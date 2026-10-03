"""Shared test fixtures.

The ``block_network`` fixture is autouse: it makes any attempt to open an
outbound socket fail the test. The whole point of the project is that no
endpoint calls a third-party API, so the test suite proves it.
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
def block_network(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Block outbound sockets unless a test opts out with @pytest.mark.allow_network."""
    if request.node.get_closest_marker("allow_network"):
        yield
        return

    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def guard_connect(self, address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            return real_connect(self, address, *args, **kwargs)
        raise AssertionError(f"Outbound network call attempted to {host!r}")

    def guard_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            return real_create_connection(address, *args, **kwargs)
        raise AssertionError(f"Outbound network call attempted to {host!r}")

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket, "create_connection", guard_create_connection)
    yield


@pytest.fixture()
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the app at a throwaway SQLite file and reset thread state."""
    from app.core.settings import get_settings
    from app.db import connection as db_connection

    settings = get_settings()
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db", raising=False)
    monkeypatch.setattr(db_connection.settings, "db_path", tmp_path / "test.db", raising=False)
    monkeypatch.setattr(db_connection, "_initialised", False, raising=False)
    db_connection.reset_thread_connection()
    yield tmp_path / "test.db"
    db_connection.reset_thread_connection()


@pytest.fixture()
def client(temp_db):
    """FastAPI test client backed by the throwaway database."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
