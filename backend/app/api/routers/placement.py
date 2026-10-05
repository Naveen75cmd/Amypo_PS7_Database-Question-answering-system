"""Placement eligibility, matching, skill gaps and what-if simulation.

These are the staff console's data endpoints (``/ask`` is the student-facing
channel). Access follows the same rule as the rest of the system: a caller in a
student role may only see their own record, while a staff role may run cohort
queries — and every cohort query is written to ``cohort_queries`` so a query over
many students' records is an auditable event.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...core.container import get_container
from ...core.schemas import (
    EligibilityResponse,
    MatchRequest,
    MatchResponse,
    Role,
    SkillGapResponse,
    WhatIfRequest,
    WhatIfResponse,
)

router = APIRouter(tags=["placement"])


def _engine():
    try:
        return get_container().get("placement")
    except Exception as exc:  # pragma: no cover - surfaced as 503
        raise HTTPException(status_code=503, detail=f"placement unavailable: {exc}") from exc


def _is_staff(role: Role) -> bool:
    return role == Role.staff


def _deny_cohort(role: Role) -> None:
    if not _is_staff(role):
        raise HTTPException(
            status_code=403,
            detail="Cohort queries are limited to staff; a student may only see their own eligibility.",
        )


@router.get(
    "/placement/roles",
    response_model=list[dict],
    summary="Companies and roles available for placement queries",
)
def roles() -> list[dict]:
    """Role metadata only — no student data, so no cohort audit is needed."""
    engine = _engine()
    return [
        {
            "role_id": r["role_id"],
            "company": r["company"],
            "title": r["title"],
            "location": r.get("location"),
            "package_lpa": r.get("package_lpa"),
            "min_cgpa": r.get("min_cgpa"),
        }
        for r in engine.roles()
    ]


@router.get(
    "/placement/eligibility",
    response_model=EligibilityResponse,
    summary="Deterministic per-criterion eligibility for a student or role",
)
def eligibility(
    student_id: str | None = None,
    company: str | None = None,
    role: str | None = None,
    role_id: int | None = None,
    department: str | None = None,
    user_id: str | None = None,
    requester_role: Role = Query(default=Role.staff),
) -> EligibilityResponse:
    engine = _engine()

    if student_id and not _is_staff(requester_role) and user_id != student_id:
        raise HTTPException(
            status_code=403, detail="A student may only view their own eligibility."
        )
    if not student_id:
        _deny_cohort(requester_role)

    results = engine.eligibility(
        student_id=student_id, company=company, role=role, role_id=role_id, department=department
    )
    if not results and student_id:
        raise HTTPException(status_code=404, detail=f"No record for student {student_id}.")
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"No role matching company={company!r} role={role!r} role_id={role_id!r}.",
        )

    if not student_id:
        engine.log_cohort_query(
            "eligibility",
            f"eligibility company={company} role={role}",
            company=company, role=role, role_id=role_id, department=department,
            user_id=user_id, requester_role=requester_role.value, result_count=len(results),
        )
    return EligibilityResponse(results=results, total=len(results))


@router.post(
    "/placement/match",
    response_model=MatchResponse,
    summary="Rank eligible candidates for a role with the reasons why",
)
def match(payload: MatchRequest) -> MatchResponse:
    engine = _engine()
    result = engine.match(
        role_id=payload.role_id,
        company=payload.company,
        role=payload.role,
        top_n=payload.top_n,
        department=payload.department,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No role matching company={payload.company!r} role={payload.role!r}.",
        )
    engine.log_cohort_query(
        "match",
        f"match {result.company} {result.role}",
        company=result.company, role=result.role, role_id=result.role_id,
        department=payload.department, result_count=len(result.candidates),
    )
    return result


@router.get(
    "/placement/skill-gap/{student_id}",
    response_model=SkillGapResponse,
    summary="Missing skills and an ordered learning path for a target role",
)
def skill_gap(
    student_id: str,
    company: str | None = None,
    role: str | None = None,
    user_id: str | None = None,
    requester_role: Role = Query(default=Role.staff),
) -> SkillGapResponse:
    engine = _engine()
    if not _is_staff(requester_role) and user_id != student_id:
        raise HTTPException(
            status_code=403, detail="A student may only view their own skill gaps."
        )
    result = engine.skill_gap(student_id, company=company, role=role)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No record for student {student_id}.")
    return result


@router.post(
    "/placement/what-if",
    response_model=WhatIfResponse,
    summary="Recompute eligibility with overrides, without persisting them",
)
def what_if(payload: WhatIfRequest) -> WhatIfResponse:
    engine = _engine()
    result = engine.what_if(payload)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No record for student {payload.student_id}.")
    return result
