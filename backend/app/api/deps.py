"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ..core.container import get_container
from ..core.logging import get_request_id


def request_id() -> str:
    return get_request_id()


def component(name: str) -> Any:
    """FastAPI dependency: ``Depends(component("index"))``."""
    def _get() -> Any:
        return get_container().get(name)

    return _get


def client_meta(request: Request) -> dict[str, Any]:
    return {
        "request_id": get_request_id(),
        "user_agent": request.headers.get("user-agent", ""),
    }
