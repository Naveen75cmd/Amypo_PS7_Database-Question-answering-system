"""The structured tool path: a fixed catalogue of parameterised SQL templates.

Design rule from the build prompts: *no free-form LLM-generated SQL*. The intent
classifier and entity extractor pick a template, the template is filled with
validated parameters, and the resulting rows become citations. The model is only
ever asked to phrase the rows, never to compute them.

Every template is a literal SQL string with ``?`` placeholders. No template
accepts SQL syntax from the caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..core.schemas import Intent
from ..db import query
from ..ingest.chunking import db_record_id


@dataclass
class ToolResult:
    template: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    summary: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def has_rows(self) -> bool:
        return bool(self.rows)


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------

STUDENT_PROFILE = """
SELECT student_id, name, department, year, cgpa, backlogs, attendance_pct,
       communication_score, project_count, updated_at
FROM students WHERE student_id = ?
"""

STUDENT_ATTENDANCE = """
SELECT a.student_id, a.course_id, c.title AS course_title, a.percent,
       a.attended, a.held, a.as_of
FROM attendance a JOIN courses c ON c.course_id = a.course_id
WHERE a.student_id = ?
ORDER BY a.percent ASC
"""

STUDENT_ATTENDANCE_COURSE = """
SELECT a.student_id, a.course_id, c.title AS course_title, a.percent,
       a.attended, a.held, a.as_of
FROM attendance a JOIN courses c ON c.course_id = a.course_id
WHERE a.student_id = ? AND a.course_id = ?
"""

STUDENT_GRADES = """
SELECT e.student_id, e.course_id, c.title AS course_title, e.score, e.grade,
       e.project_grade, e.coding_score
FROM enrollments e JOIN courses c ON c.course_id = e.course_id
WHERE e.student_id = ?
ORDER BY e.score DESC
"""

STUDENT_GRADES_COURSE = """
SELECT e.student_id, e.course_id, c.title AS course_title, e.score, e.grade,
       e.project_grade, e.coding_score
FROM enrollments e JOIN courses c ON c.course_id = e.course_id
WHERE e.student_id = ? AND e.course_id = ?
"""

STUDENT_SKILLS = """
SELECT ss.student_id, ss.skill_id, s.name AS skill_name, s.category, ss.level,
       ss.evidence_source
FROM student_skills ss JOIN skills s ON s.skill_id = ss.skill_id
WHERE ss.student_id = ?
ORDER BY ss.level DESC, s.name ASC
"""

COURSE_INFO = """
SELECT course_id, title, department, credits, semester FROM courses WHERE course_id = ?
"""

COURSE_SCHEDULE = """
SELECT course_id, day_of_week, start_time, end_time, room, faculty
FROM schedules WHERE course_id = ?
"""

ROLE_INFO = """
SELECT r.role_id, r.title, c.name AS company, r.location, r.package_lpa, r.min_cgpa,
       r.max_backlogs, r.min_attendance_pct, r.min_project_count, r.min_communication,
       r.allowed_departments
FROM company_roles r JOIN companies c ON c.company_id = r.company_id
WHERE r.role_id = ?
"""

ROLE_BY_NAME = """
SELECT r.role_id, r.title, c.name AS company, r.location, r.package_lpa, r.min_cgpa,
       r.max_backlogs, r.min_attendance_pct, r.min_project_count, r.min_communication,
       r.allowed_departments
FROM company_roles r JOIN companies c ON c.company_id = r.company_id
WHERE c.name = ? AND r.title = ?
"""

ROLE_REQUIREMENTS = """
SELECT rr.role_id, rr.skill_id, s.name AS skill_name, rr.min_level, rr.importance,
       rr.is_required
FROM role_requirements rr JOIN skills s ON s.skill_id = rr.skill_id
WHERE rr.role_id = ?
ORDER BY rr.is_required DESC, rr.importance DESC
"""

COMPANY_ROLES = """
SELECT r.role_id, r.title, c.name AS company, r.package_lpa, r.min_cgpa,
       r.min_attendance_pct, r.max_backlogs
FROM company_roles r JOIN companies c ON c.company_id = r.company_id
WHERE c.name = ?
ORDER BY r.package_lpa DESC
"""

ATTENDANCE_POLICY_THRESHOLD = """
SELECT MIN(a.percent) AS lowest_attendance, COUNT(*) AS courses_tracked
FROM attendance a WHERE a.student_id = ?
"""

AGGREGATE_CGPA = """
SELECT COUNT(*) AS students, ROUND(AVG(cgpa), 2) AS average_cgpa,
       ROUND(MAX(cgpa), 2) AS highest_cgpa, ROUND(MIN(cgpa), 2) AS lowest_cgpa
FROM students
"""

AGGREGATE_ABOVE_CGPA = """
SELECT COUNT(*) AS students_above, ? AS threshold
FROM students WHERE cgpa >= ?
"""

AGGREGATE_ATTENDANCE_SHORTFALL = """
SELECT COUNT(*) AS students_below, ? AS threshold
FROM students WHERE attendance_pct < ?
"""

AGGREGATE_BY_DEPARTMENT = """
SELECT department, COUNT(*) AS students, ROUND(AVG(cgpa), 2) AS average_cgpa
FROM students GROUP BY department ORDER BY average_cgpa DESC
"""

# intent -> ordered list of (template name, sql)
CATALOGUE: dict[str, dict[str, str]] = {
    "student_profile": {"sql": STUDENT_PROFILE},
    "student_attendance": {"sql": STUDENT_ATTENDANCE},
    "student_attendance_course": {"sql": STUDENT_ATTENDANCE_COURSE},
    "student_grades": {"sql": STUDENT_GRADES},
    "student_grades_course": {"sql": STUDENT_GRADES_COURSE},
    "student_skills": {"sql": STUDENT_SKILLS},
    "course_info": {"sql": COURSE_INFO},
    "course_schedule": {"sql": COURSE_SCHEDULE},
    "role_info": {"sql": ROLE_INFO},
    "role_by_name": {"sql": ROLE_BY_NAME},
    "role_requirements": {"sql": ROLE_REQUIREMENTS},
    "company_roles": {"sql": COMPANY_ROLES},
    "attendance_floor": {"sql": ATTENDANCE_POLICY_THRESHOLD},
    "aggregate_cgpa": {"sql": AGGREGATE_CGPA},
    "aggregate_above_cgpa": {"sql": AGGREGATE_ABOVE_CGPA},
    "aggregate_attendance_shortfall": {"sql": AGGREGATE_ATTENDANCE_SHORTFALL},
    "aggregate_by_department": {"sql": AGGREGATE_BY_DEPARTMENT},
}

# A template that takes no parameters is safe to run for an aggregate question.
PARAMLESS = {"aggregate_cgpa", "aggregate_by_department"}


def run_template(name: str, params: tuple[Any, ...] = ()) -> ToolResult:
    """Execute one catalogued template. Unknown names are refused, not guessed."""
    entry = CATALOGUE.get(name)
    if entry is None:
        return ToolResult(template=name, error=f"unknown template: {name}")
    try:
        rows = query(entry["sql"], params)
    except Exception as exc:
        return ToolResult(template=name, error=f"template {name} failed: {exc}")

    record_ids = _record_ids_for(name, rows)
    return ToolResult(
        template=name,
        rows=rows,
        record_ids=record_ids,
        summary=_summarize(name, rows),
    )


def _record_ids_for(name: str, rows: list[dict[str, Any]]) -> list[str]:
    """Map result rows onto citable record ids (``db:<table>:<pk>``)."""
    ids: list[str] = []
    for row in rows:
        if name.startswith("student_") or name in ("attendance_floor",):
            sid = row.get("student_id")
            if sid:
                ids.append(db_record_id("students", sid))
        elif name.startswith("course_") or name == "course_schedule":
            cid = row.get("course_id")
            if cid:
                ids.append(db_record_id("courses", cid))
        elif name in ("role_info", "role_by_name", "role_requirements", "company_roles"):
            rid = row.get("role_id")
            if rid:
                ids.append(db_record_id("company_roles", rid))
        elif name == "aggregate_by_department":
            continue  # derived aggregate: no single row to cite
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for rid in ids:
        if rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out


def _summarize(name: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "no matching rows"
    if name == "aggregate_cgpa":
        row = rows[0]
        return (
            f"{row['students']} students; average CGPA {row['average_cgpa']}, "
            f"highest {row['highest_cgpa']}, lowest {row['lowest_cgpa']}"
        )
    if name == "aggregate_by_department":
        return "; ".join(
            f"{r['department']}: {r['students']} students, avg CGPA {r['average_cgpa']}"
            for r in rows[:6]
        )
    if len(rows) == 1:
        return ", ".join(f"{k}: {v}" for k, v in rows[0].items())
    return f"{len(rows)} rows"


# --------------------------------------------------------------------------
# Intent -> template selection
# --------------------------------------------------------------------------


def select_templates(
    intent: Intent, entities: dict[str, Any], question: str
) -> list[tuple[str, tuple[Any, ...]]]:
    """Choose templates for an intent. Returns (name, params) pairs.

    This is the *only* place that decides which SQL runs, so the set of
    reachable queries is auditable at a glance.
    """
    student_id = entities.get("student_id")
    course_id = entities.get("course_id")
    company = entities.get("company")
    role = entities.get("role")
    lowered = question.lower()

    selected: list[tuple[str, tuple[Any, ...]]] = []

    if intent == Intent.personal_record:
        if student_id and course_id:
            # A named course scopes the query. Running the broad templates here
            # was a real bug: asking for attendance in CS301 returned another
            # course's grades, because ``student_grades`` ignores the course.
            # Only course-scoped templates may run when a course is named.
            wants_grades = any(k in lowered for k in ("grade", "score", "marks"))
            wants_attendance = "attendance" in lowered
            if wants_grades and not wants_attendance:
                selected.append(("student_grades_course", (student_id, course_id)))
            elif wants_attendance and not wants_grades:
                selected.append(("student_attendance_course", (student_id, course_id)))
            else:
                selected.append(("student_attendance_course", (student_id, course_id)))
                selected.append(("student_grades_course", (student_id, course_id)))
        elif student_id:
            if "cgpa" in lowered or "profile" in lowered or "backlog" in lowered:
                selected.append(("student_profile", (student_id,)))
            elif "attendance" in lowered:
                # No course named: "attendance percentage" means the overall
                # figure on the student's profile, not their weakest course.
                selected.append(("student_profile", (student_id,)))
            elif "grade" in lowered or "score" in lowered or "marks" in lowered:
                selected.append(("student_grades", (student_id,)))
            elif "skill" in lowered:
                selected.append(("student_skills", (student_id,)))
            else:
                # Broad personal question: give the profile plus the weakest course.
                selected.append(("student_profile", (student_id,)))
                selected.append(("student_attendance", (student_id,)))
        elif course_id:
            selected.append(("course_info", (course_id,)))
            selected.append(("course_schedule", (course_id,)))

    elif intent == Intent.placement_eligibility:
        if role and company:
            selected.append(("role_by_name", (company, role)))
        elif company:
            selected.append(("company_roles", (company,)))
        elif course_id:
            selected.append(("course_info", (course_id,)))
        if student_id:
            selected.append(("student_profile", (student_id,)))

    elif intent == Intent.aggregate_stat:
        if "department" in lowered:
            selected.append(("aggregate_by_department", ()))
        elif "cgpa" in lowered or "gpa" in lowered:
            numbers = [n for n in _numbers(question)]
            if numbers:
                selected.append(("aggregate_above_cgpa", (float(numbers[0]), float(numbers[0]))))
            else:
                selected.append(("aggregate_cgpa", ()))
        elif "attendance" in lowered:
            numbers = [n for n in _numbers(question)]
            threshold = float(numbers[0]) if numbers else 75.0
            selected.append(("aggregate_attendance_shortfall", (threshold, threshold)))
        # Deliberately no fallback template. "How many buses does the college
        # operate?" is an aggregate question with no supported metric, and the
        # old fallback answered it with the campus-wide CGPA average — a
        # confident, irrelevant number. With no metric named, nothing is run and
        # the pipeline abstains instead.

    elif intent == Intent.skill_gap:
        if student_id:
            selected.append(("student_skills", (student_id,)))
            selected.append(("student_profile", (student_id,)))
        if role and company:
            selected.append(("role_by_name", (company, role)))

    elif intent == Intent.candidate_recommendation:
        if company:
            selected.append(("company_roles", (company,)))
        if role and company:
            selected.append(("role_by_name", (company, role)))
            selected.append(("role_requirements", ()))

    elif intent == Intent.policy_lookup:
        if course_id:
            selected.append(("course_info", (course_id,)))
            selected.append(("course_schedule", (course_id,)))

    # Resolve a role_by_name lookup into its requirements, which needs the id.
    resolved: list[tuple[str, tuple[Any, ...]]] = []
    for name, params in selected:
        if name == "role_requirements":
            continue  # handled after role_by_name resolves
        resolved.append((name, params))

    return resolved


def _numbers(text: str) -> list[str]:
    import re

    return re.findall(r"\d+(?:\.\d+)?", text)


def run_for_intent(
    intent: Intent, entities: dict[str, Any], question: str
) -> list[ToolResult]:
    """Run every template selected for this intent, plus derived follow-ups."""
    results: list[ToolResult] = []
    for name, params in select_templates(intent, entities, question):
        result = run_template(name, params)
        results.append(result)
        # A resolved role needs a second query for its requirements.
        if name == "role_by_name" and result.rows:
            role_id = result.rows[0]["role_id"]
            results.append(run_template("role_requirements", (role_id,)))
    return results


# Fields that are identifiers or bookkeeping rather than answer content.
_NOISE_FIELDS = frozenset(
    {"student_id", "role_id", "course_id", "skill_id", "id", "updated_at",
     "as_of", "recorded_at", "embedding", "company_id"}
)

# Human-readable labels for the fields a student actually asks about.
_FIELD_LABELS = {
    "cgpa": "CGPA",
    "attendance_pct": "overall attendance",
    "backlogs": "live backlogs",
    "communication_score": "communication score",
    "project_count": "projects completed",
    "name": "name",
    "department": "department",
    "year": "year",
    "percent": "attendance",
    "course_title": "course",
    "score": "score",
    "grade": "grade",
    "project_grade": "project grade",
    "coding_score": "coding challenge score",
    "level": "level",
    "skill_name": "skill",
    "title": "title",
    "company": "company",
    "package_lpa": "package (LPA)",
    "min_cgpa": "minimum CGPA",
    "max_backlogs": "maximum backlogs",
    "min_attendance_pct": "minimum attendance (%)",
    "min_project_count": "minimum projects",
    "min_communication": "minimum communication score",
    "students": "students",
    "average_cgpa": "average CGPA",
    "highest_cgpa": "highest CGPA",
    "lowest_cgpa": "lowest CGPA",
    "students_above": "students above the threshold",
    "students_below": "students below the threshold",
    "threshold": "threshold",
    "faculty": "faculty",
    "room": "room",
    "day_of_week": "day",
    "credits": "credits",
    "semester": "semester",
}


def describe_no_record(
    intent: Intent, entities: dict[str, Any], tool_results: list[ToolResult]
) -> str:
    """State plainly that a named record does not exist.

    Only fires when the question named a concrete entity and the templates for
    it returned nothing. Without this the pipeline falls through to retrieval,
    which is how a course-scoped question could end up answered with another
    course's data. The message contains the canonical abstention sentence, so
    the verifier treats it as an honest abstention rather than a claim.
    """
    if any(r.ok and r.has_rows for r in tool_results):
        return ""
    student_id = entities.get("student_id")
    course_id = entities.get("course_id")
    company = entities.get("company")
    role = entities.get("role")

    if intent == Intent.personal_record and student_id and course_id:
        return (
            "I could not find this in AMYPO's records. "
            f"Student {student_id} has no attendance or grade record for course "
            f"{course_id}; they may not be enrolled in it."
        )
    if intent == Intent.personal_record and student_id and not course_id:
        return (
            "I could not find this in AMYPO's records. "
            f"There is no personal record stored for student {student_id}."
        )
    if intent == Intent.placement_eligibility and role and company:
        return (
            "I could not find this in AMYPO's records. "
            f"No role matching \"{role}\" at {company} is on record."
        )
    if intent == Intent.placement_eligibility and company:
        return (
            "I could not find this in AMYPO's records. "
            f"No roles at {company} are on record."
        )
    # Only intents that actually looked up a specific course may claim the
    # course does not exist. An aggregate question that merely mentions a course
    # ("How many modules does CS304 have?") has no template, not a missing row,
    # and belongs to the retrieval path.
    if course_id and intent in (Intent.personal_record, Intent.policy_lookup):
        return (
            "I could not find this in AMYPO's records. "
            f"No record for course {course_id} exists."
        )
    return ""


def render_tool_answer(question: str, tool_results: list[ToolResult]) -> str:
    """Render SQL rows as a deterministic, citable sentence.

    Used for structured intents instead of the LLM. The build prompts call this
    out explicitly as the cheapest local path ("skip LLM generation if a
    template answer suffices"), and it has a second, larger benefit: the answer
    is composed *from the rows*, so every number is guaranteed to be one the
    verifier can find in its evidence. A 3.8B model phrasing the same rows is
    slower and, measured on the benchmark, less reliable.

    Returns an empty string when there is nothing to render, so the caller can
    fall back to the language model.
    """
    from ..retrieval.tokenize import tokenize_query

    question_terms = set(tokenize_query(question))
    lines: list[str] = []

    for result in tool_results:
        if not result.ok or not result.has_rows:
            continue
        row = result.rows[0]
        record_id = result.record_ids[0] if result.record_ids else None
        marker = f" [S{len(lines) + 1}]" if record_id else ""

        # Prefer fields the question actually asked about; fall back to every
        # informative field so a broad question still gets a complete answer.
        interesting = [
            (field, value)
            for field, value in row.items()
            if field not in _NOISE_FIELDS and value is not None and value != ""
        ]
        if not interesting:
            continue

        def relevance(item: tuple[str, object]) -> tuple[int, int]:
            field = item[0]
            label = _FIELD_LABELS.get(field, field.replace("_", " ")).lower()
            label_terms = set(tokenize_query(label))
            return (1 if label_terms & question_terms else 0, len(label_terms & question_terms))

        ranked = sorted(interesting, key=relevance, reverse=True)
        asked = [item for item in ranked if relevance(item)[0] > 0]
        chosen = asked if asked else ranked

        # A single-field question reads best as a bare fact; otherwise list the
        # few most relevant fields so the sentence stays short.
        if len(asked) == 1:
            field, value = asked[0]
            label = _FIELD_LABELS.get(field, field.replace("_", " "))
            parts = [f"{label}: {value}"]
        else:
            parts = [
                f"{_FIELD_LABELS.get(f, f.replace('_', ' '))}: {v}"
                for f, v in chosen[:4]
            ]
        lines.append("; ".join(parts) + marker)

    return " ".join(lines).strip()


def rows_to_context(result: ToolResult) -> str:
    """Render rows as text for the phrasing prompt."""
    if not result.rows:
        return ""
    lines: list[str] = []
    for index, row in enumerate(result.rows[:20], start=1):
        fields = ", ".join(f"{k}={v}" for k, v in row.items() if v is not None)
        lines.append(f"[S{index}] {fields}")
    return "\n".join(lines)


def role_requirements_summary(role_id: int) -> str:
    """Human-readable requirement list, used by the placement engine too."""
    result = run_template("role_requirements", (role_id,))
    if not result.ok:
        return ""
    parts: list[str] = []
    for row in result.rows:
        kind = "required" if row["is_required"] else "preferred"
        parts.append(f"{row['skill_name']} level {row['min_level']} ({kind})")
    return ", ".join(parts)


def decode_departments(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        value = json.loads(raw)
        return [str(x) for x in value] if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []
