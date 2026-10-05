"""The placement engine: deterministic eligibility, ranking, gaps and what-if.

Eligibility is decided by :mod:`app.placement.rules`; ranking by
:mod:`app.placement.suitability`; gaps by :mod:`app.placement.gaps`. This module
only wires them to the database and assembles the response schemas. No model is
involved here — the LLM, when the question arrives through ``/ask``, is only ever
asked to phrase these results.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..core.schemas import (
    EligibilityResult,
    MatchResponse,
    Source,
    SkillGapResponse,
    WhatIfRequest,
    WhatIfResponse,
)
from ..db import execute, query, query_one
from ..ingest.chunking import db_record_id
from . import gaps as gaps_module
from . import rules
from .fairness import assert_no_protected_attributes
from .suitability import DEFAULT_WEIGHTS, load_weights, score_student

log = logging.getLogger(__name__)

_ROLE_SELECT = """
SELECT r.role_id, r.title, c.name AS company, r.location, r.package_lpa, r.min_cgpa,
       r.max_backlogs, r.min_attendance_pct, r.min_project_count, r.min_communication,
       r.allowed_departments, r.weights
FROM company_roles r JOIN companies c ON c.company_id = r.company_id
"""

_STUDENT_SELECT = """
SELECT student_id, name, department, year, cgpa, backlogs, attendance_pct,
       communication_score, project_count
FROM students
"""

_REQUIREMENTS_SELECT = """
SELECT rr.role_id, rr.skill_id, s.name AS skill_name, s.category, rr.min_level,
       rr.importance, rr.is_required
FROM role_requirements rr JOIN skills s ON s.skill_id = rr.skill_id
WHERE rr.role_id = ?
ORDER BY rr.is_required DESC, rr.importance DESC
"""

# Feature names the suitability scorer may use. Checked against the protected
# list once at import so a protected feature can never be added silently.
SUITABILITY_FEATURES = tuple(DEFAULT_WEIGHTS)
assert_no_protected_attributes(SUITABILITY_FEATURES)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _student_snippet(student: dict[str, Any]) -> str:
    parts = [
        f"name: {student.get('name')}",
        f"cgpa: {student.get('cgpa')}",
        f"backlogs: {student.get('backlogs')}",
        f"attendance: {student.get('attendance_pct')}%",
        f"department: {student.get('department')}",
        f"projects: {student.get('project_count')}",
        f"communication: {student.get('communication_score')}",
    ]
    return ", ".join(p for p in parts if not p.endswith(": None"))


def _role_snippet(role: dict[str, Any]) -> str:
    return (
        f"{role.get('company')} {role.get('title')}: min CGPA {role.get('min_cgpa')}, "
        f"max backlogs {role.get('max_backlogs')}, min attendance {role.get('min_attendance_pct')}%, "
        f"min projects {role.get('min_project_count')}, min communication {role.get('min_communication')}"
    )


class PlacementEngine:
    def __init__(self, index=None) -> None:
        self.index = index

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def roles(self, company: str | None = None, department: str | None = None) -> list[dict[str, Any]]:
        sql = _ROLE_SELECT
        params: list[Any] = []
        if company:
            sql += " WHERE c.name = ?"
            params.append(company)
        sql += " ORDER BY r.package_lpa DESC, r.title ASC"
        rows = query(sql, tuple(params))
        if department:
            rows = [
                r for r in rows
                if department in _as_list(r.get("allowed_departments"))
            ]
        return rows

    def resolve_role(
        self, company: str | None = None, role: str | None = None, role_id: int | None = None
    ) -> dict[str, Any] | None:
        if role_id is not None:
            rows = query(f"{_ROLE_SELECT} WHERE r.role_id = ?", (int(role_id),))
            return rows[0] if rows else None
        sql = _ROLE_SELECT
        params: list[Any] = []
        clauses: list[str] = []
        if company:
            clauses.append("c.name = ?")
            params.append(company)
        if role:
            clauses.append("r.title = ?")
            params.append(role)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY r.package_lpa DESC LIMIT 1"
        rows = query(sql, tuple(params))
        return rows[0] if rows else None

    def _student(self, student_id: str) -> dict[str, Any] | None:
        rows = query(f"{_STUDENT_SELECT} WHERE student_id = ?", (student_id,))
        return rows[0] if rows else None

    def _students(self, department: str | None = None) -> list[dict[str, Any]]:
        if department:
            return query(f"{_STUDENT_SELECT} WHERE department = ?", (department,))
        return query(_STUDENT_SELECT)

    def _requirements(self, role_id: int) -> list[dict[str, Any]]:
        return query(_REQUIREMENTS_SELECT, (int(role_id),))

    def _skill_levels(self, student_id: str) -> dict[str, int]:
        rows = query(
            "SELECT skill_id, level FROM student_skills WHERE student_id = ?",
            (student_id,),
        )
        return {row["skill_id"]: int(row["level"]) for row in rows}

    def _enrollments(self, student_id: str) -> list[dict[str, Any]]:
        return query(
            "SELECT semester, score, project_grade, coding_score FROM enrollments "
            "WHERE student_id = ?",
            (student_id,),
        )

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------

    def _one_result(
        self,
        student: dict[str, Any],
        role: dict[str, Any],
        *,
        overrides: dict[str, Any] | None = None,
        skill_levels: dict[str, int] | None = None,
        requirements: list[dict[str, Any]] | None = None,
    ) -> EligibilityResult:
        requirements = (
            requirements
            if requirements is not None
            else self._requirements(role["role_id"])
        )
        levels = skill_levels if skill_levels is not None else self._skill_levels(
            student["student_id"]
        )
        eligible, criteria, failing = rules.evaluate(
            student, role, requirements, levels, overrides or {}
        )

        suitability = None
        factors: list[dict[str, Any]] = []
        if eligible:
            enrollments = self._enrollments(student["student_id"])
            suitability, factors = score_student(
                student, role, requirements, levels, enrollments
            )

        sources = [
            Source(
                record_id=db_record_id("students", student["student_id"]),
                snippet=_student_snippet(student)[:240],
            ),
            Source(
                record_id=db_record_id("company_roles", role["role_id"]),
                snippet=_role_snippet(role)[:240],
            ),
        ]
        return EligibilityResult(
            student_id=student["student_id"],
            student_name=student["name"],
            company=role["company"],
            role=role["title"],
            role_id=int(role["role_id"]),
            eligible=eligible,
            criteria=criteria,
            failing=failing,
            suitability=suitability,
            factors=factors,
            sources=sources,
        )

    def eligibility(
        self,
        student_id: str | None = None,
        company: str | None = None,
        role: str | None = None,
        role_id: int | None = None,
        department: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> list[EligibilityResult]:
        """Evaluate a student against a role, or a role's cohort against it.

        With a ``student_id`` and no role named, the student is checked against
        every on-record role so the caller can see everything they qualify for.
        """
        if student_id:
            student = self._student(student_id)
            if student is None:
                return []
            skill_levels = self._skill_levels(student_id)
            if overrides and "skill_levels" in overrides:
                skill_levels = {**skill_levels, **overrides["skill_levels"]}
            if role or role_id or company:
                resolved = self.resolve_role(company, role, role_id)
                if resolved is None:
                    return []
                target_roles = [resolved]
            else:
                target_roles = self.roles(department=department)
            return [
                self._one_result(student, r, overrides=overrides, skill_levels=skill_levels)
                for r in target_roles
            ]

        # Cohort: no student named, so a role must be.
        resolved = self.resolve_role(company, role, role_id)
        if resolved is None:
            return []
        requirements = self._requirements(resolved["role_id"])
        return [
            self._one_result(s, resolved, requirements=requirements)
            for s in self._students(department)
        ]

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match(
        self,
        role_id: int | None = None,
        company: str | None = None,
        role: str | None = None,
        top_n: int = 5,
        department: str | None = None,
    ) -> MatchResponse | None:
        resolved = self.resolve_role(company, role, role_id)
        if resolved is None:
            return None

        top_n = max(1, min(int(top_n), 50))
        # One role, many students: fetch the requirements once, not per student.
        requirements = self._requirements(resolved["role_id"])
        results = [
            self._one_result(s, resolved, requirements=requirements)
            for s in self._students(department)
        ]
        eligible = sorted(
            (r for r in results if r.eligible),
            key=lambda r: (-(r.suitability or 0.0), r.student_id),
        )
        closest = sorted(
            (r for r in results if not r.eligible and len(r.failing) == 1),
            key=lambda r: (-(len(r.criteria) - len(r.failing)), r.student_id),
        )

        sources = [
            Source(
                record_id=db_record_id("company_roles", resolved["role_id"]),
                snippet=_role_snippet(resolved)[:240],
            )
        ]
        for candidate in eligible[:top_n]:
            sources.extend(candidate.sources[:1])

        return MatchResponse(
            company=resolved["company"],
            role=resolved["title"],
            role_id=int(resolved["role_id"]),
            weights=load_weights(resolved),
            candidates=eligible[:top_n],
            closest_misses=closest[:top_n],
            sources=sources,
        )

    # ------------------------------------------------------------------
    # Skill gaps
    # ------------------------------------------------------------------

    def skill_gap(
        self, student_id: str, company: str | None = None, role: str | None = None
    ) -> SkillGapResponse | None:
        student = self._student(student_id)
        if student is None:
            return None
        resolved = self.resolve_role(company, role)
        role_id = resolved["role_id"] if resolved else None
        requirements = self._requirements(role_id) if role_id else []
        levels = self._skill_levels(student_id)

        report = gaps_module.analyse(requirements, levels)
        sources = [
            Source(
                record_id=db_record_id("students", student_id),
                snippet=_student_snippet(student)[:240],
            )
        ]
        if resolved:
            sources.insert(
                0,
                Source(
                    record_id=db_record_id("company_roles", resolved["role_id"]),
                    snippet=_role_snippet(resolved)[:240],
                ),
            )
        sources.extend(report.sources)

        return SkillGapResponse(
            student_id=student_id,
            student_name=student["name"],
            target_role=resolved["title"] if resolved else None,
            company=resolved["company"] if resolved else company,
            gaps=report.gaps,
            learning_path=report.learning_path,
            sources=_dedupe(sources),
        )

    # ------------------------------------------------------------------
    # What-if
    # ------------------------------------------------------------------

    def what_if(self, request: WhatIfRequest) -> WhatIfResponse | None:
        student = self._student(request.student_id)
        if student is None:
            return None

        overrides: dict[str, Any] = {}
        for field in ("cgpa", "attendance_pct", "backlogs", "communication_score", "project_count"):
            value = getattr(request, field)
            if value is not None:
                overrides[field] = value
        if request.skill_levels:
            overrides["skill_levels"] = dict(request.skill_levels)

        baseline = self.eligibility(student_id=request.student_id)
        projected = self.eligibility(student_id=request.student_id, overrides=overrides)

        base_map = {_role_key(r): r for r in baseline}
        proj_map = {_role_key(r): r for r in projected}

        baseline_eligible = sorted(k for k, r in base_map.items() if r.eligible)
        projected_eligible = sorted(k for k, r in proj_map.items() if r.eligible)

        per_role: list[dict[str, Any]] = []
        for key in sorted(set(base_map) | set(proj_map)):
            base = base_map.get(key)
            proj = proj_map.get(key)
            per_role.append(
                {
                    "role": key,
                    "was_eligible": bool(base and base.eligible),
                    "now_eligible": bool(proj and proj.eligible),
                    "still_failing": proj.failing if proj else [],
                    "suitability": proj.suitability if proj else None,
                }
            )

        return WhatIfResponse(
            student_id=request.student_id,
            baseline_eligible=baseline_eligible,
            projected_eligible=projected_eligible,
            opened_up=sorted(set(projected_eligible) - set(baseline_eligible)),
            lost=sorted(set(baseline_eligible) - set(projected_eligible)),
            per_role=per_role,
        )

    # ------------------------------------------------------------------
    # Cohort audit log
    # ------------------------------------------------------------------

    def log_cohort_query(
        self,
        kind: str,
        query_text: str,
        *,
        company: str | None = None,
        role: str | None = None,
        role_id: int | None = None,
        department: str | None = None,
        user_id: str | None = None,
        requester_role: str = "staff",
        result_count: int = 0,
    ) -> None:
        """Record a query that ranged over many students' records."""
        try:
            execute(
                """
                INSERT INTO cohort_queries
                    (kind, query, company, role_title, role_id, department, user_id,
                     `role`, result_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind, query_text, company, role, role_id, department, user_id,
                    requester_role, result_count, _now(),
                ),
            )
        except Exception as exc:  # pragma: no cover - audit must not break a request
            log.warning("could not log cohort query: %s", exc)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return value if isinstance(value, list) else []


def _role_key(result: EligibilityResult) -> str:
    return f"{result.company} {result.role}"


def _dedupe(sources: list[Source]) -> list[Source]:
    seen: set[str] = set()
    out: list[Source] = []
    for source in sources:
        if source.record_id in seen:
            continue
        seen.add(source.record_id)
        out.append(source)
    return out
