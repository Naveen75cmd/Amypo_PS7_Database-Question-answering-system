"""Aggregate metrics for the dashboard and the evaluation page.

Everything is computed from what actually happened: ``query_log`` for quality and
confidence, ``router_decisions`` for route mix, latency and cost, and
``resource_samples`` for the live series. Nothing here is synthesised.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.schemas import MetricsResponse
from ..db import query


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return float(ordered[index])


def _latency_by_route() -> tuple[dict[str, float], dict[str, float]]:
    rows = query("SELECT routed_to, latency_ms FROM router_decisions")
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(row["routed_to"], []).append(float(row["latency_ms"] or 0.0))
    p50 = {route: round(_percentile(v, 0.5), 1) for route, v in grouped.items()}
    p95 = {route: round(_percentile(v, 0.95), 1) for route, v in grouped.items()}
    return p50, p95


def collect_metrics(engine=None, series_limit: int = 60) -> MetricsResponse:
    quality = query(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(abstained), 0) AS abstained,
               COALESCE(AVG(confidence), 0) AS avg_confidence,
               COALESCE(AVG(groundedness), 0) AS avg_groundedness
        FROM query_log
        """
    )
    q = quality[0] if quality else {}
    total = int(q.get("total", 0) or 0)
    abstained = int(q.get("abstained", 0) or 0)

    routes = query("SELECT routed_to, COUNT(*) AS n FROM router_decisions GROUP BY routed_to")
    by_route = {row["routed_to"]: int(row["n"]) for row in routes}
    routed_total = sum(by_route.values())
    cache_hits = by_route.get("cache", 0)

    cost = query(
        """
        SELECT COALESCE(SUM(estimated_cost), 0) AS cost,
               COALESCE(SUM(always_cloud_cost), 0) AS always_cloud
        FROM router_decisions
        """
    )
    c = cost[0] if cost else {}
    cumulative = float(c.get("cost", 0.0) or 0.0)
    always_cloud = float(c.get("always_cloud", 0.0) or 0.0)
    savings = always_cloud - cumulative
    savings_pct = (savings / always_cloud * 100.0) if always_cloud > 0 else 0.0

    p50, p95 = _latency_by_route()

    samples = query(
        """
        SELECT ram_available_mb, cpu_load_pct, bandwidth_kbps, api_quota_remaining,
               scenario, sampled_at
        FROM resource_samples ORDER BY id DESC LIMIT ?
        """,
        (int(series_limit),),
    )

    return MetricsResponse(
        total_requests=total,
        cache_hit_rate=round(cache_hits / routed_total, 4) if routed_total else 0.0,
        requests_by_route=by_route,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        cumulative_cost_inr=round(cumulative, 4),
        always_cloud_cost_inr=round(always_cloud, 4),
        savings_inr=round(savings, 4),
        savings_pct=round(savings_pct, 2),
        abstention_rate=round(abstained / total, 4) if total else 0.0,
        avg_confidence=round(float(q.get("avg_confidence", 0.0) or 0.0), 4),
        groundedness_avg=round(float(q.get("avg_groundedness", 0.0) or 0.0), 4),
        routing_agreement=(engine.routing_agreement() if engine is not None else None),
        resource_series=[dict(row) for row in samples],
    )


def decision_rows(limit: int = 50) -> list[dict[str, Any]]:
    rows = query(
        "SELECT * FROM router_decisions ORDER BY id DESC LIMIT ?", (int(limit),)
    )
    for row in rows:
        features = row.get("features_json")
        if isinstance(features, str) and features:
            try:
                row["features_json"] = json.loads(features)
            except (TypeError, ValueError):
                row["features_json"] = {}
    return rows
