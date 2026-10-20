"""Session endpoints: POST /auth/login, /auth/refresh, /auth/logout, GET /auth/me.

The access token and the refresh token both travel as httpOnly cookies for the
web app, so no token is ever readable from JavaScript or ``localStorage``. The
same values are also returned in the body, because the CLI and the organisers'
evaluation harness authenticate with a bearer header instead of a browser.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ...auth import deps
from ...auth.principal import Principal, permissions_for
from ...auth.service import (
    AuthError,
    login as login_user,
    logout as revoke_refresh,
    principal_for,
    refresh as rotate_refresh,
    staff_assignments_for,
)
from ...core.settings import settings
from ...core.schemas import (
    AuthResponse,
    LoginRequest,
    MeResponse,
    UserOut,
)

router = APIRouter(tags=["auth"])

log = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _apply_session(response: Response, bundle) -> None:
    """Attach both cookies. SameSite=Lax blocks cross-site form posts."""
    common = {
        "httponly": True,
        "samesite": settings.auth_cookie_samesite,
        "secure": settings.auth_cookie_secure,
        "path": "/",
    }
    response.set_cookie(
        settings.auth_cookie_name, bundle.access_token,
        max_age=bundle.expires_in, **common,
    )
    response.set_cookie(
        settings.auth_refresh_cookie_name, bundle.refresh_token,
        max_age=settings.refresh_token_ttl_s, **common,
    )


def _clear_session(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/")
    response.delete_cookie(settings.auth_refresh_cookie_name, path="/")


def _auth_error(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post(
    "/auth/login",
    response_model=AuthResponse,
    summary="Sign in with a local account",
    responses={401: {"description": "Wrong username or password"},
               403: {"description": "Account disabled"},
               429: {"description": "Too many failed attempts"}},
)
def login(payload: LoginRequest, request: Request, response: Response) -> AuthResponse:
    try:
        bundle = login_user(
            payload.username,
            payload.password,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
    except AuthError as exc:
        raise _auth_error(exc) from exc
    _apply_session(response, bundle)
    return AuthResponse(
        access_token=bundle.access_token,
        expires_in=bundle.expires_in,
        user=UserOut(**bundle.user),
    )


@router.post(
    "/auth/refresh",
    response_model=AuthResponse,
    summary="Rotate the session using the refresh cookie",
)
def refresh(request: Request, response: Response) -> AuthResponse:
    raw = request.cookies.get(settings.auth_refresh_cookie_name)
    try:
        bundle = rotate_refresh(
            raw or "",
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
    except AuthError as exc:
        _clear_session(response)
        raise _auth_error(exc) from exc
    _apply_session(response, bundle)
    return AuthResponse(
        access_token=bundle.access_token,
        expires_in=bundle.expires_in,
        user=UserOut(**bundle.user),
    )


@router.post("/auth/logout", summary="Revoke the session and clear the cookies")
def logout(
    request: Request,
    response: Response,
    principal: Principal = Depends(deps.optional_principal),
) -> dict[str, bool]:
    raw = request.cookies.get(settings.auth_refresh_cookie_name)
    revoked = revoke_refresh(raw, actor=principal, ip=_client_ip(request))
    _clear_session(response)
    return {"ok": True, "revoked": revoked}


@router.get("/auth/me", response_model=MeResponse, summary="The current session's identity")
def me(principal: Principal = Depends(deps.get_principal)) -> MeResponse:
    from ...auth.service import get_user

    row = get_user(principal.user_id)
    if row is None:
        # A token for a deleted account is not a session.
        raise HTTPException(status_code=401, detail="Session no longer valid.")
    fresh = principal_for(row)
    assignments = staff_assignments_for(fresh.user_id) if fresh.is_staff else []
    return MeResponse(
        user=UserOut(**{
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "role": row["role"],
            "student_id": row.get("student_id"),
            "department": row.get("department"),
            "cohort": row.get("cohort"),
            "is_active": bool(row.get("is_active")),
            "created_at": row.get("created_at"),
            "last_login": row.get("last_login"),
        }),
        role=fresh.role,
        cache_scope=fresh.cache_scope,
        student_id=fresh.student_id,
        departments=list(fresh.departments),
        cohorts=list(fresh.cohorts),
        assignments=assignments,
        permissions=permissions_for(fresh),
    )
