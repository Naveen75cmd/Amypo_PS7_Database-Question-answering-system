"""POST /api/v1/ask and GET /api/v1/ask/trace/{request_id}.

Phase 1 ships the contract and a clear not-ready signal; Phase 4 fills the body.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.schemas import AskRequest, AskResponse, TraceResponse

router = APIRouter(tags=["qa"])

READY = False


@router.post("/ask", response_model=AskResponse, summary="Grounded question answering")
def ask(payload: AskRequest) -> AskResponse:
    if not READY:
        raise HTTPException(
            status_code=503,
            detail="QA pipeline not available yet (implemented in Phase 4).",
        )
    raise HTTPException(status_code=501, detail="unreachable")


@router.get(
    "/ask/trace/{request_id}",
    response_model=TraceResponse,
    summary="Full reasoning trace for a previous request",
)
def trace(request_id: str) -> TraceResponse:
    raise HTTPException(
        status_code=404,
        detail=f"No trace for request_id={request_id}.",
    )
