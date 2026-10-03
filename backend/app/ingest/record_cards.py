"""Turn structured rows into natural-language "record cards".

The row stays the source of truth and is queried by SQL. The card exists only so
the row can also be *retrieved* by a natural-language question and cited with a
``db:<table>:<pk>`` id. Numbers are copied verbatim from the row, never inferred.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .chunking import Chunk, chunk_record_card

ACCESS_STUDENT = "student:{student_id}"
ACCESS_STAFF = "staff"
ACCESS_PUBLIC = "public"


def student_scope(student_id: str) -> str:
    """A personal record is visible to its owner and to staff."""
    return f"student:{student_id}"


def format_date(value: Any) -> str:
    if value is None:
        return "unknown date"
    text = str(value)
    try:
        return datetime.fromisoformat(text).strftime("%d %B %Y")
    except ValueError:
        return text


def student_card(row: dict[str, Any]) -> str:
    return (
        f"Student {row['name']} ({row['student_id']}) is in {row['department']}, "
        f"year {row['year']}. CGPA: {float(row['cgpa']):.2f}. "
        f"Attendance: {float(row['attendance_pct']):.1f}%. "
        f"Live backlogs: {row['backlogs']}. "
        f"Projects completed: {row['project_count']}. "
        f"Communication score: {float(row['communication_score']):.1f} out of 5. "
        f"Record updated {format_date(row.get('updated_at'))}."
    )


def course_card(row: dict[str, Any]) -> str:
    return (
        f"Course {row['course_id']} is {row['title']}, offered by {row['department']}, "
        f"worth {row['credits']} credits in semester {row['semester']}. "
        f"Record updated {format_date(row.get('updated_at'))}."
    )


def enrollment_card(row: dict[str, Any]) -> str:
    return (
        f"Student {row['student_id']} scored {row['score']} in {row['course_id']} "
        f"(semester {row['semester']}, grade {row['grade']}). "
        f"Project grade: {row['project_grade']}. Coding challenge score: {row['coding_score']}. "
        f"Record updated {format_date(row.get('updated_at'))}."
    )


def attendance_card(row: dict[str, Any]) -> str:
    return (
        f"Student {row['student_id']} attendance in {row['course_id']}: "
        f"{float(row['percent']):.1f}% ({row['attended']} of {row['held']} sessions held), "
        f"as of {format_date(row.get('as_of'))}."
    )


def schedule_card(row: dict[str, Any]) -> str:
    return (
        f"Course {row['course_id']} meets on {row['day_of_week']} from {row['start_time']} "
        f"to {row['end_time']} in room {row['room']}, taught by {row['faculty']}."
    )


def skill_card(skill: dict[str, Any]) -> str:
    return (
        f"Skill {skill['skill_id']}: {skill['name']} ({skill['category']}). "
        f"{skill.get('description') or ''}".strip()
    )


def student_skill_card(row: dict[str, Any], skill: dict[str, Any]) -> str:
    evidence = {
        "module": "coursework",
        "project": "a project",
        "coding_test": "a coding assessment",
        "self": "self-reported",
    }.get(row["evidence_source"], row["evidence_source"])
    return (
        f"Student {row['student_id']} has {skill['name']} at level {row['level']} out of 5, "
        f"evidenced by {evidence}"
        + (f" ({row['evidence_ref']})" if row.get("evidence_ref") else "")
        + "."
    )


def company_card(row: dict[str, Any]) -> str:
    return (
        f"{row['name']} is a {row['sector']} company (tier {row['tier']}). "
        f"{row.get('description') or ''}".strip()
    )


def role_card(role: dict[str, Any], company_name: str, requirements: list[dict[str, Any]]) -> str:
    required = [r for r in requirements if r["is_required"]]
    preferred = [r for r in requirements if not r["is_required"]]
    required_txt = ", ".join(
        f"{r['skill_name']} at level {r['min_level']}" for r in required
    ) or "none"
    preferred_txt = ", ".join(
        f"{r['skill_name']} at level {r['min_level']}" for r in preferred
    ) or "none"
    depts = role.get("allowed_departments_list") or []
    return (
        f"{company_name} role {role['title']} (role_id {role['role_id']}): package "
        f"{role['package_lpa']} LPA, location {role.get('location') or 'not stated'}. "
        f"Minimum CGPA {role['min_cgpa']}, maximum backlogs {role['max_backlogs']}, "
        f"minimum attendance {role['min_attendance_pct']}%, minimum projects "
        f"{role['min_project_count']}, minimum communication score {role['min_communication']}. "
        f"Allowed departments: {', '.join(depts) if depts else 'any'}. "
        f"Required skills: {required_txt}. Preferred skills: {preferred_txt}."
    )


def build_record_cards() -> list[Chunk]:
    """Read every structured table and render one card per row.

    Cards are marked with the access scope of the row they describe, so a
    student's personal card can never be retrieved by another student.
    """
    from ..db import query

    chunks: list[Chunk] = []

    for row in query("SELECT * FROM students"):
        chunks.append(
            chunk_record_card(
                "students", row["student_id"], student_card(row),
                title=f"Student record {row['student_id']}",
                access_scope=student_scope(row["student_id"]),
                updated_at=row.get("updated_at") or "",
            )
        )

    for row in query("SELECT * FROM courses"):
        chunks.append(
            chunk_record_card(
                "courses", row["course_id"], course_card(row),
                title=f"Course {row['course_id']}",
                updated_at=row.get("updated_at") or "",
            )
        )

    # Enrollments and attendance are personal records.
    for row in query("SELECT * FROM enrollments"):
        chunks.append(
            chunk_record_card(
                "enrollments", row["id"], enrollment_card(row),
                title=f"Result {row['student_id']} {row['course_id']}",
                access_scope=student_scope(row["student_id"]),
                updated_at=row.get("updated_at") or "",
            )
        )

    for row in query("SELECT * FROM attendance"):
        chunks.append(
            chunk_record_card(
                "attendance", row["id"], attendance_card(row),
                title=f"Attendance {row['student_id']} {row['course_id']}",
                access_scope=student_scope(row["student_id"]),
                updated_at=row.get("as_of") or "",
            )
        )

    for row in query("SELECT * FROM schedules"):
        chunks.append(
            chunk_record_card(
                "schedules", row["course_id"], schedule_card(row),
                title=f"Schedule {row['course_id']}",
                updated_at=row.get("updated_at") or "",
            )
        )

    skills = {row["skill_id"]: row for row in query("SELECT * FROM skills")}
    for row in skills.values():
        chunks.append(
            chunk_record_card(
                "skills", row["skill_id"], skill_card(row),
                title=f"Skill {row['name']}",
                updated_at="",
            )
        )

    for row in query("SELECT * FROM student_skills"):
        skill = skills.get(row["skill_id"])
        if skill is None:
            continue
        chunks.append(
            chunk_record_card(
                "student_skills", row["id"], student_skill_card(row, skill),
                title=f"Skill {row['student_id']} {skill['name']}",
                access_scope=student_scope(row["student_id"]),
                updated_at=row.get("updated_at") or "",
            )
        )

    for row in query("SELECT * FROM companies"):
        chunks.append(
            chunk_record_card(
                "companies", row["company_id"], company_card(row),
                title=f"Company {row['name']}",
                updated_at=row.get("updated_at") or "",
            )
        )

    roles = query(
        """
        SELECT r.*, c.name AS company_name
        FROM company_roles r JOIN companies c ON c.company_id = r.company_id
        """
    )
    for role in roles:
        reqs = query(
            """
            SELECT rr.*, s.name AS skill_name
            FROM role_requirements rr JOIN skills s ON s.skill_id = rr.skill_id
            WHERE rr.role_id = ?
            """,
            (role["role_id"],),
        )
        import json

        try:
            role["allowed_departments_list"] = json.loads(role["allowed_departments"])
        except (TypeError, ValueError):
            role["allowed_departments_list"] = []
        chunks.append(
            chunk_record_card(
                "company_roles", role["role_id"],
                role_card(role, role["company_name"], reqs),
                title=f"Role {role['company_name']} {role['title']}",
                updated_at=role.get("updated_at") or "",
            )
        )

    return chunks
