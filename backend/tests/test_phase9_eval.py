"""Phase 9: the evaluation harness, its report, and the /eval/run endpoint.

The harness runs the real pipeline (never a mock), so the smoke run is
module-scoped: one shared run keeps the suite fast while every assertion still
checks the actual artefacts ``make eval`` produces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

NEEDED_KEYS = {
    "run_id",
    "generated_at",
    "scope",
    "config",
    "methodology",
    "answers",
    "per_item",
    "citation_validity",
    "retrieval",
    "routing",
    "ablations",
    "scenarios",
    "sweeps",
    "load_test",
    "failure_analysis",
    "resources",
    "access_control",
    "headline",
}


@pytest.fixture(scope="module")
def report() -> dict:
    """One small, real harness run shared by the assertions below."""
    corpus = PROJECT_ROOT / "data" / "raw" / "attendance-policy.md"
    if not corpus.exists():
        pytest.skip("run scripts/generate_data.py then python -m app.ingest first")
    from app.eval.harness import EvalOptions, run_harness

    return run_harness(
        EvalOptions(
            limit=8,
            include_scenarios=True,
            include_sweeps=True,
            include_load_test=False,
            write_report=False,
        )
    )


def test_access_control_red_team_reports_zero_leaks(report) -> None:
    """Phase 9, item 5: 30+ prompts and requests per role, leak count in the report."""
    access = report["access_control"]
    assert access["ran"] is True
    assert access["leaks"] == 0, [f for f in access["failures"]]
    assert access["inconclusive_count"] == 0, access["inconclusive"]
    assert access["skipped_count"] == 0, access["skipped"]
    assert access["passed"] is True
    # The plan's size requirement, counted from cases that really ran.
    for role in ("student", "staff", "admin"):
        bucket = access["per_role"][role]
        assert bucket["cases"] >= 30, (role, bucket)
        assert bucket["cases"] == bucket["prompts"] + bucket["requests"]
    # Every attack vector was actually exercised, and the prompt cases really
    # came back with answers to inspect — a suite that 401'd its own prompts
    # would otherwise "pass" while proving nothing.
    assert access["by_vector"]["prompt_injection"]["cases"] >= 10
    assert access["by_vector"]["role_matrix"]["cases"] > 0
    assert access["by_vector"]["forged_credentials"]["cases"] > 0
    assert access["prompts_answered"] > 0
    assert access["prompts_unexpected"] == 0
    assert report["headline"]["access_control_leaks"] == 0
    assert report["headline"]["access_control_pass"] is True


def test_red_team_catalogue_alone_meets_the_30_case_rule() -> None:
    """Countable without running: the plan fixes the size, not just the result."""
    from app.eval.access_control import cases_per_role

    counts = cases_per_role()
    for role in ("student", "staff", "admin"):
        assert counts[role] >= 30, (role, counts[role])


def test_harness_produces_every_report_block(report) -> None:
    assert NEEDED_KEYS <= set(report), sorted(NEEDED_KEYS - set(report))
    answers = report["answers"]
    assert answers["total"] == 8
    assert 0.0 <= answers["accuracy"] <= 1.0
    assert 0.0 <= answers["groundedness"] <= 1.0
    # Every answerable item scored exactly once, and per-kind buckets sum to n.
    buckets = answers["per_kind"]
    assert sum(b["n"] for b in buckets.values()) == answers["total"]
    # Retrieval ablation: four modes, all four reported.
    assert {"dense", "bm25", "hybrid", "hybrid_rerank"} == set(report["retrieval"])
    assert report["retrieval"]["hybrid_rerank"]["mrr"] >= 0.0
    # Routing: agreement and the always-cloud cost baseline are present.
    routing = report["routing"]
    assert routing["questions"] == 8
    assert routing["always_cloud_cost_inr"] > 0
    assert routing["cumulative_cost_inr"] <= routing["always_cloud_cost_inr"]
    # Peak RAM is measured (psutil), not guessed, and must respect the budget.
    assert report["resources"]["peak_rss_mb"] > 0
    assert report["resources"]["within_budget"] is True
    # Methodology must document how each headline number was derived.
    assert "accuracy" in report["methodology"]
    assert "hallucination_rate" in report["methodology"]


def test_scenario_suite_passes(report) -> None:
    """RAM crash, Ollama down, quota, offline and bandwidth all behave."""
    scenarios = report["scenarios"]
    names = [s["scenario"] for s in scenarios]
    assert names == [
        "stable",
        "ram_crash",
        "ollama_crash",
        "quota_exhausted",
        "offline",
        "bandwidth_degrading",
    ]
    failed = [s for s in scenarios if not s["passed"]]
    assert not failed, [f"{s['scenario']}: {s['detail']}" for s in failed]


def test_threshold_sweeps_carry_the_chosen_operating_point(report) -> None:
    sweeps = report["sweeps"]
    verifier = sweeps["verifier_threshold"]
    assert [p["threshold"] for p in verifier["points"]] == [
        0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80,
    ]
    assert verifier["chosen_point"] is not None, "current config must appear in the sweep"
    cache = sweeps["cache_cosine"]
    assert cache["points"] and cache["chosen"] == 0.92
    ram = sweeps["ram_floor"]
    assert {p["floor_mb"] for p in ram["points"]} == {512, 900, 1500, 2600, 4096}
    assert sum(1 for p in ram["points"] if p["is_current"]) == 1
    # The relevance floor is the knob the model card's accuracy-vs-hallucination
    # argument cites, so the report must carry its curve, not just prose.
    relevance = sweeps["relevance_floor"]
    assert relevance["chosen_point"] is not None
    assert relevance["chosen_point"]["accuracy"] == report["answers"]["accuracy"]
    assert relevance["chosen_point"]["hallucinated"] == report["answers"]["hallucinated"]
    # The sweep must start from the gate switched off, so the report shows what
    # the floor buys rather than only points above it.
    assert relevance["points"][0]["floor"] == 0.0


def _fake_gate_pipeline(scores: dict[str, float]) -> object:
    """A pipeline whose only behaviour is the relevance gate.

    Each question has a fixed best-BM25 score, and the stub abstains exactly
    when that score is below ``settings.retrieval_relevance_floor`` -- the same
    rule ``AskPipeline`` applies *before* generation, which is what makes the
    sweep a real measurement rather than a re-derivation.
    """
    from types import SimpleNamespace

    from app.core.settings import settings

    class _Pipeline:
        def answer(self, question: str, user_id=None, role=None, force_extractive=False):
            relevance = scores[question]
            gated = relevance < settings.retrieval_relevance_floor
            if gated:
                return SimpleNamespace(
                    abstained=True,
                    answer="Not in the corpus.",
                    confidence=0.0,
                    sources=[],
                    retrieval=[{"record_id": "r0", "bm25_score": relevance}],
                    grounding=SimpleNamespace(
                        groundedness=0.0,
                        supported_claims=0,
                        total_claims=0,
                        numeric_violations=[],
                    ),
                )
            # Every stub item's expected answer is the text below, so the scorer
            # calls it correct whenever the gate lets it through.
            return SimpleNamespace(
                abstained=False,
                answer=f"minimum attendance is 75% [S1] ({question})",
                confidence=0.95,
                sources=[SimpleNamespace(record_id=f"gold-{question}")],
                retrieval=[{"record_id": f"gold-{question}", "bm25_score": relevance}],
                grounding=SimpleNamespace(
                    groundedness=1.0,
                    supported_claims=1,
                    total_claims=1,
                    numeric_violations=[],
                ),
            )

    return _Pipeline()


def test_relevance_sweep_measures_each_floor_with_a_real_pass(monkeypatch) -> None:
    """Raising the floor can only withhold answers, and each point is measured."""
    from app.core.settings import settings
    from app.eval.benchmark import BenchmarkItem
    from app.eval.harness import EvalOptions, _NoRouteEngine, _answer_pass, _relevance_sweep

    monkeypatch.setattr(settings, "retrieval_relevance_floor", 9.0)
    expected = "minimum attendance is 75%"
    items = [
        BenchmarkItem("a1", "answered high", expected, ["gold-answered high"]),
        BenchmarkItem("a2", "answered low", expected, ["gold-answered low"]),
        BenchmarkItem("u1", "hallucinated high", expected, ["gold-hallucinated high"], answerable=False),
        BenchmarkItem("u2", "hallucinated low", expected, ["gold-hallucinated low"], answerable=False),
    ]
    pipeline = _fake_gate_pipeline(
        {
            "answered high": 20.0,
            "answered low": 11.0,
            "hallucinated high": 15.0,
            "hallucinated low": 9.5,
        }
    )

    # The delivered pass at the shipped floor is what the sweep reuses.
    summary, _rows, _cited = _answer_pass(pipeline, _NoRouteEngine(), items, EvalOptions())
    sweep = _relevance_sweep(pipeline, items, EvalOptions(), summary)

    floors = [p["floor"] for p in sweep["points"]]
    assert floors == sorted(floors) and floors[0] == 0.0
    assert sweep["chosen"] == 9.0
    assert sweep["chosen_point"]["accuracy"] == summary["accuracy"]
    assert sweep["chosen_point"]["hallucinated"] == summary["hallucinated"]

    gate_off = sweep["points"][0]
    assert (gate_off["answered"], gate_off["correct"]) == (2, 2)
    assert gate_off["abstention_rate_unanswerable"] == 0.0
    assert gate_off["hallucinated"] == 2

    at_12 = next(p for p in sweep["points"] if p["floor"] == 12.0)
    assert (at_12["answered"], at_12["correct"]) == (1, 1)  # the 11.0 answer is withheld
    assert at_12["accuracy"] == 0.5
    assert at_12["hallucinated"] == 1  # only the 15.0 hallucination survives
    assert at_12["abstention_rate_unanswerable"] == 0.5

    for earlier, later in zip(sweep["points"], sweep["points"][1:]):
        assert later["answered"] <= earlier["answered"]
        assert later["hallucinated"] <= earlier["hallucinated"]
        assert later["abstention_rate_unanswerable"] >= earlier["abstention_rate_unanswerable"]


def test_failure_analysis_lists_at_most_ten_worst(report) -> None:
    failures = report["failure_analysis"]
    assert len(failures) <= 10
    for failure in failures:
        assert failure["cause"] and failure["fix"], failure["id"]
        assert failure["kind_of"] in {"wrong", "hallucination"}


def test_to_eval_response_matches_the_api_schema(report) -> None:
    from app.core.schemas import EvalRunResponse
    from app.eval.harness import to_eval_response

    payload = to_eval_response(report)
    assert set(payload) == set(EvalRunResponse.model_fields), (
        sorted(set(EvalRunResponse.model_fields) - set(payload)),
        sorted(set(payload) - set(EvalRunResponse.model_fields)),
    )
    response = EvalRunResponse(**payload)
    assert response.total == 8
    assert response.report_path is None  # this run did not write files
    assert 0.0 <= response.accuracy <= 1.0


def test_write_report_writes_json_and_standalone_html(report, tmp_path, monkeypatch) -> None:
    from app.core.settings import settings
    from app.eval.report import write_report

    monkeypatch.setattr(settings, "docs_dir", tmp_path)
    json_path, html_path = write_report(report)

    assert json_path == tmp_path / "eval" / "report.json"
    assert html_path == tmp_path / "eval" / "report.html"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["run_id"] == report["run_id"]

    html_text = html_path.read_text(encoding="utf-8")
    assert html_text.startswith("<!doctype html>")
    # The sections a judge must find in the artefact.
    for marker in (
        "Headline",
        "Answers",
        "Ablations",
        "Threshold sweeps",
        "Resource scenarios",
        "Load test",
        "Failure analysis",
        "Methodology",
        report["run_id"],
    ):
        assert marker in html_text, marker
    # No external assets: the report must open offline from disk. The config
    # block legitimately names the loopback Ollama endpoint when a model is
    # running, so only a non-loopback URL would mean the report needs a network.
    offline_text = html_text.replace("http://127.0.0.1", "").replace(
        "http://localhost", ""
    )
    assert "http://" not in offline_text and "https://" not in offline_text
    assert "<script" not in html_text


def test_eval_endpoint_returns_metrics(client, temp_db) -> None:
    """POST /api/v1/eval/run answers 200 with every EvalRunResponse field.

    The test schema has no corpus, so this proves the wiring (options ->
    harness -> response mapping), not quality numbers; the module-scoped run
    above covers those against the seeded database.
    """
    from app.core.schemas import EvalRunResponse

    resp = client.post(
        "/api/v1/eval/run", json={"limit": 4, "kinds": None, "write_report": False}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == set(EvalRunResponse.model_fields)
    assert body["run_id"]
    assert body["total"] >= 1
    assert body["peak_ram_mb"] > 0
    assert body["report_path"] is None


def test_eval_endpoint_rejects_an_empty_kind_filter(client, temp_db) -> None:
    resp = client.post(
        "/api/v1/eval/run", json={"limit": 4, "kinds": ["no-such-kind"], "write_report": False}
    )
    assert resp.status_code == 422, resp.text


def test_evaluate_script_is_the_make_eval_entry_point() -> None:
    """`make eval` runs scripts/evaluate.py; its CLI must parse --help.

    Run in-process with runpy rather than as a subprocess: on Windows, a
    freshly spawned interpreter can fail to initialise (STATUS_DLL_INIT_FAILED)
    when the suite holds the whole index in RAM, which would report the *script*
    as broken when it is the machine that could not start a process. Executing
    the file as ``__main__`` exercises the same argparse entry point and the
    same imports, and fails for the same reasons a real failure would.
    """
    import io
    import runpy
    from contextlib import redirect_stdout

    script = PROJECT_ROOT / "scripts" / "evaluate.py"
    assert script.exists(), "scripts/evaluate.py is the Phase 9 CLI entry point"
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "scripts/evaluate.py" in makefile

    argv, captured = sys.argv[:], io.StringIO()
    sys.argv = [str(script), "--help"]
    try:
        with redirect_stdout(captured):
            with pytest.raises(SystemExit) as exit_info:
                runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = argv

    assert exit_info.value.code == 0, captured.getvalue()
    assert "usage" in captured.getvalue().lower()
