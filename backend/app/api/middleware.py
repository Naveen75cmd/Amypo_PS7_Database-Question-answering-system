"""Middleware: request-id propagation and structured access logging."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..core.logging import log_event, set_request_id

log = logging.getLogger("amypo.api")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id (honouring an inbound one) and logs the exchange."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        incoming = request.headers.get("x-request-id")
        request_id = incoming or uuid.uuid4().hex[:16]
        set_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # let the exception handlers deal with it
            elapsed = (time.perf_counter() - started) * 1000
            log_event(
                log,
                "request failed",
                method=request.method,
                path=request.url.path,
                latency_ms=round(elapsed, 2),
            )
            raise
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = request_id
        response.headers["x-latency-ms"] = f"{elapsed:.2f}"
        log_event(
            log,
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=round(elapsed, 2),
        )
        return response
