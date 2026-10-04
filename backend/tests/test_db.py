"""The MySQL data layer: schema artifacts and the SQLite->MySQL translation.

These are fast, database-free checks that guard the pieces the rest of the suite
takes for granted.
"""

from __future__ import annotations

from pathlib import Path

from app.core.settings import settings
from app.db.connection import _adapt
from app.db.migrate import split_statements

DB_DIR = settings.project_root / "db"


def test_standalone_schema_matches_the_migration() -> None:
    """`db/schema.sql` and the app migration must not drift apart."""
    schema = (DB_DIR / "schema.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    migration = (DB_DIR / "migrations" / "001_init.sql").read_text(
        encoding="utf-8"
    ).replace("\r\n", "\n")
    assert schema == migration


def test_schema_is_mysql_not_sqlite() -> None:
    sql = (DB_DIR / "migrations" / "001_init.sql").read_text(encoding="utf-8")
    assert "PRAGMA" not in sql.upper()
    assert "AUTOINCREMENT" not in sql.upper()
    assert "sqlite_master" not in sql.lower()
    assert "ENGINE=InnoDB" in sql
    assert "utf8mb4" in sql


def test_split_statements_handles_comments_and_creates_all_tables() -> None:
    sql = (DB_DIR / "migrations" / "001_init.sql").read_text(encoding="utf-8")
    statements = split_statements(sql)
    creates = [s for s in statements if s.upper().startswith("CREATE TABLE")]
    assert len(creates) >= 18
    # No statement should retain its terminating semicolon.
    assert all(not s.rstrip().endswith(";") for s in statements)


def test_placeholder_translation() -> None:
    assert _adapt("SELECT * FROM students WHERE student_id = ?") == (
        "SELECT * FROM students WHERE student_id = %s"
    )
    # A LIKE pattern's percent signs must be escaped for PyMySQL.
    assert _adapt("SELECT * FROM chunks WHERE text LIKE ?") == (
        "SELECT * FROM chunks WHERE text LIKE %s"
    )
    assert _adapt("SELECT * FROM documents WHERE title LIKE '%policy%'") == (
        "SELECT * FROM documents WHERE title LIKE '%%policy%%'"
    )


def test_insert_or_replace_becomes_mysql_replace() -> None:
    adapted = _adapt("INSERT OR REPLACE INTO query_log (request_id) VALUES (?)")
    assert adapted == "REPLACE INTO query_log (request_id) VALUES (%s)"
