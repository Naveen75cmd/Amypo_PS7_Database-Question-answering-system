"""SQLite connection management.

One connection per thread (SQLite objects are not shareable across threads),
WAL mode for concurrent readers while the API writes traces.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from ..core.settings import settings

_local = threading.local()
_init_lock = threading.Lock()
_initialised = False


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
    _configure(conn)
    return conn


def get_connection() -> sqlite3.Connection:
    """Thread-local connection, migrated on first use in this process."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    global _initialised
    if not _initialised:
        with _init_lock:
            if not _initialised:
                from .migrate import apply_migrations

                apply_migrations(conn)
                _initialised = True
    return conn


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create/migrate a database at ``db_path`` (defaults to settings)."""
    conn = connect(db_path)
    from .migrate import apply_migrations

    apply_migrations(conn)
    return conn


def query(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


def query_one(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
    """Run a write statement and commit. Returns lastrowid."""
    conn = get_connection()
    cur = conn.execute(sql, params)
    conn.commit()
    return int(cur.lastrowid or 0)


def executemany(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    conn = get_connection()
    conn.executemany(sql, list(seq))
    conn.commit()


def reset_thread_connection() -> None:
    """Drop this thread's cached connection (used by tests)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
