"""POST /api/v1/ask and GET /api/v1/ask/trace/{request_id}."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.container import get_container
from ...core.logging import get_request_id
from ...core.schemas import AskRequest, AskResponse, TraceResponse
from . import ask as _self  # noqa: F401  (kept for symmetry with other routers)

router = APIRouter(tags=["qa"])


@router.post("/ask", response_model=AskResponse, summary="Grounded question answering")
def ask(payload: AskRequest) -> AskResponse:
    from ..ask_service import AskPipeline

    try:
        index = get_container().get("index")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"retrieval index unavailable: {exc}") from exc

    if getattr(index, "is_empty", False):
        raise HTTPException(
            status_code=503,
            detail="No documents indexed yet. Run: python -m app.ingest",
        )

    pipeline = AskPipeline(
        index=index,
        llm=get_container().get("llm"),
        verifier=get_container().get("verifier"),
    )

    result = pipeline.answer(
        question=payload.question,
        user_id=payload.user_id,
        role=payload.role.value,
        top_k=payload.top_k,
        request_id=get_request_id(),
        mode="hybrid_rerank",
    )
    AskPipeline.persist(result, payload.user_id, payload.role.value)
    return result.to_response()


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
