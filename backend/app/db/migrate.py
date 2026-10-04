"""Apply the plain-SQL migration files in filename order (MySQL).

Migrations live in ``/db/migrations`` so the same files seed the MySQL container
(via ``/docker-entrypoint-initdb.d``) and the application can apply them itself
against any server. Idempotency comes from the ``schema_migrations`` bookkeeping
table *and* from the statements themselves using ``CREATE TABLE IF NOT EXISTS``.

MySQL's driver executes one statement per call, so a small splitter breaks each
file into statements. It understands ``--`` comments and quoted strings, which is
everything these migrations use (no stored procedures or triggers).
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.engine import Engine

from ..core.settings import settings

log = logging.getLogger(__name__)


def migrations_dir() -> Path:
    return settings.db_migrations_dir


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements.

    Handles ``--`` line comments, ``#`` comments, quoted strings and backtick
    identifiers, so a semicolon inside a string or comment never splits wrongly.
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    length = len(sql)
    quote: str | None = None
    while i < length:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < length else ""
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            current.append(ch)
            i += 1
            continue
        if ch == "-" and nxt == "-":
            while i < length and sql[i] != "\n":
                i += 1
            continue
        if ch == "#":
            while i < length and sql[i] != "\n":
                i += 1
            continue
        if ch == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def apply_migrations(engine: Engine, directory: Path | None = None) -> list[str]:
    """Run every ``*.sql`` file that has not been applied yet."""
    target = directory or migrations_dir()
    ran: list[str] = []

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name       VARCHAR(191) NOT NULL PRIMARY KEY,
                applied_at VARCHAR(40)  NOT NULL
            )
            """
        )
        applied = {
            row[0] for row in conn.exec_driver_sql("SELECT name FROM schema_migrations").fetchall()
        }

        for path in sorted(target.glob("*.sql")):
            if path.name in applied:
                continue
            for statement in split_statements(path.read_text(encoding="utf-8")):
                conn.exec_driver_sql(statement)
            conn.exec_driver_sql(
                "REPLACE INTO schema_migrations (name, applied_at) VALUES (%s, NOW())",
                (path.name,),
            )
            ran.append(path.name)
            log.info("applied migration %s", path.name)

    return ran
