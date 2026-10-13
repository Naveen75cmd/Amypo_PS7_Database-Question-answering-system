"""Resource status, metrics, decision log and the scenario simulator."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.schemas import (
    DecisionsResponse,
    MetricsResponse,
    ResourceStatus,
    RetrainResponse,
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


@router.post(
    "/router/retrain",
    response_model=RetrainResponse,
    summary="Retrain the complexity classifier and report the accuracy delta",
)
def retrain() -> RetrainResponse:
    """On-demand retrain (Phase 8, item 1).

    The brief asks for nightly/on-demand retraining from ``query_log`` plus
    thumbs feedback, with the accuracy delta shown on the dashboard. There is no
    scheduler in this app by design — it must run offline from one command — so
    "on demand" is an endpoint the dashboard calls, and the delta is computed
    against the accuracy of the model that was live a moment ago.

    Retraining is CPU-bound but short (a few hundred labelled questions), and a
    failure falls back to the previously loaded model rather than leaving the
    router with no classifier at all.
    """
    from ...core.container import get_container
    from ...router.classifier import ComplexityClassifier

    try:
        engine = get_container().get("router")
    except Exception as exc:  # pragma: no cover - router always available in prod
        raise HTTPException(status_code=503, detail=f"router unavailable: {exc}") from exc

    previous = getattr(engine.classifier, "report", None)
    previous_accuracy = previous.accuracy if previous is not None else None

    try:
        trained = ComplexityClassifier.train(save=True)
    except Exception as exc:
        # Keep serving with the model we already have rather than failing hard.
        raise HTTPException(
            status_code=503, detail=f"retrain failed: {exc}"
        ) from exc

    engine.classifier = trained
    report = trained.report
    if report is None:  # pragma: no cover - train() always builds a report
        raise HTTPException(status_code=503, detail="retrain produced no report")

    delta = (
        round(report.accuracy - previous_accuracy, 4)
        if previous_accuracy is not None
        else None
    )
    return RetrainResponse(
        accuracy=round(report.accuracy, 4),
        macro_f1=round(report.macro_f1, 4),
        samples=report.samples,
        previous_accuracy=(
            round(previous_accuracy, 4) if previous_accuracy is not None else None
        ),
        delta=delta,
        # getattr: an artefact trained by an older recipe has no such fields.
        holdout=int(getattr(report, "holdout", 0) or 0),
        from_feedback=int(getattr(report, "from_feedback", 0) or 0),
        confirmed=int(getattr(report, "confirmed", 0) or 0),
        corrected=int(getattr(report, "corrected", 0) or 0),
    )


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
