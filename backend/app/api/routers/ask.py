"""POST /api/v1/ask and GET /api/v1/ask/trace/{request_id}.

From Phase 5 the answer path goes through the PS1 router: the router decides the
cheapest adequate route (cache / local / offline / simulated cloud) and executes
it. The response keeps its Phase-4 contract and adds the optional ``route`` and
``trace_id`` fields.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query

from ...core.container import get_container
from ...core.logging import get_request_id
from ...core.schemas import (
    AskRequest,
    AskResponse,
    FeedbackRequest,
    FeedbackResponse,
    Role,
    Route,
    TraceResponse,
)

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
        # --- Phase 8 add-ons ------------------------------------------
        clarifying_question=execution.clarifying_question,
        closest_records=execution.closest_records or [],
        conflict=execution.conflict,
        carbon=execution.carbon,
        detected_language=execution.detected_language,
        model_tier=execution.model_tier,
    )


@router.post(
    "/ask/feedback",
    response_model=FeedbackResponse,
    summary="Rate an answer (thumbs up / down)",
)
def feedback(payload: FeedbackRequest) -> FeedbackResponse:
    """Record a thumbs rating against a logged answer.

    This is the signal Phase 8 item 1 retrains the complexity classifier from:
    ``query_log.feedback`` was in the schema from the start but nothing ever
    wrote to it, so "retrain from thumbs feedback" had no feedback to learn
    from. A rating for an unknown request is still recorded as accepted=False
    rather than erroring, because a dropped thumb must never break the UI.
    """
    from ...db import execute, query

    rows = query(
        "SELECT request_id FROM query_log WHERE request_id = ?", (payload.request_id,)
    )
    if not rows:
        return FeedbackResponse(
            request_id=payload.request_id, rating=payload.rating, recorded=False
        )

    execute(
        "UPDATE query_log SET feedback = ? WHERE request_id = ?",
        (payload.rating, payload.request_id),
    )
    return FeedbackResponse(
        request_id=payload.request_id, rating=payload.rating, recorded=True
    )


@router.get(
    "/ask/history",
    response_model=list[dict],
    summary="Recent answered questions from the query log",
)
def history(
    limit: int = 50,
    user_id: str | None = None,
    requester_role: Role = Query(default=Role.student),
) -> list[dict]:
    """Recent queries for the chat history rail.

    A student caller sees only their own queries; staff see everything. The
    rows are summaries — the full trace stays fetchable via /ask/trace/{id}.
    """
    from ...db import query

    limit = max(1, min(int(limit), 200))
    if requester_role == Role.staff:
        rows = query(
            """
            SELECT request_id, question, user_id, intent, confidence, abstained,
                   created_at
            FROM query_log
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
    else:
        rows = query(
            """
            SELECT request_id, question, user_id, intent, confidence, abstained,
                   created_at
            FROM query_log
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
    return [dict(r) for r in rows]


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
