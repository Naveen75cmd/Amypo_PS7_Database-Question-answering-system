"""POST /api/v1/ask and GET /api/v1/ask/trace/{request_id}.

From Phase 5 the answer path goes through the PS1 router: the router decides the
cheapest adequate route (cache / local / offline / simulated cloud) and executes
it. The response keeps its Phase-4 contract and adds the optional ``route`` and
``trace_id`` fields.

Phase 11: the caller is identified by a verified token. ``AskRequest.role`` and
``AskRequest.user_id`` are accepted for backwards compatibility and then
ignored -- a student cannot widen their scope by asking for it, and a staff
member's attempt to read another student's record is checked against their
department assignment and audited either way.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...auth import deps
from ...auth.principal import Principal, may_read_student
from ...auth.service import record_audit
from ...core.container import get_container
from ...core.logging import get_request_id
from ...core.schemas import (
    AskRequest,
    AskResponse,
    FeedbackRequest,
    FeedbackResponse,
    TraceResponse,
)

router = APIRouter(tags=["qa"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _effective_user_id(payload_user_id: str | None, principal: Principal) -> str | None:
    """The student whose records this answer may use, from the token."""
    if principal.student_id:
        return principal.student_id
    if principal.is_staff:
        return payload_user_id
    return None


@router.post("/ask", response_model=AskResponse, summary="Grounded question answering")
def ask(
    payload: AskRequest,
    request: Request,
    principal: Principal = Depends(deps.get_principal),
) -> AskResponse:
    from ..ask_service import AskPipeline

    try:
        engine = get_container().get("router")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"router unavailable: {exc}") from exc

    ip = _client_ip(request)
    if payload.role is not None and payload.role.value != principal.role:
        # Not an error: old clients still send it. Recorded because a request
        # that asks to be someone else is worth seeing in the audit log.
        record_audit(
            actor=principal,
            action="role_override_ignored",
            allowed=True,
            target=f"claimed {payload.role.value}",
            scope=principal.cache_scope,
            ip=ip,
        )

    user_id = _effective_user_id(payload.user_id, principal)
    if payload.user_id and payload.user_id != principal.student_id:
        allowed = may_read_student(principal, payload.user_id)
        record_audit(
            actor=principal,
            action="student_scope",
            allowed=allowed,
            target=payload.user_id,
            scope=principal.cache_scope,
            ip=ip,
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail="Not permitted: this account may not read that student's records.",
            )

    request_id = get_request_id() or uuid.uuid4().hex[:16]
    execution = engine.run(
        request_id=request_id,
        query=payload.question,
        user_id=user_id,
        role=principal.role,
        complexity_hint=payload.complexity_hint,
        principal=principal,
    )

    # Persist a trace: the real pipeline result, or a minimal cache-hit trace.
    result = execution.pipeline_result
    if result is not None:
        AskPipeline.persist(result, user_id, principal.role)
    elif execution.route.value == "cache":
        cached = AskPipeline.cached_result(
            request_id=request_id,
            question=payload.question,
            answer=execution.answer,
            sources=execution.sources,
            confidence=execution.confidence,
            route=execution.route.value,
            latency_ms=execution.latency_ms,
        )
        AskPipeline.persist(cached, user_id, principal.role)

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
def feedback(
    payload: FeedbackRequest,
    principal: Principal = Depends(deps.get_principal),
) -> FeedbackResponse:
    """Record a thumbs rating against a logged answer.

    This is the signal Phase 8 item 1 retrains the complexity classifier from:
    ``query_log.feedback`` was in the schema from the start but nothing ever
    wrote to it, so "retrain from thumbs feedback" had no feedback to learn
    from. A rating for an unknown request is still recorded as accepted=False
    rather than erroring, because a dropped thumb must never break the UI.

    A rating on someone else's answer is a 404 rather than a silent no-op: the
    row exists, it is just not this caller's to rate.
    """
    from ...db import execute, query

    rows = query(
        "SELECT request_id, user_id FROM query_log WHERE request_id = ?",
        (payload.request_id,),
    )
    if not rows:
        return FeedbackResponse(
            request_id=payload.request_id, rating=payload.rating, recorded=False
        )
    owner = rows[0].get("user_id")
    if not principal.is_admin and owner and owner != principal.student_id:
        raise HTTPException(
            status_code=404, detail=f"No trace for request_id={payload.request_id}."
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
    principal: Principal = Depends(deps.get_principal),
) -> list[dict]:
    """Recent queries for the chat history rail, always scoped to the caller.

    A student sees only their own questions, staff see questions they were
    allowed to ask over their own departments, and admin sees everything. The
    previous version trusted a ``requester_role`` query parameter, which meant a
    student could send ``?requester_role=staff`` and read the whole log; that
    parameter is gone.
    """
    from ...db import query

    limit = max(1, min(int(limit), 200))
    if principal.is_admin:
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
        return [dict(r) for r in rows]

    if principal.is_staff:
        from ...auth.principal import allowed_student_ids

        allowed = allowed_student_ids(principal)
        if allowed is None:
            rows = query(
                """
                SELECT request_id, question, user_id, intent, confidence, abstained,
                       created_at
                FROM query_log ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in rows]
        if not allowed:
            return []
        placeholders = ", ".join("?" for _ in allowed)
        rows = query(
            f"""
            SELECT request_id, question, user_id, intent, confidence, abstained,
                   created_at
            FROM query_log
            WHERE user_id IN ({placeholders})
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*tuple(allowed), limit),
        )
        return [dict(r) for r in rows]

    rows = query(
        """
        SELECT request_id, question, user_id, intent, confidence, abstained,
               created_at
        FROM query_log
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (principal.student_id, limit),
    )
    return [dict(r) for r in rows]


@router.get(
    "/ask/trace/{request_id}",
    response_model=TraceResponse,
    summary="Full reasoning trace for a previous request",
)
def trace(request_id: str, principal: Principal = Depends(deps.get_principal)) -> TraceResponse:
    from ...db import query
    from ..ask_service import load_trace

    rows = query("SELECT user_id FROM query_log WHERE request_id = ?", (request_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"No trace for request_id={request_id}.")
    owner = rows[0].get("user_id")
    if not principal.is_admin and not (owner and may_read_student(principal, owner)):
        raise HTTPException(status_code=404, detail=f"No trace for request_id={request_id}.")

    stored = load_trace(request_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No trace for request_id={request_id}.")
    return stored
