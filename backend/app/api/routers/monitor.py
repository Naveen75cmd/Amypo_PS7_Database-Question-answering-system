"""Resource status, metrics, decision log and the scenario simulator."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.schemas import (
    DecisionsResponse,
    MetricsResponse,
    ResourceStatus,
    SimulateRequest,
    SimulateResponse,
)

router = APIRouter(tags=["monitor"])

READY = False


@router.get(
    "/resource-status",
    response_model=ResourceStatus,
    summary="Live RAM, CPU, bandwidth and simulated-cloud quota",
)
def resource_status() -> ResourceStatus:
    if not READY:
        raise HTTPException(
            status_code=503,
            detail="Resource monitor not available yet (implemented in Phase 5).",
        )
    raise HTTPException(status_code=501, detail="unreachable")


@router.get("/metrics", response_model=MetricsResponse, summary="Aggregate quality and cost metrics")
def metrics() -> MetricsResponse:
    raise HTTPException(status_code=503, detail="Metrics available after Phase 5.")


@router.get(
    "/router/decisions",
    response_model=DecisionsResponse,
    summary="Router decision log with reasoning",
)
def decisions(limit: int = 50) -> DecisionsResponse:
    raise HTTPException(status_code=503, detail="Decision log available after Phase 5.")


@router.post(
    "/simulate",
    response_model=SimulateResponse,
    summary="Replay a resource scenario and observe routing changes",
)
def simulate(payload: SimulateRequest) -> SimulateResponse:
    raise HTTPException(status_code=503, detail="Simulator available after Phase 5.")
