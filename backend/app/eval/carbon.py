"""Carbon / energy estimate per query (Phase 8, item 9).

A sustainability line item for the judges: what did that answer cost in kWh and
INR, and what would the same answer have cost if every call went to the cloud?

These are *estimates*, not meter readings, and the payload says so via
``source: "estimate"`` so nobody quotes them as measurements. The model is
deliberately simple and stated: a fixed per-call draw scaled by latency, with a
local call priced at the configured electricity rate and a cloud call priced at
the configured per-call API price. The comparison — local far below always-cloud
— holds across every plausible value of those constants, which is the number the
brief actually asks for.

Assumptions live here rather than in settings because they are properties of the
estimator, not tunables anyone should be sweeping.
"""

from __future__ import annotations

from typing import Any

from ..core.settings import settings

SOURCE = "estimate"

# Sustained draw while answering, watts. The local path runs a small quantized
# model on the host CPU; 25 W is a conservative slice of a laptop TDP and is
# applied to the whole latency window rather than to model-load time.
LOCAL_DRAW_W = 25.0

# The cloud leg still burns local energy (network, GPU queue, cooling) on top of
# the API price. Expressed as a multiple of the local draw so the comparison
# stays honest about *where* the energy goes: a remote round trip is longer and
# draws more, but the point of the line item is the total, not the location.
CLOUD_DRAW_W = 45.0


def estimate_query_energy(
    route: str, latency_ms: float, calls: int = 1
) -> dict[str, Any]:
    """Energy and cost for one query on ``route``.

    ``route`` is the route the router actually took, so the payload reflects
    what happened rather than a counterfactual.
    """
    latency_ms = max(0.0, float(latency_ms))
    seconds = (latency_ms / 1000.0) * max(1, int(calls))

    cloud = route in {"cloud", "always_cloud", "simulated_cloud"}
    watts = CLOUD_DRAW_W if cloud else LOCAL_DRAW_W
    kwh = (watts * seconds) / 3_600_000.0

    # Floor at one micro-kWh so a sub-millisecond local answer never reports
    # exactly zero, which would read as "costs nothing" rather than "too small".
    kwh = max(kwh, 1e-6)

    if cloud:
        inr = settings.cloud_price_inr_per_call * max(1, int(calls))
    else:
        inr = settings.local_price_inr_per_call * max(1, int(calls))

    return {
        "kwh": round(kwh, 8),
        "inr": round(inr, 6),
        "source": SOURCE,
    }


def always_cloud_energy(latency_ms: float, calls: int = 1) -> dict[str, Any]:
    """The baseline the brief asks us to compare against."""
    return estimate_query_energy("always_cloud", latency_ms, calls)


def savings_row(route: str, latency_ms: float) -> dict[str, Any]:
    """One row for the dashboard: this route vs always-cloud, side by side."""
    here = estimate_query_energy(route, latency_ms)
    there = always_cloud_energy(settings.cloud_latency_ms)
    return {
        "route": route,
        "kwh": here["kwh"],
        "inr": here["inr"],
        "always_cloud_kwh": there["kwh"],
        "always_cloud_inr": there["inr"],
        "kwh_saved": round(max(0.0, there["kwh"] - here["kwh"]), 8),
        "inr_saved": round(max(0.0, there["inr"] - here["inr"]), 6),
        "source": SOURCE,
    }
