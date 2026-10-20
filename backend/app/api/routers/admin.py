"""Administration: user management and the audit log.

Every route here is admin-only, and every route writes an audit row. Student
records are not exposed: the response shapes are accounts and metadata, so the
admin console can operate without ever reading a student's grades.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...auth import deps
from ...auth.principal import ROLE_ADMIN, Principal
from ...auth.service import (
    AuthError,
    audit_entries,
    audit_summary,
    change_role,
    create_user,
    list_users,
    reset_password,
    set_active,
    set_assignments,
    staff_assignments_for,
)
from ...core.schemas import (
    AdminUserCreate,
    AdminUserPatch,
    AuditEntry,
    AuditResponse,
    PasswordResetRequest,
    UserOut,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

_require_admin = deps.require(ROLE_ADMIN, action="admin")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _guard(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "/admin/users",
    response_model=list[UserOut],
    summary="List accounts (admin only)",
)
def users(
    limit: int = Query(default=200, ge=1, le=1000),
    role: str | None = None,
    principal: Principal = Depends(_require_admin),
) -> list[UserOut]:
    return [UserOut(**row) for row in list_users(limit=limit, role=role)]


@router.post(
    "/admin/users",
    response_model=UserOut,
    status_code=201,
    summary="Create an account (admin only)",
)
def create(
    payload: AdminUserCreate,
    request: Request,
    principal: Principal = Depends(_require_admin),
) -> UserOut:
    try:
        row = create_user(
            actor=principal,
            username=payload.username,
            email=payload.email,
            password=payload.password,
            role=payload.role.value,
            student_id=payload.student_id,
            department=payload.department,
            cohort=payload.cohort,
            assignments=[(a.scope_kind, a.scope_value) for a in payload.assignments],
            ip=_client_ip(request),
        )
    except AuthError as exc:
        raise _guard(exc) from exc
    return UserOut(**row)


@router.patch(
    "/admin/users/{user_id}",
    response_model=UserOut,
    summary="Enable/disable, change role, reset password or reassign (admin only)",
)
def patch_user(
    user_id: str,
    payload: AdminUserPatch,
    request: Request,
    principal: Principal = Depends(_require_admin),
) -> UserOut:
    ip = _client_ip(request)
    try:
        if payload.role is not None:
            change_role(
                principal, user_id, payload.role.value, payload.student_id, ip=ip
            )
        if payload.is_active is not None:
            set_active(principal, user_id, payload.is_active, ip=ip)
        if payload.password is not None:
            reset_password(principal, user_id, payload.password, ip=ip)
        if payload.assignments is not None:
            set_assignments(
                principal,
                user_id,
                [(a.scope_kind, a.scope_value) for a in payload.assignments],
                ip=ip,
            )
        rows = [row for row in list_users(limit=1000) if row["id"] == user_id]
    except AuthError as exc:
        raise _guard(exc) from exc
    if not rows:
        raise HTTPException(status_code=404, detail="No such user.")
    return UserOut(**rows[0])


@router.post(
    "/admin/users/{user_id}/reset-password",
    summary="Reset a password and end that user's sessions (admin only)",
)
def reset(
    user_id: str,
    payload: PasswordResetRequest,
    request: Request,
    principal: Principal = Depends(_require_admin),
) -> dict[str, bool]:
    try:
        reset_password(principal, user_id, payload.password, ip=_client_ip(request))
    except AuthError as exc:
        raise _guard(exc) from exc
    return {"ok": True}


@router.get(
    "/admin/users/{user_id}/assignments",
    summary="What a staff account may look at (admin only)",
)
def assignments(
    user_id: str,
    principal: Principal = Depends(_require_admin),
) -> list[dict]:
    return staff_assignments_for(user_id)


@router.get(
    "/admin/audit",
    response_model=AuditResponse,
    summary="Audit log: every allowed and denied action (admin only)",
)
def audit(
    limit: int = Query(default=100, ge=1, le=500),
    denied_only: bool = False,
    actor_role: str | None = None,
    principal: Principal = Depends(_require_admin),
) -> AuditResponse:
    rows = audit_entries(
        limit=limit,
        allowed_only=False if denied_only else None,
        actor_role=actor_role,
    )
    return AuditResponse(
        entries=[AuditEntry(**row) for row in rows],
        total=len(rows),
        summary=audit_summary(),
    )


@router.get(
    "/admin/overview",
    summary="Account and audit counts for the admin console (admin only)",
)
def overview(principal: Principal = Depends(_require_admin)) -> dict:
    from ...db import query

    by_role = {
        row["role"]: int(row["n"])
        for row in query("SELECT role, COUNT(*) AS n FROM users GROUP BY role")
    }
    active = query("SELECT COUNT(*) AS n FROM users WHERE is_active = 1")
    return {
        "users_by_role": by_role,
        "active_users": int(active[0]["n"]) if active else 0,
        "audit": audit_summary(),
    }
