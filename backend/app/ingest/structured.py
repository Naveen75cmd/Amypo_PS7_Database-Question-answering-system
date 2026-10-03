"""Load the synthetic (or AMYPO-provided) CSV exports into SQLite.

Idempotent: every table is upserted on its natural key, so re-running changes
nothing and row counts stay stable.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..db import execute, query, query_one

# CSV filename -> (table, columns in file order, upsert key columns)
TABLES: dict[str, tuple[str, list[str], list[str]]] = {
    "students.csv": (
        "students",
        ["student_id", "name", "department", "year", "cgpa", "backlogs",
         "attendance_pct", "communication_score", "project_count", "email", "updated_at"],
        ["student_id"],
    ),
    "courses.csv": (
        "courses",
        ["course_id", "title", "department", "credits", "semester", "updated_at"],
        ["course_id"],
    ),
    "enrollments.csv": (
        "enrollments",
        ["student_id", "course_id", "semester", "score", "grade", "project_grade",
         "coding_score", "updated_at"],
        ["student_id", "course_id", "semester"],
    ),
    "grades.csv": (
        "grades",
        ["student_id", "course_id", "assessment", "score", "max_score", "weight", "recorded_at"],
        ["student_id", "course_id", "assessment"],
    ),
    "attendance.csv": (
        "attendance",
        ["student_id", "course_id", "attended", "held", "percent", "as_of"],
        ["student_id", "course_id"],
    ),
    "schedules.csv": (
        "schedules",
        ["course_id", "day_of_week", "start_time", "end_time", "room", "faculty", "updated_at"],
        ["course_id"],
    ),
    "skills.csv": (
        "skills",
        ["skill_id", "name", "category", "description"],
        ["skill_id"],
    ),
    "student_skills.csv": (
        "student_skills",
        ["student_id", "skill_id", "level", "evidence_source", "evidence_ref", "updated_at"],
        ["student_id", "skill_id"],
    ),
    "companies.csv": (
        "companies",
        ["company_id", "name", "sector", "tier", "website", "description", "updated_at"],
        ["company_id"],
    ),
    "company_roles.csv": (
        "company_roles",
        ["company_id", "title", "location", "package_lpa", "min_cgpa", "max_backlogs",
         "min_attendance_pct", "min_project_count", "min_communication",
         "allowed_departments", "weights", "updated_at"],
        ["company_id", "title"],
    ),
}


@dataclass
class StructuredResult:
    rows: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.rows.values())


def _to_number(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _upsert(table: str, columns: list[str], keys: list[str], row: dict[str, Any]) -> None:
    existing = query_one(
        f"SELECT 1 FROM {table} WHERE " + " AND ".join(f"{k} = ?" for k in keys),
        tuple(row[k] for k in keys),
    )
    if existing:
        updates = ", ".join(f"{c} = ?" for c in columns if c not in keys)
        if not updates:
            return
        execute(
            f"UPDATE {table} SET {updates} WHERE " + " AND ".join(f"{k} = ?" for k in keys),
            tuple(row[c] for c in columns if c not in keys) + tuple(row[k] for k in keys),
        )
        return
    placeholders = ", ".join("?" for _ in columns)
    execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(row[c] for c in columns),
    )


def load_structured(directory: Path) -> StructuredResult:
    """Load every known CSV in ``directory`` into its table."""
    result = StructuredResult()

    for filename, (table, columns, keys) in TABLES.items():
        path = directory / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            count = 0
            for raw in reader:
                row = {c: _to_number(raw.get(c)) for c in columns}
                try:
                    _upsert(table, columns, keys, row)
                    count += 1
                except Exception as exc:
                    result.errors.append(f"{filename}: {exc}")
        result.rows[table] = count

    # role_requirements references roles by file order; resolve them now.
    req_path = directory / "role_requirements.csv"
    if req_path.exists():
        # role_id ordering matches the generator's global role_index because
        # roles are inserted in generation order.
        role_ids = [r["role_id"] for r in query("SELECT role_id FROM company_roles ORDER BY role_id")]
        count = 0
        with req_path.open(encoding="utf-8", newline="") as fh:
            for raw in csv.DictReader(fh):
                idx = int(_to_number(raw["role_index"]))
                if not (1 <= idx <= len(role_ids)):
                    result.errors.append(f"role_requirements: bad role_index {idx}")
                    continue
                role_id = role_ids[idx - 1]
                skill_id = str(raw["skill_id"]).strip()
                existing = query_one(
                    "SELECT 1 FROM role_requirements WHERE role_id = ? AND skill_id = ?",
                    (role_id, skill_id),
                )
                values = (
                    int(_to_number(raw["min_level"])),
                    float(_to_number(raw["importance"])),
                    int(_to_number(raw["is_required"])),
                )
                if existing:
                    execute(
                        "UPDATE role_requirements SET min_level = ?, importance = ?, "
                        "is_required = ? WHERE role_id = ? AND skill_id = ?",
                        values + (role_id, skill_id),
                    )
                else:
                    execute(
                        "INSERT INTO role_requirements (role_id, skill_id, min_level, "
                        "importance, is_required) VALUES (?, ?, ?, ?, ?)",
                        (role_id, skill_id) + values,
                    )
                count += 1
        result.rows["role_requirements"] = count

    return result
