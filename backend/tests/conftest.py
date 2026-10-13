"""Shared test fixtures.

Two things are essential here:

* ``block_network`` (autouse) makes any non-loopback outbound socket fail, so the
  suite proves the "no external API" constraint. MySQL is loopback, so it is
  allowed through.
* ``temp_db`` points the app at a throwaway MySQL schema (``amypo_test``) and
  wipes it per test, so DB-writing tests never disturb the seeded ``amypo``
  database that the retrieval and grounding tests read from.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def exact_vocab(monkeypatch: pytest.MonkeyPatch):
    """Disable the entity-vocab TTL so an INSERT is visible to the next call.

    Production caches the course/student/company vocab for
    settings.intent_vocab_ttl_s seconds; a test that inserts a student and then
    asks about it must not lose the race to that cache.
    """
    from app.core.settings import settings
    from app.retrieval import intent

    monkeypatch.setattr(settings, "intent_vocab_ttl_s", 0.0, raising=False)
    intent.invalidate_vocab_cache()
    yield
    intent.invalidate_vocab_cache()


@pytest.fixture(autouse=True)
def deterministic_llm(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Keep the suite off the local Ollama unless a test asks for the real model.

    Whether ``ollama serve`` happens to be running on the machine must not change
    what the suite measures: by default generation uses the deterministic
    extractive stub — the same offline path the demo falls back to — so results
    are reproducible and the suite stays fast. A test that genuinely needs a
    pulled model opts in with ``@pytest.mark.real_model``.
    """
    if request.node.get_closest_marker("real_model"):
        yield
        return

    from app.core.settings import settings

    monkeypatch.setattr(settings, "stub_llm", True, raising=False)
    yield


@pytest.fixture(autouse=True)
def no_cache_prewarm(monkeypatch: pytest.MonkeyPatch):
    """Ingest must not answer 25 historical questions during the suite.

    Pre-warming is exercised deliberately by its own tests; everywhere else it
    is off so an ingest test stays an ingest test.
    """
    from app.core.settings import settings

    monkeypatch.setattr(settings, "cache_prewarm_n", 0, raising=False)
    yield


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Block outbound sockets unless a test opts out with @pytest.mark.allow_network."""
    if request.node.get_closest_marker("allow_network"):
        yield
        return

    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def guard_connect(self, address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "mysql"):
            return real_connect(self, address, *args, **kwargs)
        raise AssertionError(f"Outbound network call attempted to {host!r}")

    def guard_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "mysql"):
            return real_create_connection(address, *args, **kwargs)
        raise AssertionError(f"Outbound network call attempted to {host!r}")

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket, "create_connection", guard_create_connection)
    yield


def _bootstrap_test_database() -> None:
    """Create the throwaway schema and grant the app user access to it.

    The MySQL entrypoint only grants ``amypo`` on the ``amypo`` schema, so a
    ``amypo_test`` schema needs an explicit CREATE + GRANT. Root credentials come
    from settings (the compose defaults).
    """
    import pymysql

    from app.core.settings import settings

    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user="root",
        password=settings.mysql_root_password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_test_database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute(
                f"GRANT ALL PRIVILEGES ON `{settings.mysql_test_database}`.* "
                f"TO '{settings.mysql_user}'@'%'"
            )
            cur.execute("FLUSH PRIVILEGES")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="session", autouse=True)
def mysql_test_schema():
    _bootstrap_test_database()
    yield


def _drop_all_tables() -> None:
    from app.core.settings import settings
    from app.db import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        rows = conn.exec_driver_sql(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (settings.mysql_database,),
        ).fetchall()
        for (name,) in rows:
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS `{name}`")
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")


@pytest.fixture()
def temp_db(monkeypatch: pytest.MonkeyPatch):
    """Point the app at a wiped ``amypo_test`` schema for one test."""
    from app import db as db_pkg
    from app.core.settings import settings

    monkeypatch.setattr(
        settings, "mysql_database", settings.mysql_test_database, raising=False
    )
    db_pkg.reset()
    _drop_all_tables()
    db_pkg.init_db()
    yield settings.mysql_test_database
    db_pkg.reset()


@pytest.fixture()
def client(temp_db):
    """FastAPI test client backed by the throwaway database."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
