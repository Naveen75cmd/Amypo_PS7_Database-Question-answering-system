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


def _monitor():
    from ...core.container import get_container

    try:
        return get_container().get("monitor")
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"resource monitor unavailable: {exc}"
        ) from exc


@router.get(
    "/resource-status",
    response_model=ResourceStatus,
    summary="Live RAM, CPU, bandwidth and simulated-cloud quota",
)
def resource_status() -> ResourceStatus:
    from ...core.container import get_container

    monitor = _monitor()
    # Only report Ollama state if the client has already been built; probing here
    # would add latency to a status endpoint that must stay cheap.
    llm = get_container()._cache.get("llm")
    return monitor.status(llm)


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
