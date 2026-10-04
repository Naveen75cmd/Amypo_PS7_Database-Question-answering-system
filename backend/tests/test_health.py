"""Phase 1 definition of done: the app boots and /health returns 200."""

from __future__ import annotations


def test_health_returns_200_with_components(client) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in {"ok", "degraded"}
    assert set(body["components"]) == {"db", "index", "llm", "router"}
    assert body["components"]["db"]["status"] == "ok"
    assert body["components"]["index"]["status"] in {"ok", "degraded", "not_loaded"}
    assert body["version"]


def test_request_id_header_is_returned(client) -> None:
    resp = client.get("/api/v1/health")
    assert resp.headers.get("x-request-id")
    assert resp.headers.get("x-latency-ms")


def test_inbound_request_id_is_honoured(client) -> None:
    resp = client.get("/api/v1/health", headers={"x-request-id": "trace-me-123"})
    assert resp.headers["x-request-id"] == "trace-me-123"


def test_migrations_create_every_table(temp_db) -> None:
    from app.core.settings import settings
    from app.db import init_db, query

    init_db()
    names = {
        row["name"]
        for row in query(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = ?",
            (settings.mysql_database,),
        )
    }
    expected = {
        "students", "courses", "enrollments", "grades", "attendance", "schedules",
        "skills", "student_skills", "companies", "company_roles", "role_requirements",
        "documents", "chunks", "query_log", "cache_entries", "router_decisions",
        "resource_samples", "eval_runs", "schema_migrations",
    }
    assert expected <= names, f"missing tables: {sorted(expected - names)}"


def test_migrations_are_idempotent(temp_db) -> None:
    from app.db import get_engine, init_db
    from app.db.migrate import apply_migrations

    init_db()
    assert apply_migrations(get_engine()) == []
