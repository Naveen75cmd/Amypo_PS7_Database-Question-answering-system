"""POST /api/v1/route — the PS1 routing decision (Phase 5)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.schemas import RouteRequest, RouteResponse

router = APIRouter(tags=["router"])

READY = False


@router.post("/route", response_model=RouteResponse, summary="Choose and run the cheapest adequate path")
def route(payload: RouteRequest) -> RouteResponse:
    if not READY:
        raise HTTPException(
            status_code=503,
            detail="Router not available yet (implemented in Phase 5).",
        )
    raise HTTPException(status_code=501, detail="unreachable")
