"""FastAPI dependencies that turn a request into a verified :class:`Principal`.

Resolution order, first match wins:

1. ``Authorization: Bearer <jwt>`` -- used by the CLI and the evaluation harness.
2. ``X-API-Key: <key>`` -- the read-only ``eval`` machine account.
3. The httpOnly session cookie -- what the web app actually uses, so no token is
   ever readable from JavaScript or ``localStorage``.
4. Nothing -- rejected with 401 when ``settings.auth_required`` (the default).

A denied role check is written to ``audit_log`` *before* the 403 is raised, so
the refusal is a record rather than only a status code.
"""

from __future__ import annotations

import logging
import secrets
from typing import Callable

from fastapi import Depends, HTTPException, Request, status

from ..core.settings import settings
from .principal import (
    ROLE_EVAL,
    Principal,
)
from .security import TokenError, decode_access_token

log = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _principal_from_claims(claims: dict) -> Principal:
    cohorts = claims.get("cohorts") or []
    return Principal(
        user_id=str(claims.get("sub") or ""),
        username=str(claims.get("username") or ""),
        role=str(claims.get("role") or ""),
        student_id=claims.get("student_id"),
        departments=tuple(claims.get("departments") or ()),
        cohorts=tuple(cohorts) if isinstance(cohorts, list | tuple) else (),
    )


def _service_principal() -> Principal:
    return Principal(
        user_id="service:harness",
        username="harness",
        role=ROLE_EVAL,
        is_service=True,
    )


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _api_key(request: Request) -> str | None:
    return request.headers.get("x-api-key")


def resolve_principal(request: Request, *, required: bool = True) -> Principal:
    """Build the principal for this request, or raise 401.

    Written as a plain function (not a generator) so routers and middleware can
    share it; the ``Depends`` wrapper below is thin.
    """
    configured_key = settings.service_api_key.strip()
    presented_key = _api_key(request)
    if presented_key and configured_key and secrets.compare_digest(
        presented_key, configured_key
    ):
        return _service_principal()

    token = _bearer(request) or request.cookies.get(settings.auth_cookie_name)
    if not token:
        if required and settings.auth_required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Unauthenticated and auth is optional: public documents only.
        return Principal(user_id="anonymous", username="anonymous", role="")

    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        if required and settings.auth_required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Session is not valid: {exc}.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return Principal(user_id="anonymous", username="anonymous", role="")
    return _principal_from_claims(claims)


def get_principal(request: Request) -> Principal:
    """Dependency: the verified caller, always required."""
    return resolve_principal(request, required=True)


def optional_principal(request: Request) -> Principal:
    """Dependency: the caller if there is one, otherwise an anonymous principal."""
    return resolve_principal(request, required=False)


def require(*roles: str, action: str = "") -> Callable[..., Principal]:
    """Dependency factory: 403 unless the caller holds one of ``roles``.

    The refusal is audited with the caller's identity and the action, which is
    what makes the matrix test meaningful: a denied attempt leaves a row behind.
    """

    def _dependency(
        request: Request, principal: Principal = Depends(get_principal)
    ) -> Principal:
        if principal.role in roles:
            return principal
        from .service import record_audit

        label = action or request.url.path
        record_audit(
            actor=principal,
            action=label,
            allowed=False,
            target=request.url.path,
            scope=principal.cache_scope,
            ip=_client_ip(request),
            detail=f"role {principal.role or 'anonymous'} not in {sorted(roles)}",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Not permitted: {label} requires "
                f"{' or '.join(sorted(roles))}; this session is "
                f"{principal.role or 'anonymous'}."
            ),
        )

    return _dependency
