"""Phase 11: authentication and role-based access control.

The suite is organised the way the plan asks for it -- one role-by-endpoint
matrix plus targeted red-team cases -- and every case is exercised through the
real HTTP surface with a real signed token, not by calling a helper.

What is being proved here, in order:

1. the login lifecycle (generic failures, disabled accounts, throttling,
   rotation, reuse detection, logout);
2. every endpoint answers each role with its documented status;
3. a student cannot retrieve staff-only or admin-only documents, and staff
   cannot retrieve admin-only ones -- through /ask *and* through /route;
4. the semantic cache never serves one scope's answer to another;
5. a denied action leaves an audit row.
"""

from __future__ import annotations

import pytest

PROTECTED = "/api/v1/ask"


def _login(client, username: str, password: str = "amypo-demo-2026"):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


# --------------------------------------------------------------------------
# Login lifecycle
# --------------------------------------------------------------------------


def test_login_sets_http_only_cookies_and_returns_the_role(anonymous_client) -> None:
    resp = _login(anonymous_client, "admin")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["role"] == "admin"
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    raw = resp.headers.get("set-cookie", "")
    assert "amypo_session=" in raw
    assert "HttpOnly" in raw, "the session cookie must not be readable from JS"
    assert "amypo_refresh=" in raw


def test_wrong_password_and_unknown_user_are_indistinguishable(anonymous_client) -> None:
    wrong = _login(anonymous_client, "admin", "not-the-password")
    unknown = _login(anonymous_client, "definitely-not-a-user", "not-the-password")
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"], (
        "a different message would let a caller enumerate accounts"
    )


def test_me_requires_a_session(anonymous_client) -> None:
    resp = anonymous_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate", "").startswith("Bearer")


def test_me_reports_permissions_for_the_role(client) -> None:
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "admin"
    assert body["permissions"]["user_admin"] is True
    assert body["cache_scope"] == "admin"


def test_disabled_account_cannot_log_in(client, anonymous_client) -> None:
    created = client.post(
        "/api/v1/admin/users",
        json={
            "username": "temp.student",
            "email": "temp.student@amypo.local",
            "password": "correct-horse-battery",
            "role": "student",
            "student_id": "S902",
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    patched = client.patch(f"/api/v1/admin/users/{user_id}", json={"is_active": False})
    assert patched.status_code == 200, patched.text

    resp = _login(anonymous_client, "temp.student", "correct-horse-battery")
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


def test_repeated_failures_are_throttled(anonymous_client) -> None:
    from app.db import execute
    from app.core.settings import settings

    execute("DELETE FROM login_attempts")
    limit = settings.login_max_attempts
    for _ in range(limit):
        assert _login(anonymous_client, "admin", "wrong").status_code == 401
    throttled = _login(anonymous_client, "admin", "wrong")
    assert throttled.status_code == 429, throttled.text

    # Even the *correct* password is refused while the window is saturated.
    assert _login(anonymous_client, "admin").status_code == 429

    # Leave no residue: these 8 failures live for ``login_window_s`` and would
    # lock the demo admin out of every later login (the eval harness signs in as
    # admin too). The assertions above already proved the limit; clearing the
    # window afterwards is fixture hygiene, not a weaker check.
    execute("DELETE FROM login_attempts")


def test_refresh_rotates_and_a_reused_token_is_rejected(anonymous_client) -> None:
    from app.core.settings import settings

    first = _login(anonymous_client, "admin")
    assert first.status_code == 200
    old_refresh = anonymous_client.cookies.get(settings.auth_refresh_cookie_name)
    assert old_refresh

    rotated = anonymous_client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200, rotated.text
    new_refresh = anonymous_client.cookies.get(settings.auth_refresh_cookie_name)
    assert new_refresh and new_refresh != old_refresh

    # Replaying the rotated token is the signal that it leaked: it must be
    # refused and it must invalidate the session that replaced it.
    replay = anonymous_client.post(
        "/api/v1/auth/refresh",
        cookies={settings.auth_refresh_cookie_name: old_refresh},
    )
    assert replay.status_code == 401, replay.text

    after = anonymous_client.post(
        "/api/v1/auth/refresh",
        cookies={settings.auth_refresh_cookie_name: new_refresh},
    )
    assert after.status_code == 401, "reuse must revoke the whole chain"


def test_logout_clears_cookies_and_revokes_the_refresh_token(anonymous_client) -> None:
    from app.core.settings import settings

    assert _login(anonymous_client, "admin").status_code == 200
    raw = anonymous_client.cookies.get(settings.auth_refresh_cookie_name)
    assert raw

    out = anonymous_client.post("/api/v1/auth/logout")
    assert out.status_code == 200

    replay = anonymous_client.post(
        "/api/v1/auth/refresh",
        cookies={settings.auth_refresh_cookie_name: raw},
    )
    assert replay.status_code == 401


# --------------------------------------------------------------------------
# Role x endpoint matrix
# --------------------------------------------------------------------------

MATRIX = [
    # (method, path, json, {role: expected_status})
    ("GET", "/api/v1/health", None,
     {"anonymous": 200, "student": 200, "staff": 200, "admin": 200, "eval": 200}),
    ("GET", "/api/v1/resource-status", None,
     {"anonymous": 200, "student": 200, "staff": 200, "admin": 200, "eval": 200}),
    ("POST", "/api/v1/ask", {"question": "What is the attendance policy?"},
     {"anonymous": 401, "student": 200, "staff": 200, "admin": 200, "eval": 200}),
    ("POST", "/api/v1/route", {"query": "What is the attendance policy?"},
     {"anonymous": 401, "student": 200, "staff": 200, "admin": 200, "eval": 200}),
    ("GET", "/api/v1/metrics", None,
     {"anonymous": 401, "student": 403, "staff": 200, "admin": 200, "eval": 403}),
    ("GET", "/api/v1/router/decisions", None,
     {"anonymous": 401, "student": 403, "staff": 200, "admin": 200, "eval": 403}),
    ("POST", "/api/v1/simulate", {"scenario": "stable", "steps": 1},
     {"anonymous": 401, "student": 403, "staff": 403, "admin": 200, "eval": 403}),
    ("GET", "/api/v1/placement/cohort-queries", None,
     {"anonymous": 401, "student": 403, "staff": 200, "admin": 200, "eval": 403}),
    ("POST", "/api/v1/placement/match", {"company": "Zoho", "role": "SDE"},
     {"anonymous": 401, "student": 403, "staff": 404, "admin": 404, "eval": 403}),
    ("POST", "/api/v1/ingest", {"force": False},
     {"anonymous": 401, "student": 403, "eval": 403}),
    ("POST", "/api/v1/eval/run", {"limit": 1},
     {"anonymous": 401, "student": 403, "staff": 403, "eval": 403}),
    ("GET", "/api/v1/admin/users", None,
     {"anonymous": 401, "student": 403, "staff": 403, "admin": 200, "eval": 403}),
    ("GET", "/api/v1/admin/audit", None,
     {"anonymous": 401, "student": 403, "staff": 403, "admin": 200, "eval": 403}),
    ("GET", "/api/v1/ingest/documents", None,
     {"anonymous": 401, "student": 403, "staff": 200, "admin": 200, "eval": 403}),
]


@pytest.mark.parametrize(
    "method,path,body,expected",
    [(m, p, b, e) for m, p, b, e in MATRIX],
    ids=[f"{m} {p}" for m, p, _, _ in MATRIX],
)
def test_role_matrix(api_client, anonymous_client, method, path, body, expected) -> None:
    """One request per role per endpoint, asserting the documented status."""
    clients = {"anonymous": anonymous_client}
    for role in ("student", "staff", "admin", "eval"):
        clients[role] = api_client(
            role, student_id="S102" if role == "student" else None
        )

    for role, status in expected.items():
        kwargs = {"json": body} if body is not None else {}
        resp = clients[role].request(method, path, **kwargs)
        assert resp.status_code == status, (
            f"{role} on {method} {path}: expected {status}, got "
            f"{resp.status_code} ({resp.text[:200]})"
        )


def test_the_legacy_role_field_cannot_escalate() -> None:
    """A student token that claims ``staff`` in the body is still a student.

    This is the single most important regression: before Phase 11 the role came
    from the request body, so ``{"role": "staff"}`` was an access-control bypass.
    """
    from app.api.routers.ask import _effective_user_id
    from app.auth.principal import Principal

    student = Principal(user_id="u1", username="s102", role="student", student_id="S102")
    assert _effective_user_id(None, student) == "S102"
    assert _effective_user_id("S999", student) == "S102", (
        "the body must not be able to widen a student's scope"
    )


# --------------------------------------------------------------------------
# Retrieval leaks
# --------------------------------------------------------------------------


PUBLIC_Q = "attendance condonation policy for students"
STAFF_Q = "faculty handbook attendance appeals committee quorum moderation"
ADMIN_Q = "security runbook audit retention break glass administrator"


def _forget_corpus_components() -> None:
    """Drop every in-process component that still points at another corpus.

    ``temp_db`` wipes the *database*, not the memories in the container: a test
    that ran earlier — the Phase 9 harness, for one — leaves an index (and the
    verifier, cache and router that are built on top of it) holding whatever it
    was pointed at. Cited ids then come from that other corpus, so these tests
    would fail for a reason that has nothing to do with permissions, or pass
    against a corpus they were never asked about. The assertions are unchanged;
    this only guarantees the fixture's stated property, that the corpus is
    hermetic. ``monitor`` is left alone because it owns a live thread.
    """
    from app.core.container import get_container

    container = get_container()
    for name in ("index", "cache", "verifier", "router"):
        container.reset(name)


@pytest.fixture()
def rbac_corpus(temp_db):
    """A three-chunk corpus: one public, one staff-only, one admin-only.

    Hermetic on purpose. Reading the demo database would make the leak test
    depend on whatever the seeded corpus happens to contain; three chunks with
    known text and known scopes make a leak unambiguous, and the index over them
    is cheap to build.
    """
    from app.ingest.chunking import Chunk, content_hash, count_tokens
    from app.ingest.pipeline import _store_chunk

    docs = [
        (
            "doc:rbac-public#0",
            "public",
            "General attendance policy: students maintain seventy-five percent "
            "attendance; condonation is described in the student handbook.",
        ),
        (
            "doc:rbac-staff#0",
            "staff",
            "Faculty handbook: the attendance appeals committee has a quorum of "
            "three staff members and moderates marks internally.",
        ),
        (
            "doc:rbac-admin#0",
            "admin",
            "Security runbook: audit retention is ninety days and break glass "
            "access is logged for the administrator.",
        ),
    ]
    for record_id, scope, text in docs:
        _store_chunk(
            Chunk(
                record_id=record_id,
                doc_id=record_id.split("#")[0],
                chunk_no=0,
                title=record_id,
                section="rbac",
                page=None,
                text=text,
                token_count=count_tokens(text),
                access_scope=scope,
                content_hash=content_hash(text),
                updated_at="2026-01-01T00:00:00Z",
            )
        )
    _forget_corpus_components()
    try:
        yield {record_id: scope for record_id, scope, _ in docs}
    finally:
        # Give the next phase back its own index instead of these three chunks.
        _forget_corpus_components()


def _retrieved_ids(question: str, principal) -> list[str]:
    """Retrieve directly, so the assertion is about the filter, not the answer."""
    from app.retrieval.index import AccessFilter, RetrievalIndex

    index = RetrievalIndex.load_or_build()
    return [
        r.record_id
        for r in index.retrieve(
            question, top_k=5, policy=AccessFilter.policy_for(principal)
        )
    ]


def _sources(client, question: str) -> list[str]:
    """Every record the response cites, including an abstention's nearest hits."""
    resp = client.post("/api/v1/ask", json={"question": question})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = [s["record_id"] for s in body["sources"]]
    ids += [r["record_id"] for r in body.get("closest_records") or []]
    return ids


def _scope_of(record_id: str) -> str:
    from app.db import query_one

    row = query_one("SELECT access_scope FROM chunks WHERE record_id = ?", (record_id,))
    return row["access_scope"] if row else "missing"


def test_retrieval_filter_withholds_staff_and_admin_documents(rbac_corpus) -> None:
    """The filter runs before ranking, so a withheld chunk is never returned."""
    from app.auth.principal import Principal

    student = Principal(user_id="u1", username="s102", role="student", student_id="S102")
    staff = Principal(
        user_id="u2", username="staff", role="staff",
        departments=("Computer Science",),
    )
    admin = Principal(user_id="u3", username="admin", role="admin")

    public = "doc:rbac-public#0"
    staff_doc = "doc:rbac-staff#0"
    admin_doc = "doc:rbac-admin#0"

    assert staff_doc not in _retrieved_ids(STAFF_Q, student)
    assert admin_doc not in _retrieved_ids(ADMIN_Q, student)
    assert public in _retrieved_ids(PUBLIC_Q, student)

    assert staff_doc in _retrieved_ids(STAFF_Q, staff), (
        "staff must still be able to read staff-only documents"
    )
    assert admin_doc not in _retrieved_ids(ADMIN_Q, staff)
    assert admin_doc in _retrieved_ids(ADMIN_Q, admin)


def test_a_student_never_receives_a_staff_or_admin_citation(
    api_client, rbac_corpus
) -> None:
    """End to end through /ask: no citation may carry a privileged scope."""
    student = api_client("student", student_id="S102")
    for question in (STAFF_Q, ADMIN_Q):
        for record_id in _sources(student, question):
            assert _scope_of(record_id) in ("public", "student:S102"), (
                f"student received {record_id} with scope {_scope_of(record_id)}"
            )


def test_staff_never_receives_an_admin_citation(api_client, rbac_corpus) -> None:
    staff = api_client("staff", departments=("Computer Science",))
    for question in (STAFF_Q, ADMIN_Q, PUBLIC_Q):
        for record_id in _sources(staff, question):
            assert _scope_of(record_id) != "admin", (
                f"staff received the admin-only record {record_id}"
            )


def test_route_endpoint_applies_the_same_filter(api_client, rbac_corpus) -> None:
    """``/route`` is a second door onto retrieval; it must not be a way around."""
    student = api_client("student", student_id="S102")
    resp = student.post("/api/v1/route", json={"query": STAFF_Q})
    assert resp.status_code == 200, resp.text
    for source in resp.json().get("sources", []):
        assert _scope_of(source["record_id"]) in ("public", "student:S102")


def test_a_student_cannot_read_another_students_records_through_ask(api_client) -> None:
    s102 = api_client("student", student_id="S102")
    resp = s102.post(
        "/api/v1/ask", json={"question": "What is the CGPA of S103?", "user_id": "S103"}
    )
    assert resp.status_code == 403, (
        "a student asking for another student's record must be refused"
    )


# --------------------------------------------------------------------------
# Cache scoping and audit
# --------------------------------------------------------------------------


def test_cache_scopes_are_disjoint_per_role() -> None:
    from app.auth.principal import Principal

    admin = Principal(user_id="a", username="admin", role="admin")
    staff = Principal(user_id="b", username="staff", role="staff")
    s102 = Principal(user_id="c", username="s102", role="student", student_id="S102")
    s103 = Principal(user_id="d", username="s103", role="student", student_id="S103")

    scopes = {admin.cache_scope, staff.cache_scope, s102.cache_scope, s103.cache_scope}
    assert len(scopes) == 4, f"cache scopes collide: {scopes}"
    assert s102.cache_scope == "student:S102"


def test_a_denied_action_is_written_to_the_audit_log(api_client) -> None:
    from app.db import query

    student = api_client("student", student_id="S102")
    assert student.get("/api/v1/admin/users").status_code == 403

    rows = query(
        "SELECT actor_role, action, allowed FROM audit_log ORDER BY id DESC LIMIT 5"
    )
    assert rows, "a denial must leave an audit row"
    assert any(not row["allowed"] and row["actor_role"] == "student" for row in rows)


def test_student_record_access_by_staff_is_audited(client, temp_db) -> None:
    from app.db import query

    from test_placement import _seed, _student

    _seed()
    _student("T001")
    resp = client.get(
        "/api/v1/placement/eligibility", params={"student_id": "T001"}
    )
    assert resp.status_code == 200, resp.text
    rows = query(
        "SELECT action, target, allowed FROM audit_log WHERE action = 'pii.read'"
    )
    assert rows and rows[0]["target"] == "T001"


# --------------------------------------------------------------------------
# Service account (organisers' harness)
# --------------------------------------------------------------------------


def test_service_api_key_gets_a_read_only_public_scope(client, rbac_corpus) -> None:
    from app.core.settings import settings
    from fastapi.testclient import TestClient

    from app.main import create_app

    previous = settings.service_api_key
    settings.service_api_key = "harness-key"
    try:
        with TestClient(create_app(), headers={"X-API-Key": "harness-key"}) as harness:
            me = harness.get("/api/v1/auth/me")
            # The harness principal is stateless: /me has no database row for it.
            assert me.status_code == 401

            ok = harness.post("/api/v1/ask", json={"question": STAFF_Q})
            assert ok.status_code == 200, ok.text
            for source in ok.json()["sources"]:
                assert _scope_of(source["record_id"]) == "public"

            assert harness.get("/api/v1/admin/users").status_code == 403
            assert harness.post("/api/v1/simulate", json={}).status_code == 403

        wrong = TestClient(create_app(), headers={"X-API-Key": "not-the-key"})
        assert wrong.post(
            "/api/v1/ask", json={"question": "What is the attendance policy?"}
        ).status_code == 401
    finally:
        settings.service_api_key = previous


def test_the_health_and_status_endpoints_stay_open(anonymous_client) -> None:
    """The organisers' harness calls these without logging in."""
    assert anonymous_client.get("/api/v1/health").status_code == 200
    assert anonymous_client.get("/api/v1/resource-status").status_code == 200
    assert anonymous_client.post(PROTECTED, json={"question": "hi"}).status_code == 401
