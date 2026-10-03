"""POST /api/v1/ingest — document and structured ingestion (Phase 2)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.schemas import IngestRequest, IngestResponse

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse, summary="Ingest documents and structured rows")
def ingest(payload: IngestRequest) -> IngestResponse:
    raise HTTPException(status_code=503, detail="Ingestion available after Phase 2.")
