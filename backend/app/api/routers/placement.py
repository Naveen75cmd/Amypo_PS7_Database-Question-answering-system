"""Placement eligibility, matching, skill gaps and what-if simulation.

These are the staff console's data endpoints (``/ask`` is the student-facing
channel). Access follows the same rule as the rest of the system: a caller in a
student role may only see their own record, while a staff role may run cohort
queries — and every cohort query is written to ``cohort_queries`` so a query over
many students' records is an auditable event.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ...core.container import get_container
from ...core.schemas import (
    CohortQuery,
    EligibilityResponse,
    MatchRequest,
    MatchResponse,
    Role,
    SkillGapResponse,
    WhatIfRequest,
    WhatIfResponse,
)

router = APIRouter(tags=["placement"])

log = logging.getLogger(__name__)


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
    "/placement/cohort-queries",
    response_model=list[CohortQuery],
    summary="Audit trail of staff cohort queries (Phase 8, item 7)",
)
def cohort_queries(
    limit: int = Query(default=50, ge=1, le=500),
    requester_role: Role = Query(default=Role.staff),
) -> list[CohortQuery]:
    """Every query that ranged over many students' records, newest first.

    Writing the audit row is not enough on its own: an audit trail nobody can
    read is not a control. Staff only, and it returns metadata about the *query*
    (who ran it, over which cohort, how many rows it touched) rather than the
    student records themselves, so reading the trail never widens access.
    """
    from ...db import query

    _deny_cohort(requester_role)
    rows = query(
        """
        SELECT id, kind, query, company, role_title, role_id, department,
               user_id, `role`, result_count, created_at
        FROM cohort_queries
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    return [CohortQuery(**row) for row in rows]


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


@router.get(
    "/placement/eligibility/{student_id}/report.pdf",
    summary="Downloadable PDF eligibility report (Phase 8, item 11)",
    responses={200: {"content": {"application/pdf": {}}}},
)
def eligibility_report_pdf(
    student_id: str,
    company: str | None = None,
    role: str | None = None,
    user_id: str | None = None,
    requester_role: Role = Query(default=Role.student),
) -> Response:
    """Render the student's eligibility as a self-contained PDF.

    Access follows the same rule as the JSON endpoint: a student may only export
    their own report, so this cannot be used to harvest other students' records.
    """
    from ...placement.export import build_eligibility_pdf, pdf_filename

    if not _is_staff(requester_role) and user_id != student_id:
        raise HTTPException(
            status_code=403,
            detail="A student may only export their own eligibility report.",
        )

    engine = _engine()
    results = engine.eligibility(student_id=student_id, company=company, role=role)
    if not results:
        raise HTTPException(status_code=404, detail=f"No record for student {student_id}.")

    student = engine._student(student_id)
    student_name = student["name"] if student else student_id

    # Learning path is a nice-to-have: a gap-analysis failure must not stop the
    # report the user actually asked for.
    learning_path: list = []
    try:
        gap = engine.skill_gap(student_id, company=company, role=role)
        if gap is not None:
            learning_path = list(gap.learning_path)
    except Exception as exc:  # pragma: no cover - never block the export
        log.warning("learning path unavailable for PDF: %s", exc)

    try:
        pdf = build_eligibility_pdf(
            student_id, str(student_name), results, learning_path
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf_filename(student_id)}"',
            "Content-Length": str(len(pdf)),
        },
    )


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
