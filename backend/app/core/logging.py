"""Structured JSON logging with ``request_id`` propagation.

Every log line carries the current request id from a contextvar, so a trace can
be reconstructed from the logs alone. PII is redacted unless ``AMYPO_LOG_PII``.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_STUDENT_ID_RE = re.compile(r"\bS\d{3,}\b")


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str:
    return request_id_var.get()


def redact(text: str, enabled: bool = False) -> str:
    """Mask emails and student ids. Disabled by default for local debugging."""
    if enabled:
        return text
    text = _EMAIL_RE.sub("[email]", text)
    return _STUDENT_ID_RE.sub("[student]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        from .settings import settings

        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "msg": redact(record.getMessage(), settings.log_pii),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # uvicorn's access log duplicates our own request logging
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def log_event(logger: logging.Logger, msg: str, **fields: Any) -> None:
    logger.info(msg, extra={"extra_fields": fields})
