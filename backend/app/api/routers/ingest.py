"""POST /api/v1/ingest — document and structured ingestion."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ...core.schemas import IngestRequest, IngestResponse
from ...core.settings import settings
from ...ingest.pipeline import ingest_all

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse, summary="Ingest documents and structured rows")
def ingest(payload: IngestRequest) -> IngestResponse:
    target = Path(payload.path) if payload.path else settings.raw_dir
    if not target.exists():
        raise HTTPException(status_code=400, detail=f"path does not exist: {target}")

    result = ingest_all(path=target, force=payload.force)

    # Refresh the retrieval index in place when one is already loaded.
    from ...core.container import get_container

    try:
        index = get_container()._cache.get("index")
        if index is not None:
            index.refresh()
    except Exception:  # pragma: no cover - index refresh must not fail the ingest
        pass

    return IngestResponse(
        documents=result.documents,
        chunks=result.chunks,
        records=result.records,
        skipped_unchanged=result.skipped_unchanged,
        duration_ms=result.duration_ms,
        errors=result.errors,
    )
