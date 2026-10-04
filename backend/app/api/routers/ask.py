"""POST /api/v1/ask and GET /api/v1/ask/trace/{request_id}.

From Phase 5 the answer path goes through the PS1 router: the router decides the
cheapest adequate route (cache / local / offline / simulated cloud) and executes
it. The response keeps its Phase-4 contract and adds the optional ``route`` and
``trace_id`` fields.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ...core.container import get_container
from ...core.logging import get_request_id
from ...core.schemas import AskRequest, AskResponse, Route, TraceResponse

router = APIRouter(tags=["qa"])


@router.post("/ask", response_model=AskResponse, summary="Grounded question answering")
def ask(payload: AskRequest) -> AskResponse:
    from ..ask_service import AskPipeline

    try:
        engine = get_container().get("router")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"router unavailable: {exc}") from exc

    request_id = get_request_id() or uuid.uuid4().hex[:16]
    execution = engine.run(
        request_id=request_id,
        query=payload.question,
        user_id=payload.user_id,
        role=payload.role.value,
        complexity_hint=payload.complexity_hint,
    )

    # Persist a trace: the real pipeline result, or a minimal cache-hit trace.
    result = execution.pipeline_result
    if result is not None:
        AskPipeline.persist(result, payload.user_id, payload.role.value)
    elif execution.route == Route.cache:
        cached = AskPipeline.cached_result(
            request_id=request_id,
            question=payload.question,
            answer=execution.answer,
            sources=execution.sources,
            confidence=execution.confidence,
            route=execution.route.value,
            latency_ms=execution.latency_ms,
        )
        AskPipeline.persist(cached, payload.user_id, payload.role.value)

    return AskResponse(
        answer=execution.answer,
        sources=execution.sources,
        confidence=execution.confidence,
        route=execution.route,
        trace_id=request_id,
        degraded=execution.degraded,
        abstained=execution.abstained,
        latency_ms=execution.latency_ms,
        estimated_cost=execution.estimated_cost,
    )


@router.get(
    "/ask/trace/{request_id}",
    response_model=TraceResponse,
    summary="Full reasoning trace for a previous request",
)
def trace(request_id: str) -> TraceResponse:
    from ..ask_service import load_trace

    stored = load_trace(request_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No trace for request_id={request_id}.")
    return stored
