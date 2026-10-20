"""Placement eligibility, matching, skill gaps and what-if simulation.

These are the staff console's data endpoints (``/ask`` is the student-facing
channel). Access follows the same rule as the rest of the system: a student may
only see their own record, staff may run cohort queries over the departments
they are assigned to, and every cohort query is written to ``cohort_queries`` so
a query over many students' records is an auditable event.

Phase 11: the role and the student id come from the verified token. The old
``requester_role`` and ``user_id`` query parameters are gone -- a student could
send ``?requester_role=staff`` and read the cohort tools, which is exactly the
hole this closes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from ...auth import deps
from ...auth.principal import (
    ROLE_ADMIN,
    ROLE_STAFF,
    Principal,
    may_read_student,
)
from ...auth.service import record_audit
from ...core.container import get_container
from ...core.schemas import (
    CohortQuery,
    EligibilityResponse,
    MatchRequest,
    MatchResponse,
    SkillGapResponse,
    WhatIfRequest,
    WhatIfResponse,
)

router = APIRouter(tags=["placement"])

log = logging.getLogger(__name__)

_require_staff = deps.require(ROLE_STAFF, ROLE_ADMIN, action="placement.cohort")


def _engine():
    try:
        return get_container().get("placement")
    except Exception as exc:  # pragma: no cover - surfaced as 503
        raise HTTPException(status_code=503, detail=f"placement unavailable: {exc}") from exc


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _own_student(principal: Principal, requested: str | None) -> str:
    """The student id a request may act on, or 403.

    A student's scope is fixed to the id in their token, so requesting anybody
    else is refused rather than quietly rewritten.
    """
    if principal.is_staff:
        if not requested:
            raise HTTPException(status_code=400, detail="student_id is required.")
        if not may_read_student(principal, requested):
            raise HTTPException(
                status_code=403,
                detail="Not permitted: that student is outside your assigned departments.",
            )
        return requested
    if not principal.student_id:
        raise HTTPException(status_code=403, detail="Not permitted: no student scope.")
    if requested and requested != principal.student_id:
        raise HTTPException(
            status_code=403, detail="A student may only view their own record."
        )
    return principal.student_id


def _staff_department(principal: Principal, requested: str | None) -> str | None:
    """Constrain a cohort query to the staff member's assigned department."""
    if principal.is_admin:
        return requested
    if not requested:
        return principal.departments[0] if principal.departments else None
    if requested not in principal.departments:
        raise HTTPException(
            status_code=403,
            detail=f"Not permitted: you are not assigned to {requested}.",
        )
    return requested


@router.get(
    "/placement/cohort-queries",
    response_model=list[CohortQuery],
    summary="Audit trail of staff cohort queries (Phase 8, item 7)",
)
def cohort_queries(
    limit: int = Query(default=50, ge=1, le=500),
    principal: Principal = Depends(_require_staff),
) -> list[CohortQuery]:
    """Every query that ranged over many students' records, newest first.

    Writing the audit row is not enough on its own: an audit trail nobody can
    read is not a control. Staff only, and it returns metadata about the *query*
    (who ran it, over which cohort, how many rows it touched) rather than the
    student records themselves, so reading the trail never widens access.
    """
    from ...db import query

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
def roles(principal: Principal = Depends(deps.get_principal)) -> list[dict]:
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
    request: Request,
    student_id: str | None = None,
    company: str | None = None,
    role: str | None = None,
    role_id: int | None = None,
    department: str | None = None,
    principal: Principal = Depends(deps.get_principal),
) -> EligibilityResponse:
    engine = _engine()

    if principal.is_staff:
        if student_id:
            # A single row read: allowed only inside the account's departments,
            # and audited, because it is one student's record rather than an
            # aggregate.
            student_id = _own_student(principal, student_id)
            record_audit(
                actor=principal,
                action="pii.read",
                allowed=True,
                target=student_id,
                scope=principal.cache_scope,
                ip=_client_ip(request),
                detail="single-student eligibility",
            )
        else:
            department = _staff_department(principal, department)
    else:
        # Without a student id this is a cohort query ("who is eligible for X"),
        # which is a staff capability. A student asks for their own record by id.
        if not student_id and any(
            [company, role, role_id is not None, department]
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Cohort queries are limited to staff; a student may only see "
                    "their own eligibility."
                ),
            )
        student_id = _own_student(principal, student_id)

    results = engine.eligibility(
        student_id=student_id, company=company, role=role, role_id=role_id,
        department=department,
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
            user_id=principal.user_id, requester_role=principal.role,
            result_count=len(results),
        )
    return EligibilityResponse(results=results, total=len(results))


@router.get(
    "/placement/eligibility/{student_id}/report.pdf",
    summary="Downloadable PDF eligibility report (Phase 8, item 11)",
    responses={200: {"content": {"application/pdf": {}}}},
)
def eligibility_report_pdf(
    student_id: str,
    request: Request,
    company: str | None = None,
    role: str | None = None,
    principal: Principal = Depends(deps.get_principal),
) -> Response:
    """Render the student's eligibility as a self-contained PDF.

    Access follows the same rule as the JSON endpoint: a student may only export
    their own report, so this cannot be used to harvest other students' records.
    """
    from ...placement.export import build_eligibility_pdf, pdf_filename

    student_id = _own_student(principal, student_id)
    if not principal.is_staff:
        record_audit(
            actor=principal, action="pii.export", allowed=True, target=student_id,
            scope=principal.cache_scope, ip=_client_ip(request),
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
def match(payload: MatchRequest, principal: Principal = Depends(_require_staff)) -> MatchResponse:
    engine = _engine()
    department = _staff_department(principal, payload.department)
    result = engine.match(
        role_id=payload.role_id,
        company=payload.company,
        role=payload.role,
        top_n=payload.top_n,
        department=department,
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
        department=department, user_id=principal.user_id,
        requester_role=principal.role, result_count=len(result.candidates),
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
    principal: Principal = Depends(deps.get_principal),
) -> SkillGapResponse:
    engine = _engine()
    student_id = _own_student(principal, student_id)
    result = engine.skill_gap(student_id, company=company, role=role)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No record for student {student_id}.")
    return result


@router.post(
    "/placement/what-if",
    response_model=WhatIfResponse,
    summary="Recompute eligibility with overrides, without persisting them",
)
def what_if(
    payload: WhatIfRequest, principal: Principal = Depends(deps.get_principal)
) -> WhatIfResponse:
    payload.student_id = _own_student(principal, payload.student_id)
    engine = _engine()
    result = engine.what_if(payload)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No record for student {payload.student_id}.")
    return result
