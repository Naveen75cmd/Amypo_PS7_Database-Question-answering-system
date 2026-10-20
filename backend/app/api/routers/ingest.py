"""POST /api/v1/ingest — document and structured ingestion."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from ...auth import deps
from ...auth.principal import ROLE_ADMIN, ROLE_STAFF, Principal
from ...auth.service import record_audit
from ...core.schemas import IngestRequest, IngestResponse
from ...core.settings import settings
from ...ingest.pipeline import ingest_all

router = APIRouter(tags=["ingest"])

_require_staff = deps.require(ROLE_STAFF, ROLE_ADMIN, action="ingest")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/ingest", response_model=IngestResponse, summary="Ingest documents and structured rows")
def ingest(
    payload: IngestRequest,
    request: Request,
    principal: Principal = Depends(_require_staff),
) -> IngestResponse:
    """Re-index the corpus. Staff may upload, admin may also force a rebuild.

    Every ingest is audited: it changes what every role can retrieve, so it is
    one of the actions that must be attributable.
    """
    target = Path(payload.path) if payload.path else settings.raw_dir
    if not target.exists():
        raise HTTPException(status_code=400, detail=f"path does not exist: {target}")

    record_audit(
        actor=principal, action="ingest.start", allowed=True, target=str(target),
        scope=principal.cache_scope, ip=_client_ip(request),
        detail=f"force={payload.force}",
    )
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
        warmed=result.warmed,
    )


@router.get(
    "/ingest/documents",
    response_model=list[dict],
    summary="Ingested documents with chunk counts",
)
def documents(
    principal: Principal = Depends(_require_staff),
) -> list[dict]:
    """The knowledge base as it is indexed right now (read-only).

    Staff and admin only: the list includes the visibility level of every
    document, which would tell a student which staff-only titles exist.
    """
    from ...db import query

    rows = query(
        """
        SELECT d.doc_id, d.title, d.doc_type, d.access_scope, d.version,
               d.updated_at, d.indexed_at, COUNT(c.record_id) AS chunk_count
        FROM documents d
        LEFT JOIN chunks c ON c.doc_id = d.doc_id
        GROUP BY d.doc_id
        ORDER BY d.doc_type, d.doc_id
        """
    )
    return [dict(r) for r in rows]