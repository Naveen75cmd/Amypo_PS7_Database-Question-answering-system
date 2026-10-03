"""Apply the plain-SQL migration files in filename order."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    """Run every ``*.sql`` file that has not been applied yet.

    Idempotency comes from the schema_migrations bookkeeping table *and* from
    the statements themselves using ``CREATE TABLE IF NOT EXISTS``.
    """
    directory = migrations_dir or MIGRATIONS_DIR
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name       TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()

    applied: set[str] = {
        row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()
    }
    ran: list[str] = []

    for path in sorted(directory.glob("*.sql")):
        if path.name in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations(name, applied_at) VALUES (?, datetime('now'))",
            (path.name,),
        )
        conn.commit()
        ran.append(path.name)
        log.info("applied migration %s", path.name)

    return ran
