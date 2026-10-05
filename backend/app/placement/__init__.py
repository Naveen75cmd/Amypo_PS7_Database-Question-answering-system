"""The deterministic placement engine (Phase 6).

Submodules are imported lazily so importing ``app.placement`` for the rules or
the fairness constants does not pull in the database-bound engine.
"""

from __future__ import annotations

__all__ = ["PlacementEngine", "PROTECTED_ATTRIBUTES", "assert_no_protected_attributes"]


def __getattr__(name: str):
    if name == "PlacementEngine":
        from .engine import PlacementEngine

        return PlacementEngine
    if name in ("PROTECTED_ATTRIBUTES", "assert_no_protected_attributes"):
        from . import fairness

        return getattr(fairness, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
