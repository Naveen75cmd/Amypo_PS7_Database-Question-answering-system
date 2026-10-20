"""POST /api/v1/route — the PS1 routing decision (Phase 5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from ...auth import deps
from ...auth.principal import Principal
from ...core.container import get_container
from ...core.logging import get_request_id
from ...core.schemas import RouteRequest, RouteResponse

router = APIRouter(tags=["router"])


@router.post("/route", response_model=RouteResponse, summary="Choose and run the cheapest adequate path")
def route(
    payload: RouteRequest, principal: Principal = Depends(deps.get_principal)
) -> RouteResponse:
    """The PS1 decision endpoint.

    Identity and role come from the token; ``payload.role`` is ignored. That is
    what stops a caller from claiming ``staff`` to reach staff-only documents
    through the router, which would otherwise be a second door past the filter.
    """
    try:
        engine = get_container().get("router")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"router unavailable: {exc}") from exc

    request_id = payload.request_id or get_request_id() or uuid.uuid4().hex[:16]
    user_id = payload.user_id if principal.is_staff else principal.student_id
    execution = engine.run(
        request_id=request_id,
        query=payload.query,
        user_id=user_id,
        role=principal.role,
        complexity_hint=payload.complexity_hint,
        execute_answer=payload.execute,
        principal=principal,
    )
    return engine.to_response(execution)
