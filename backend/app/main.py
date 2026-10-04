"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.middleware import RequestContextMiddleware
from .api.routers import health, ask, route, placement, monitor, ingest, evaluate
from .core.logging import configure_logging, log_event
from .core.settings import settings

log = logging.getLogger("amypo.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    from .db import get_connection

    get_connection()  # connects to MySQL and applies migrations
    log_event(
        log,
        "startup",
        version=__version__,
        db=f"{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}",
    )
    yield
    # Stop the background monitor thread if it was started.
    from .core.container import get_container

    try:
        monitor = get_container()._cache.get("monitor")
        if monitor is not None:
            monitor.stop()
    except Exception:  # pragma: no cover - shutdown must never raise
        pass
    log_event(log, "shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Fully offline Database Question-Answering System with a low-cost AI "
            "request router (PS1) and placement matching engine (PS7)."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "x-latency-ms"],
    )

    prefix = settings.api_prefix
    for module in (health, ask, route, placement, monitor, ingest, evaluate):
        app.include_router(module.router, prefix=prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "api": prefix,
        }

    return app


app = create_app()
