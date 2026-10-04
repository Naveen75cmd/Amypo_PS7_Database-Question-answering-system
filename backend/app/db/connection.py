"""MySQL connection management via SQLAlchemy + PyMySQL.

A single process-wide engine owns a small connection pool (see
``settings.mysql_pool_size``); every helper borrows a pooled connection for the
duration of one statement. That keeps the connection count tiny, which matters
because MySQL is capped at ~400-500 MB inside the 8 GB budget.

The rest of the codebase writes ordinary SQL with ``?`` placeholders, exactly as
it did against SQLite. ``_adapt`` translates that dialect at the boundary:
``?`` -> ``%s`` (PyMySQL's paramstyle), literal ``%`` -> ``%%``, and the SQLite
``INSERT OR REPLACE`` -> MySQL ``REPLACE``. Keeping the translation in one place
means the ~100 SQL call sites stay database-agnostic and readable.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ..core.settings import settings

log = logging.getLogger(__name__)

_engine_lock = threading.Lock()
_engine: Engine | None = None
_init_lock = threading.Lock()
_initialised = False

_INSERT_OR_REPLACE_RE = re.compile(r"INSERT\s+OR\s+REPLACE", re.IGNORECASE)


def _adapt(sql: str) -> str:
    """Translate SQLite-flavoured SQL to MySQL, including placeholders.

    ``%`` is escaped *before* ``?`` is converted, so a LIKE pattern like
    ``'%foo%'`` becomes ``'%%foo%%'`` (correct for PyMySQL) while each ``?``
    becomes ``%s``.
    """
    adapted = _INSERT_OR_REPLACE_RE.sub("REPLACE", sql, count=1)
    return adapted.replace("%", "%%").replace("?", "%s")


def get_engine() -> Engine:
    """The process-wide engine, built lazily."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = create_engine(
                    settings.mysql_url,
                    pool_size=settings.mysql_pool_size,
                    max_overflow=settings.mysql_max_overflow,
                    pool_pre_ping=True,
                    pool_recycle=settings.mysql_pool_recycle_s,
                    future=True,
                )
    return _engine


def connect() -> Engine:
    """Return the shared engine."""
    return get_engine()


def _ensure_migrated() -> None:
    global _initialised
    if _initialised:
        return
    with _init_lock:
        if not _initialised:
            from .migrate import apply_migrations

            apply_migrations(get_engine())
            _initialised = True


def get_connection() -> Engine:
    """The engine, with the schema guaranteed to exist."""
    engine = get_engine()
    _ensure_migrated()
    return engine


def init_db() -> Engine:
    """Apply migrations against the configured database."""
    from .migrate import apply_migrations

    engine = get_engine()
    apply_migrations(engine)
    return engine


def query(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        result = conn.exec_driver_sql(_adapt(sql), tuple(params) if not isinstance(params, dict) else params)
        return [dict(row) for row in result.mappings().all()]


def query_one(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
    """Run a write statement in its own transaction. Returns the last row id."""
    with get_engine().begin() as conn:
        result = conn.exec_driver_sql(
            _adapt(sql), tuple(params) if not isinstance(params, dict) else params
        )
        return int(result.lastrowid or 0)


def executemany(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    rows = [tuple(row) for row in seq]
    if not rows:
        return
    with get_engine().begin() as conn:
        conn.exec_driver_sql(_adapt(sql), rows)


def reset() -> None:
    """Drop the cached engine and migration flag (used by tests).

    Disposing the engine also closes pooled connections, so a test that points
    ``settings`` at a different schema gets a fresh pool.
    """
    global _engine, _initialised
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
    _initialised = False


def reset_thread_connection() -> None:
    """Compatibility alias for the SQLite-era test hook."""
    reset()
