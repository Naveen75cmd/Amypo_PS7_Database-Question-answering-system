"""Phase 8 add-ons: each one implemented must have a test that proves it.

These assert the *mechanism*, not just the presence of a string: the tier
selector must actually change tier on RAM, the pre-warmer must actually insert
cache entries, and the carbon estimate must actually track the work done.
"""

from __future__ import annotations

import pytest


# --- item 4: quantized-model auto-downgrade (three tiers) -----------------


def _bare_client():
    """An LLMClient with no network probe, for exercising the tier selector."""
    from app.llm.client import LLMClient

    client = LLMClient.__new__(LLMClient)
    client.model = "phi3:mini"
    client.fallback_model = "tinyllama"
    client._available_models = {"phi3:mini", "tinyllama:latest"}
    client.tier = "primary"
    client.downgrade_reason = None
    return client


@pytest.fixture()
def pinned_ram(monkeypatch: pytest.MonkeyPatch):
    """Pin host RAM so the tier depends on the fixture, not the machine."""
    import app.llm.client as client_module

    state = {"mb": 4000}

    def _set(mb: int) -> None:
        state["mb"] = mb

    monkeypatch.setattr(client_module, "_ram_available_mb", lambda: state["mb"])
    return _set


def test_tier_primary_when_ram_is_plenty(pinned_ram) -> None:
    pinned_ram(4000)
    assert _bare_client().select_model() == ("phi3:mini", "primary")


def test_tier_downgrades_to_tinyllama_when_ram_drops(pinned_ram) -> None:
    """Item 4: phi3:mini -> tinyllama, not phi3 -> extractive."""
    from app.core.settings import settings

    pinned_ram(settings.llm_downgrade_ram_mb - 100)
    model, tier = _bare_client().select_model()
    assert (model, tier) == ("tinyllama", "downgraded")


def test_tier_three_is_extractive_at_the_ram_floor(pinned_ram) -> None:
    from app.core.settings import settings

    pinned_ram(settings.ram_floor_mb - 100)
    model, tier = _bare_client().select_model()
    assert tier == "extractive"
    assert model == ""


def test_tiers_are_ordered_by_ram(pinned_ram) -> None:
    """Walking RAM down must visit primary -> downgraded -> extractive once."""
    from app.core.settings import settings

    client = _bare_client()
    seen = []
    for mb in (4000, settings.llm_downgrade_ram_mb - 1, settings.ram_floor_mb - 1):
        pinned_ram(mb)
        seen.append(client.select_model()[1])
    assert seen == ["primary", "downgraded", "extractive"]


def test_tier_never_selects_a_model_that_is_not_pulled(pinned_ram) -> None:
    """Downgrading to a model Ollama does not have would fail every request."""
    from app.core.settings import settings

    client = _bare_client()
    client._available_models = {"phi3:mini"}  # tinyllama NOT pulled
    pinned_ram(settings.llm_downgrade_ram_mb - 100)
    assert client.select_model() == ("phi3:mini", "primary")


def test_tiering_can_be_disabled(pinned_ram, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.settings import settings

    pinned_ram(400)
    monkeypatch.setattr(settings, "llm_tiering", False)
    assert _bare_client().select_model()[1] == "primary"


def test_extractive_tier_answers_without_a_model() -> None:
    """Tier 3 must still answer by quoting evidence, not return nothing."""
    from app.llm.client import extractive_answer
    from app.llm.prompts import ContextBlock

    context = [
        ContextBlock(
            index=1,
            record_id="doc:attendance-policy#0",
            title="Attendance Policy",
            text="Students must maintain a minimum of 75% attendance to sit "
            "the end-semester examination.",
        )
    ]
    answer = extractive_answer("What attendance is needed to sit exams?", context)
    assert "75%" in answer
    assert "[S1]" in answer


# --- item 5: predictive pre-warming --------------------------------------


def test_preload_query_history_returns_the_logged_questions() -> None:
    from app.eval.benchmark import load_query_history

    history = load_query_history()
    # Either the file exists and gives us questions, or it is absent and we get
    # an empty list -- never an exception, since ingest calls this.
    assert isinstance(history, list)
    assert all(isinstance(q, str) and q for q in history)


def test_preload_probes_every_attempted_question(monkeypatch: pytest.MonkeyPatch) -> None:
    """Item 5: frequently-logged questions are checked against the cache."""
    from app.eval.preload import preload_cache

    probed: list[str] = []
    stored: list[str] = []

    class FakeCache:
        def lookup(self, question: str, access_scope: str = "public"):  # type: ignore[no-untyped-def]
            probed.append(question)
            return None  # cold, so warming proceeds

        def store(self, question, answer, sources, confidence, access_scope="public", **kw):  # type: ignore[no-untyped-def]
            stored.append(question)
            return "key"

    history = [f"question {i}?" for i in range(10)]
    report = preload_cache(
        FakeCache(),
        answer_fn=lambda q: ("an answer", [], 0.9),
        questions=history,
        top_n=3,
    )
    assert report["attempted"] == 3
    assert report["warmed"] == 3
    assert probed == history[:3]
    assert stored == history[:3]


def test_preload_skips_questions_that_cannot_be_answered() -> None:
    """A non-answer must never be cached as if it were one."""
    from app.eval.preload import preload_cache

    stored: list[str] = []

    class FakeCache:
        def lookup(self, question: str, access_scope: str = "public"):  # type: ignore[no-untyped-def]
            return None

        def store(self, question, *a, **k):  # type: ignore[no-untyped-def]
            stored.append(question)

    report = preload_cache(
        FakeCache(),
        answer_fn=lambda q: None if "unanswerable" in q else ("ans", [], 0.9),
        questions=["answerable?", "unanswerable?"],
        top_n=5,
    )
    assert report["skipped"] == 1
    assert report["warmed"] == 1
    assert stored == ["answerable?"]


def test_preload_is_disabled_by_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.settings import settings
    from app.eval.preload import preload_cache

    monkeypatch.setattr(settings, "cache_prewarm_n", 0)
    report = preload_cache(object(), answer_fn=lambda q: ("a", [], 0.9), questions=["q?"])
    assert report["attempted"] == 0
    assert report["warmed"] == 0


def test_prewarm_scopes_match_what_the_router_looks_up() -> None:
    """A warmed entry must be filed where requests actually look.

    ``scope_identity`` is the inverse of ``router.engine.cache_scope``. If they
    drift, every warmed entry lands in the anonymous scope and the near-zero-cost
    cache hit the demo depends on never happens.
    """
    from app.core.settings import settings
    from app.eval.preload import scope_identity
    from app.router.engine import cache_scope

    for scope in settings.cache_prewarm_scopes:
        user_id, role = scope_identity(scope)
        assert cache_scope(user_id, role) == scope


def test_ingest_prewarms_the_cache_when_asked(temp_db, monkeypatch, tmp_path) -> None:
    """Item 5 is only real if something calls the warmer: ingest does."""
    from app.ingest.pipeline import ingest_all

    calls: list[str] = []

    def fake_warm() -> dict[str, int]:
        calls.append("warm")
        return {"attempted": 3, "warmed": 2, "already_warm": 0, "failed": 0,
                "skipped": 1}

    # Patched where the ingest imports it, so the wiring is what is under test.
    monkeypatch.setattr("app.eval.preload.warm_from_pipeline", fake_warm)
    result = ingest_all(path=tmp_path, structured_dir=tmp_path / "none", warm=True)
    assert calls == ["warm"], "ingest must pre-warm the cache"
    assert result.warmed == 2


def test_ingest_can_skip_prewarming(temp_db, monkeypatch, tmp_path) -> None:
    from app.ingest.pipeline import ingest_all

    def explode() -> dict[str, int]:  # pragma: no cover - must not be reached
        raise AssertionError("pre-warm ran despite warm=False")

    monkeypatch.setattr("app.eval.preload.warm_from_pipeline", explode)
    result = ingest_all(path=tmp_path, structured_dir=tmp_path / "none", warm=False)
    assert result.warmed == 0


def test_preload_failure_never_propagates() -> None:
    """One bad question must not abort the ingest that triggers the warm run."""
    from app.eval.preload import preload_cache

    class ExplodingCache:
        def lookup(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("db down")

        def store(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("db down")

    report = preload_cache(
        ExplodingCache(), answer_fn=lambda q: ("a", [], 0.9), questions=["q?"], top_n=1
    )
    assert report["failed"] == 1
    assert report["warmed"] == 0


# --- item 3: confidence-aware abstention asks a clarifying question -------


def test_abstention_offers_a_clarifying_question() -> None:
    from app.llm.prompts import build_clarifying_question

    question = build_clarifying_question(
        "What is the attendance policy?", closest=["Attendance Policy"]
    )
    assert question, "an abstention must ask for what is missing"
    assert "?" in question


def test_clarifying_question_is_absent_for_empty_input() -> None:
    from app.llm.prompts import build_clarifying_question

    assert build_clarifying_question("   ", closest=[]) is None


# --- item 6: conflict detector is surfaced, not just resolved -------------


def test_conflicting_sources_are_marked_in_the_answer() -> None:
    from app.grounding.conflicts import detect_conflict

    conflict = detect_conflict(
        [
            type("B", (), {"title": "Attendance Policy", "text": "minimum of 75% "
                  "attendance", "index": 1})(),
            type("B", (), {"title": "Attendance Policy (2019, superseded)",
                           "text": "minimum of 60% attendance", "index": 2})(),
        ]
    )
    assert conflict is not None, "two disagreeing sources must be detected"
    assert conflict["newer_title"] == "Attendance Policy"
    assert conflict["superseded_title"].startswith("Attendance Policy (2019")
    assert conflict["winner_value"] == "75%"


def test_conflict_payload_validates_against_the_response_model() -> None:
    """The detector's dict must be exactly what ``ConflictPayload`` accepts.

    This is a regression test for a live 500: the detector emitted extra keys
    (``detected``), the strict response model rejected them, and every answer
    that happened to contain a conflict failed with a validation error instead
    of being returned. Detection needs a real model to fire, so the bug was
    invisible in extractive-only runs.
    """
    from app.core.schemas import ConflictPayload
    from app.grounding.conflicts import detect_conflict

    conflict = detect_conflict(
        [
            type("B", (), {"title": "Attendance Policy", "text": "minimum of 75% "
                  "attendance", "index": 1})(),
            type("B", (), {"title": "Attendance Policy (2019, superseded)",
                           "text": "minimum of 60% attendance", "index": 2})(),
        ]
    )
    assert conflict is not None
    model = ConflictPayload(**conflict)  # raises on any extra/missing field
    assert model.newer_index == 1 and model.superseded_index == 2


def test_agreeing_sources_do_not_report_a_conflict() -> None:
    from app.grounding.conflicts import detect_conflict

    blocks = [
        type("B", (), {"title": "Attendance Policy", "text": "minimum of 75% attendance",
                       "index": 1})(),
        type("B", (), {"title": "Fee Policy", "text": "minimum of 75% attendance",
                       "index": 2})(),
    ]
    # Same value, no supersession marker -> nothing to reconcile.
    assert detect_conflict(blocks) is None


# --- item 9: carbon / energy estimate per query ---------------------------


def test_carbon_estimate_tracks_the_route_taken() -> None:
    from app.eval.carbon import estimate_query_energy

    local = estimate_query_energy(route="offline_fallback", latency_ms=120)
    cloud = estimate_query_energy(route="cloud", latency_ms=1800)

    assert local["kwh"] > 0 and cloud["kwh"] > 0
    # A local answer must beat the round trip to the cloud on energy.
    assert local["kwh"] < cloud["kwh"]
    assert local["inr"] > 0 and cloud["inr"] > 0
    assert cloud["inr"] > local["inr"], "cloud must cost more per call"
    for payload in (local, cloud):
        assert set(payload) == {"kwh", "inr", "source"}


# --- item 10: multilingual input (experimental) ---------------------------


def test_language_detection_identifies_supported_scripts() -> None:
    from app.llm.language import detect_language

    assert detect_language("What is the attendance requirement?") == "en"
    assert detect_language("வருகை தவறாமல் இருக்க வேண்டும்") == "ta"
    assert detect_language("பள்ளிக்குச் செல்ல வேண்டும்") == "ta"
    assert detect_language("छात्र को 75% उपस्थिति चाहिए") == "hi"


def test_language_detection_is_opt_in_and_never_breaks_english() -> None:
    from app.llm.language import detect_language

    # English is always returned as English regardless of config; detection of
    # other scripts is marked experimental rather than blocking the request.
    assert detect_language("") == "en"
    assert detect_language("1234") == "en"


# --- item 1: query_log feedback is queryable for retraining ---------------


def test_feedback_column_is_readable_for_retraining(temp_db) -> None:
    """The thumbs column exists so the classifier can be retrained from it."""
    from app.db import query

    rows = query("SHOW COLUMNS FROM query_log LIKE 'feedback'")
    assert rows, "query_log must carry a feedback column for thumbs retraining"


def test_classifier_retrain_reports_an_accuracy_delta() -> None:
    from app.router.classifier import ComplexityClassifier

    classifier = ComplexityClassifier.train(save=False)
    report = classifier.report
    assert report is not None, "training must produce a report the dashboard can show"
    # The dashboard's headline ("improved from 84% to 89%") needs a number.
    assert 0.0 <= report.accuracy <= 1.0
    payload = report.as_dict()
    assert "accuracy" in payload and "macro_f1" in payload
    assert payload["samples"] > 0


def _rate(temp_db, rows: list[tuple[str, str, int]]) -> None:
    """Insert (question, complexity, feedback) triples into the live schema."""
    from app.db import execute

    for i, (question, complexity, feedback) in enumerate(rows):
        request_id = f"rated-{i}"
        execute(
            "REPLACE INTO query_log (request_id, question, `role`, feedback, created_at) "
            "VALUES (?, ?, 'student', ?, '2026-10-11T00:00:00')",
            (request_id, question, feedback),
        )
        execute(
            "INSERT INTO router_decisions (request_id, query, routed_to, reasoning, "
            "complexity, latency_ms, estimated_cost, always_cloud_cost, created_at) "
            "VALUES (?, ?, 'local_model', 'test', ?, 10.0, 0.02, 1.75, "
            "'2026-10-11T00:00:00')",
            (request_id, question, complexity),
        )


def test_feedback_examples_confirm_upvotes_and_correct_downvotes(temp_db) -> None:
    """Item 1: a thumbs-up is a label, a thumbs-down is a correction."""
    from app.router.classifier import feedback_examples

    _rate(
        temp_db,
        [
            ("What is my CGPA?", "low", 1),
            ("Who is eligible for TCS Digital?", "low", -1),
            ("Compare the two attendance policies", "medium", -1),
        ],
    )
    questions, labels, counts = feedback_examples()
    assert counts == {"confirmed": 1, "corrected": 2}
    by_question = dict(zip(questions, labels))
    assert by_question["What is my CGPA?"] == "low"  # confirmed as routed
    # A downvote means the router under-rated it, so the label steps up.
    assert sorted(labels) == ["high", "low", "medium"]


def test_feedback_examples_ignore_rows_without_a_complexity(temp_db) -> None:
    """A rating for a question the router never classified teaches nothing."""
    from app.db import execute
    from app.router.classifier import feedback_examples

    execute(
        "REPLACE INTO query_log (request_id, question, `role`, feedback, created_at) "
        "VALUES (?, ?, 'student', 1, '2026-10-11T00:00:00')",
        ("orphan", "What is my CGPA?"),
    )
    questions, labels, counts = feedback_examples()
    assert questions == [] and labels == []
    assert counts == {"confirmed": 0, "corrected": 0}


def test_retrain_folds_feedback_into_the_training_set(temp_db, monkeypatch) -> None:
    """The retrain must grow its training set from live feedback, not just say so."""
    from app.router.classifier import ComplexityClassifier

    baseline = ComplexityClassifier.train(save=False, use_feedback=False)
    assert baseline.report.from_feedback == 0

    monkeypatch.setattr(
        "app.router.classifier.feedback_examples",
        lambda limit=None: (
            ["What is my CGPA?"] * 4,
            ["high"] * 4,
            {"confirmed": 0, "corrected": 4},
        ),
    )
    retrained = ComplexityClassifier.train(save=False)
    report = retrained.report
    assert report.from_feedback == 4
    assert report.corrected == 4
    assert report.samples == baseline.report.samples + 4
    # Both numbers came from the same held-out questions, so they compare.
    assert report.holdout == baseline.report.holdout > 0


# --- the add-ons must actually reach the wire, not just exist ------------


ADDON_FIELDS = ("clarifying_question", "conflict", "carbon",
                 "detected_language", "model_tier")


def _ask(client, question: str) -> dict:
    resp = client.post(
        "/api/v1/ask", json={"question": question, "role": "staff"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_addon_fields_reach_the_wire(client) -> None:
    body = _ask(client, "What is the minimum attendance required to sit exams?")
    for key in ADDON_FIELDS:
        assert key in body, f"{key} missing from AskResponse: {sorted(body)}"
    # The sustainability line item must always be present and non-zero.
    assert body["carbon"] is not None
    assert set(body["carbon"]) == {"kwh", "inr", "source"}
    assert body["carbon"]["kwh"] > 0
    assert body["carbon"]["inr"] > 0


def test_abstention_offers_a_clarifying_question_on_the_wire(client) -> None:
    body = _ask(client, "What is the Wi-Fi password for the hostel?")
    if body.get("abstained"):
        assert body["clarifying_question"], (
            "an abstention must ask the user to narrow the question"
        )
    else:
        # Answered: a clarifying question would contradict the answer.
        assert body["clarifying_question"] is None


def test_closest_records_carry_what_the_user_can_act_on() -> None:
    """Item 3: an abstention names the nearest records, not just a refusal."""
    from app.api.ask_service import closest_records_from
    from app.llm.prompts import ContextBlock

    context = [
        ContextBlock(index=1, record_id="doc:hostel-policy#0",
                     title="Hostel and Residential Policy",
                     text="Hostel gates close at 21:30 on weekdays."),
        ContextBlock(index=2, record_id="doc:library-policy#4", title="Library Policy",
                     text="The digital library is reachable off campus."),
    ]
    records = closest_records_from(context)
    assert [r["record_id"] for r in records] == [
        "doc:hostel-policy#0", "doc:library-policy#4"
    ]
    assert records[0]["title"] == "Hostel and Residential Policy"
    assert records[0]["snippet"].startswith("Hostel gates close")
    # Bounded: an abstention must not dump the whole candidate list.
    assert len(closest_records_from(context * 5)) == 3


def test_abstention_offers_closest_records_on_the_wire(client) -> None:
    """The field reaches the response model (the test schema has no records)."""
    body = _ask(client, "What is the Wi-Fi password for the hostel?")
    assert "closest_records" in body
    assert isinstance(body["closest_records"], list)
    if not body["abstained"]:
        # A delivered answer lists its sources; closest records would duplicate them.
        assert body["closest_records"] == []


def test_english_input_reports_no_detected_language(client) -> None:
    assert _ask(client, "What is the attendance policy?")[
        "detected_language"
    ] is None


def test_tamil_input_is_detected_end_to_end(client) -> None:
    body = _ask(client, "வருகை தேவை என்ன?")
    assert body["detected_language"] == "ta"
    # Detection is observational: the request still succeeds and still answers.
    assert body["answer"]


def test_contract_yaml_documents_the_new_addon_fields() -> None:
    """openapi.yaml must document what the model actually returns."""
    from pathlib import Path

    import yaml

    from app.core.schemas import AskResponse

    root = Path(__file__).resolve().parents[2]
    spec = yaml.safe_load((root / "openapi.yaml").read_text(encoding="utf-8"))
    documented = set(
        spec["components"]["schemas"]["AskResponse"]["properties"]
    )
    model = set(AskResponse.model_fields)
    missing = set(ADDON_FIELDS) - documented
    assert not missing, f"add-ons undocumented in openapi.yaml: {sorted(missing)}"
    assert documented <= model, f"documented but not implemented: {sorted(documented - model)}"


# --- item 1: thumbs feedback actually writes to query_log ----------------


def _first_logged_request(client) -> str:
    """Ask something so there is a row to rate."""
    body = _ask(client, "What is the minimum attendance required to sit exams?")
    assert body["trace_id"], "the answer must be traceable to a request id"
    return body["trace_id"]


def test_feedback_records_a_thumbs_rating(client, temp_db) -> None:
    from app.db import query

    request_id = _first_logged_request(client)
    resp = client.post(
        "/api/v1/ask/feedback", json={"request_id": request_id, "rating": 1}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recorded"] is True
    assert body["rating"] == 1

    rows = query(
        "SELECT feedback FROM query_log WHERE request_id = ?", (request_id,)
    )
    assert rows and rows[0]["feedback"] == 1, "thumbs must reach query_log.feedback"


def test_feedback_can_record_a_downvote(client) -> None:
    request_id = _first_logged_request(client)
    resp = client.post(
        "/api/v1/ask/feedback", json={"request_id": request_id, "rating": -1}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rating"] == -1


def test_feedback_for_unknown_request_does_not_error(client) -> None:
    """A dropped thumb must never break the UI, even on a stale id."""
    resp = client.post(
        "/api/v1/ask/feedback", json={"request_id": "no-such-id", "rating": 1}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["recorded"] is False


def test_feedback_rejects_an_out_of_range_rating(client) -> None:
    resp = client.post(
        "/api/v1/ask/feedback",
        json={"request_id": "whatever", "rating": 5},
    )
    assert resp.status_code == 422, resp.text


def test_feedback_column_is_empty_until_rated(client) -> None:
    from app.db import query

    request_id = _first_logged_request(client)
    rows = query(
        "SELECT feedback FROM query_log WHERE request_id = ?", (request_id,)
    )
    assert rows, "the answer must have been logged"
    assert rows[0]["feedback"] is None, "no thumb yet means NULL, not 0"


# --- item 1b: retrain reports the delta the dashboard shows --------------


def test_retrain_endpoint_reports_an_accuracy_delta(client) -> None:
    resp = client.post("/api/v1/router/retrain")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert 0.0 <= body["accuracy"] <= 1.0
    assert body["samples"] > 0
    assert "macro_f1" in body
    # Either we compared against a previous model, or there was none to compare.
    if body["previous_accuracy"] is not None:
        assert 0.0 <= body["previous_accuracy"] <= 1.0
        assert body["delta"] is not None
        assert abs(body["delta"]) < 1.0


def test_retrain_is_a_post_not_a_get(client) -> None:
    """Retraining mutates state; it must not be triggerable by a GET."""
    assert client.get("/api/v1/router/retrain").status_code in {404, 405}


# --- item 7: the cohort audit trail is readable, not just written --------


def _audit_row(question: str = "eligibility company=Zoho", count: int = 3) -> None:
    from app.db import execute

    execute(
        "INSERT INTO cohort_queries (kind, query, company, `role`, result_count, "
        "created_at) VALUES ('eligibility', ?, 'Zoho', 'staff', ?, ?)",
        (question, count, "2026-10-11T00:00:00"),
    )


def test_cohort_audit_trail_is_staff_only(client) -> None:
    """Writing the row is not a control; reading it back is."""
    _audit_row()
    denied = client.get(
        "/api/v1/placement/cohort-queries", params={"requester_role": "student"}
    )
    assert denied.status_code == 403, denied.text


def test_cohort_audit_trail_lists_the_query_metadata(client) -> None:
    _audit_row(count=3)
    resp = client.get(
        "/api/v1/placement/cohort-queries",
        params={"requester_role": "staff", "limit": 10},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows, "the audit trail must show the row that was just written"
    assert rows[0]["kind"] == "eligibility"
    assert rows[0]["result_count"] == 3
    assert rows[0]["query"] == "eligibility company=Zoho"


def test_cohort_audit_trail_rejects_an_unbounded_limit(client) -> None:
    resp = client.get(
        "/api/v1/placement/cohort-queries",
        params={"requester_role": "staff", "limit": 100000},
    )
    assert resp.status_code == 422, resp.text


# --- item 11: downloadable PDF eligibility report ------------------------


@pytest.fixture()
def seeded_student(temp_db):
    """One student and one role, reusing the Phase 6 seeding helpers."""
    from test_placement import _seed, _student

    _seed()
    _student("T001", name="Test Student")
    return "T001"


def _pdf(client, student_id: str, **params):
    return client.get(
        f"/api/v1/placement/eligibility/{student_id}/report.pdf", params=params
    )


def test_pdf_report_is_served_as_a_real_pdf(client, seeded_student) -> None:
    resp = _pdf(client, seeded_student, user_id=seeded_student,
                requester_role="student")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    body = resp.content
    # A PDF must start with the magic bytes and contain a trailer.
    assert body[:5] == b"%PDF-", f"not a PDF: {body[:20]!r}"
    assert b"%%EOF" in body[-1024:], "PDF is truncated"
    assert "attachment" in resp.headers["content-disposition"]
    assert f"eligibility-{seeded_student}.pdf" in resp.headers["content-disposition"]


def test_pdf_report_is_non_trivial(client, seeded_student) -> None:
    resp = _pdf(client, seeded_student, user_id=seeded_student,
                requester_role="student")
    assert resp.status_code == 200
    # An empty shell would technically be a PDF; require real page content.
    assert len(resp.content) > 2000, f"suspiciously small: {len(resp.content)} bytes"


def test_pdf_report_names_the_student_and_a_verdict(client, seeded_student) -> None:
    """The artefact must carry the data it claims to report."""
    from pypdf import PdfReader
    import io

    resp = _pdf(client, seeded_student, user_id=seeded_student,
                requester_role="student")
    assert resp.status_code == 200
    reader = PdfReader(io.BytesIO(resp.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Test Student" in text, "report must name the student"
    assert "TestCo" in text, "report must list the role evaluated"
    assert "ELIGIBLE" in text or "not eligible" in text, "report must state a verdict"


def test_pdf_report_denies_exporting_another_students_record(
    client, seeded_student
) -> None:
    """The export must enforce the same scope as the JSON endpoint."""
    resp = _pdf(client, seeded_student, user_id="S999", requester_role="student")
    assert resp.status_code == 403, resp.text


def test_pdf_report_404s_for_unknown_student(client) -> None:
    resp = _pdf(client, "NOPE", user_id="NOPE", requester_role="staff")
    assert resp.status_code == 404, resp.text


def test_pdf_export_is_documented_in_openapi() -> None:
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    spec = yaml.safe_load((root / "openapi.yaml").read_text(encoding="utf-8"))
    assert "/placement/eligibility/{student_id}/report.pdf" in spec["paths"]
