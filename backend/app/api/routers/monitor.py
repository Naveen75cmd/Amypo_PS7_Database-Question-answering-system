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


def _router():
    from ...core.container import get_container

    try:
        return get_container().get("router")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"router unavailable: {exc}") from exc


@router.get("/metrics", response_model=MetricsResponse, summary="Aggregate quality and cost metrics")
def metrics() -> MetricsResponse:
    from ...router.metrics import collect_metrics

    return collect_metrics(_router())


@router.get(
    "/router/decisions",
    response_model=DecisionsResponse,
    summary="Router decision log with reasoning",
)
def decisions(limit: int = 50) -> DecisionsResponse:
    from ...core.schemas import RouterDecision
    from ...router.metrics import decision_rows

    rows = decision_rows(limit)
    return DecisionsResponse(
        decisions=[
            RouterDecision(
                request_id=row["request_id"],
                query=row["query"],
                routed_to=row["routed_to"],
                reasoning=row["reasoning"],
                complexity=row.get("complexity"),
                intent=row.get("intent"),
                latency_ms=float(row["latency_ms"] or 0.0),
                estimated_cost=float(row["estimated_cost"] or 0.0),
                always_cloud_cost=float(row["always_cloud_cost"] or 0.0),
                ram_available_mb=row.get("ram_available_mb"),
                bandwidth_kbps=row.get("bandwidth_kbps"),
                api_quota_remaining=row.get("api_quota_remaining"),
                created_at=row.get("created_at"),
            )
            for row in rows
        ],
        total=len(rows),
    )


@router.post(
    "/simulate",
    response_model=SimulateResponse,
    summary="Replay a resource scenario and observe routing changes",
)
def simulate(payload: SimulateRequest) -> SimulateResponse:
    engine = _router()
    rows = engine.simulate(
        scenario=payload.scenario,
        steps=payload.steps,
        query_text=payload.query,
        reset=payload.reset,
    )
    return SimulateResponse(
        scenario=payload.scenario, steps=rows, summary=engine.simulate_summary(rows)
    )
