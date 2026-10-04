"""The PS1 request router: complexity classification and the routing policy.

Submodules are imported lazily so that importing ``app.router`` never drags in
the engine (which depends on the cache, monitor and verifier) when only the
classifier is needed.
"""

from __future__ import annotations

__all__ = ["ComplexityClassifier", "RouterEngine", "RoutingDecision"]


def __getattr__(name: str):
    if name == "ComplexityClassifier":
        from .classifier import ComplexityClassifier

        return ComplexityClassifier
    if name in ("RouterEngine", "RoutingDecision"):
        from .engine import RouterEngine, RoutingDecision

        return {"RouterEngine": RouterEngine, "RoutingDecision": RoutingDecision}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
