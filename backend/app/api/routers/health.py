"""GET /api/v1/health — component status and versions.

Deliberately cheap: it reports *readiness* (does the artefact exist, is the
database reachable) rather than forcing the embedding model or LLM to load.
"""

from __future__ import annotations

import importlib.metadata as md
import platform
import sys

from fastapi import APIRouter

from ... import __version__
from ...core.schemas import HealthComponent, HealthResponse
from ...core.settings import settings
from ...db import get_connection

router = APIRouter(tags=["health"])


def _db_status() -> HealthComponent:
    try:
        conn = get_connection()
        conn.execute("SELECT 1").fetchone()
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        return HealthComponent(status="ok", detail=f"{tables} tables at {settings.db_path}")
    except Exception as exc:  # pragma: no cover - defensive
        return HealthComponent(status="down", detail=str(exc))


def _index_status() -> HealthComponent:
    try:
        from ...db import query_one

        row = query_one("SELECT COUNT(*) AS n FROM chunks")
        n = int(row["n"]) if row else 0
        if n == 0:
            return HealthComponent(status="not_loaded", detail="no chunks indexed yet")
        embedded = query_one(
            "SELECT COUNT(*) AS n FROM chunks WHERE embedding IS NOT NULL"
        )
        e = int(embedded["n"]) if embedded else 0
        state = "ok" if e else "degraded"
        return HealthComponent(status=state, detail=f"{n} chunks, {e} embedded")
    except Exception as exc:  # pragma: no cover
        return HealthComponent(status="down", detail=str(exc))


def _llm_status() -> HealthComponent:
    try:
        from ...core.container import get_container

        # Only report on an already-built client; never build one here.
        client = get_container()._cache.get("llm")
        if client is None:
            return HealthComponent(status="not_loaded", detail="LLM client not built yet")
        return HealthComponent(status=client.status(), detail=client.status_detail())
    except Exception as exc:  # pragma: no cover
        return HealthComponent(status="down", detail=str(exc))


def _router_status() -> HealthComponent:
    try:
        from ...core.container import get_container

        engine = get_container()._cache.get("router")
        if engine is None:
            return HealthComponent(
                status="not_loaded", detail="router built lazily on first request"
            )
        return HealthComponent(status="ok", detail=engine.status_detail())
    except Exception as exc:  # pragma: no cover
        return HealthComponent(status="down", detail=str(exc))


def _package_version(name: str) -> str:
    try:
        return md.version(name)
    except md.PackageNotFoundError:  # pragma: no cover
        return "absent"


@router.get("/health", response_model=HealthResponse, summary="Component health")
def health() -> HealthResponse:
    components = {
        "db": _db_status(),
        "index": _index_status(),
        "llm": _llm_status(),
        "router": _router_status(),
    }
    overall = "ok" if components["db"].status == "ok" else "degraded"
    return HealthResponse(
        status=overall,
        version=__version__,
        components=components,
        versions={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "fastapi": _package_version("fastapi"),
            "pydantic": _package_version("pydantic"),
            "scikit-learn": _package_version("scikit-learn"),
            "faiss": _package_version("faiss-cpu"),
            "sentence-transformers": _package_version("sentence-transformers"),
        },
    )
