"""POST /api/v1/route — the PS1 routing decision (Phase 5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ...core.container import get_container
from ...core.logging import get_request_id
from ...core.schemas import RouteRequest, RouteResponse

router = APIRouter(tags=["router"])


@router.post("/route", response_model=RouteResponse, summary="Choose and run the cheapest adequate path")
def route(payload: RouteRequest) -> RouteResponse:
    try:
        engine = get_container().get("router")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"router unavailable: {exc}") from exc

    request_id = payload.request_id or get_request_id() or uuid.uuid4().hex[:16]
    execution = engine.run(
        request_id=request_id,
        query=payload.query,
        user_id=payload.user_id,
        role=payload.role.value,
        complexity_hint=payload.complexity_hint,
        execute_answer=payload.execute,
    )
    return engine.to_response(execution)
