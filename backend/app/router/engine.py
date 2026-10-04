"""The routing decision engine (PS1).

Policy, in the exact order the spec lists it, with every input logged:

1. cache hit                     -> ``cache``
2. RAM below the floor, or Ollama unhealthy -> ``offline_fallback``
3. the intent is purely structured (SQL answers it) -> local, no LLM needed
4. complexity low/medium and RAM fine -> ``local_model``
5. complexity high AND the local model is predicted to miss the latency budget
   AND bandwidth is usable AND quota remains -> ``cloud_api`` (simulated)
6. otherwise -> ``local_model``, else ``offline_fallback``

The engine also keeps an online EWMA of per-route latency (so "predicted
latency" adapts to this machine), prices each route, computes what an
always-cloud policy would have cost, and records an *oracle* route so routing
accuracy can be reported. Every decision is persisted to ``router_decisions``.

``cloud_api`` is a **simulation**: the cloud object tracks quota, price, latency
and failures, and the actual answer is still produced locally. No socket is
opened.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.schemas import Complexity, Intent, Route, RouteResponse, Source
from ..core.settings import settings
from ..db import execute, query
from ..retrieval.intent import is_structured_intent, understand_query
from .classifier import ComplexityClassifier

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def cache_scope(user_id: str | None, role: str) -> str:
    """The access scope a cache entry belongs to.

    Cache entries are never shared across scopes; this string is part of the
    cache key, so a staff answer can never be served to a student.
    """
    if role in settings.staff_roles:
        return "staff"
    if user_id:
        return f"student:{user_id}"
    return "public"


# Seed latencies (ms) for the EWMA; refined from real measurements per route.
_SEED_LATENCY = {
    Route.cache: 5.0,
    Route.offline_fallback: 90.0,
    Route.local_model: 2600.0,
    Route.cloud_api: float(settings.cloud_latency_ms),
}


@dataclass
class RoutingDecision:
    route: Route
    reasoning: str
    complexity: Complexity
    complexity_confidence: float
    intent: Intent
    structured: bool
    snapshot: Any
    estimated_latency_ms: float
    estimated_cost: float
    always_cloud_cost: float
    oracle_route: Route
    features: dict[str, Any] = field(default_factory=dict)
    cache_hit: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.value,
            "reasoning": self.reasoning,
            "complexity": self.complexity.value,
            "intent": self.intent.value,
            "structured": self.structured,
            "estimated_latency_ms": round(self.estimated_latency_ms, 1),
            "estimated_cost": round(self.estimated_cost, 4),
            "always_cloud_cost": round(self.always_cloud_cost, 4),
            "oracle_route": self.oracle_route.value,
            "features": self.features,
        }


@dataclass
class RouteExecution:
    decision: RoutingDecision
    request_id: str
    route: Route
    answer: str
    sources: list[Source]
    confidence: float
    abstained: bool
    degraded: bool
    latency_ms: float
    estimated_cost: float
    trace_id: str | None = None
    pipeline_result: Any = None


class RouterEngine:
    def __init__(
        self,
        index=None,
        llm=None,
        verifier=None,
        cache=None,
        classifier: ComplexityClassifier | None = None,
        monitor=None,
    ) -> None:
        self.index = index
        self.llm = llm
        self.verifier = verifier
        self.cache = cache
        self.classifier = classifier or ComplexityClassifier.load_or_train()
        self.monitor = monitor
        self._latency = dict(_SEED_LATENCY)
        # Used by the scenario simulator to force the "Ollama is down" path.
        self._force_offline = False

    # ------------------------------------------------------------------
    # Latency / cost model
    # ------------------------------------------------------------------

    def predict_latency(self, route: Route) -> float:
        return float(self._latency.get(route, 1000.0))

    def observe_latency(self, route: Route, latency_ms: float) -> None:
        alpha = settings.ewma_alpha
        previous = self._latency.get(route, latency_ms)
        self._latency[route] = alpha * latency_ms + (1 - alpha) * previous

    def route_cost(self, route: Route) -> float:
        if route == Route.cache:
            return 0.0
        if route == Route.cloud_api:
            return settings.cloud_price_inr_per_call
        return settings.local_price_inr_per_call

    # ------------------------------------------------------------------
    # Decide
    # ------------------------------------------------------------------

    def decide(
        self,
        query: str,
        user_id: str | None = None,
        role: str = "student",
        complexity_hint: Complexity | None = None,
    ) -> RoutingDecision:
        understanding = understand_query(query, user_id=user_id, role=role)
        structured = is_structured_intent(understanding.intent)
        complexity, conf, complexity_reason = self.classifier.classify(query, complexity_hint)

        snapshot = self.monitor.sample() if self.monitor is not None else None
        ram_available = snapshot.ram_available_mb if snapshot else settings.ram_comfort_mb
        bandwidth = snapshot.bandwidth_kbps if snapshot else settings.bandwidth_min_kbps
        quota = snapshot.api_quota_remaining if snapshot else settings.cloud_quota_per_day

        llm_healthy = (self.llm.healthy() if self.llm is not None else False) and not self._force_offline
        reserve = max(5, int(settings.cloud_quota_per_day * 0.1))
        ram_ok = ram_available >= settings.ram_floor_mb
        bandwidth_ok = bandwidth >= settings.bandwidth_min_kbps and bandwidth > 0
        quota_ok = quota > reserve

        scope = cache_scope(user_id, role)
        cache_hit = self.cache.lookup(query, scope) if self.cache is not None else None

        local_latency = self.predict_latency(Route.local_model)

        if cache_hit is not None:
            route = Route.cache
            reasoning = (
                f"semantic cache hit (similarity {cache_hit.similarity:.2f} >= "
                f"{settings.cache_cosine}); zero model cost"
            )
        elif not ram_ok or not llm_healthy:
            route = Route.offline_fallback
            why = (
                f"RAM {ram_available} MB < floor {settings.ram_floor_mb} MB"
                if not ram_ok
                else "local model unavailable"
            )
            reasoning = f"{why}; using extractive fallback (degraded)"
        elif structured:
            route = Route.local_model
            reasoning = (
                f"intent {understanding.intent.value} is answered from SQL templates, "
                "so no model generation is needed"
            )
        elif complexity in (Complexity.low, Complexity.medium):
            route = Route.local_model
            reasoning = (
                f"complexity {complexity.value} ({complexity_reason}) and RAM "
                f"{ram_available} MB >= floor {settings.ram_floor_mb} MB; local model is adequate"
            )
        elif (
            complexity == Complexity.high
            and local_latency > settings.latency_budget_ms
            and bandwidth_ok
            and quota_ok
        ):
            route = Route.cloud_api
            reasoning = (
                f"complexity high, predicted local latency {local_latency:.0f} ms > budget "
                f"{settings.latency_budget_ms} ms, bandwidth {bandwidth} kbps >= "
                f"{settings.bandwidth_min_kbps} kbps and quota {quota} > reserve {reserve}; "
                "routing to the simulated cloud"
            )
        else:
            route = Route.local_model
            reasoning = (
                f"complexity {complexity.value} but cloud is not viable "
                f"(bandwidth {bandwidth} kbps, quota {quota}, predicted local "
                f"{local_latency:.0f} ms); staying local"
            )

        oracle = self._oracle(
            structured=structured, complexity=complexity, ram_ok=ram_ok,
            llm_healthy=llm_healthy, bandwidth_ok=bandwidth_ok, quota_ok=quota_ok,
            cache_hit=cache_hit is not None,
        )

        return RoutingDecision(
            route=route,
            reasoning=reasoning,
            complexity=complexity,
            complexity_confidence=conf,
            intent=understanding.intent,
            structured=structured,
            snapshot=snapshot,
            estimated_latency_ms=self.predict_latency(route),
            estimated_cost=self.route_cost(route),
            always_cloud_cost=settings.cloud_price_inr_per_call,
            oracle_route=oracle,
            features={
                "ram_available_mb": ram_available,
                "bandwidth_kbps": bandwidth,
                "api_quota_remaining": quota,
                "llm_healthy": llm_healthy,
                "complexity_confidence": round(conf, 3),
                "cache_similarity": (cache_hit.similarity if cache_hit else None),
            },
            cache_hit=cache_hit,
        )

    @staticmethod
    def _oracle(
        *,
        structured: bool,
        complexity: Complexity,
        ram_ok: bool,
        llm_healthy: bool,
        bandwidth_ok: bool,
        quota_ok: bool,
        cache_hit: bool,
    ) -> Route:
        """The route a perfect policy would pick: cheapest path meeting quality.

        Cache if we can; SQL tools when the question is structured; otherwise
        local when the machine can cope and the question is easy, cloud for hard
        questions when the cloud is usable, and the extractive fallback when the
        local model is not.
        """
        if cache_hit:
            return Route.cache
        # A machine that cannot run the model has to fall back, whatever the
        # question is — the same gate the policy applies first.
        if not ram_ok or not llm_healthy:
            return Route.offline_fallback
        if structured:
            return Route.local_model
        if complexity in (Complexity.low, Complexity.medium):
            return Route.local_model
        if bandwidth_ok and quota_ok:
            return Route.cloud_api
        return Route.local_model

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def run(
        self,
        request_id: str,
        query: str,
        user_id: str | None = None,
        role: str = "student",
        complexity_hint: Complexity | None = None,
        execute_answer: bool = True,
    ) -> RouteExecution:
        decision = self.decide(query, user_id=user_id, role=role, complexity_hint=complexity_hint)
        started = time.perf_counter()

        from ..api.ask_service import AskPipeline

        pipeline = AskPipeline(self.index, self.llm, self.verifier)
        route = decision.route
        degraded = False
        answer = ""
        sources: list[Source] = []
        confidence = 0.0
        abstained = False
        result = None
        cost = decision.estimated_cost

        if route == Route.cache and decision.cache_hit is not None:
            hit = decision.cache_hit
            answer = hit.answer
            sources = [Source(**s) for s in hit.sources if isinstance(s, dict)]
            confidence = hit.confidence
        elif not execute_answer:
            pass
        elif route == Route.cloud_api:
            call = self.monitor.cloud.call() if self.monitor is not None else None
            if call is not None and not call.ok:
                # The simulated cloud failed -> degrade to the extractive path.
                route = Route.offline_fallback
                degraded = True
                result = pipeline.answer(
                    query, user_id=user_id, role=role, request_id=request_id,
                    force_extractive=True,
                )
            else:
                # No real network exists, so the answer is still produced locally;
                # the cloud call only books quota, latency and cost.
                result = pipeline.answer(
                    query, user_id=user_id, role=role, request_id=request_id
                )
                if call is not None:
                    cost = call.cost_inr
        elif route == Route.offline_fallback:
            degraded = True
            result = pipeline.answer(
                query, user_id=user_id, role=role, request_id=request_id,
                force_extractive=True,
            )
        else:
            result = pipeline.answer(query, user_id=user_id, role=role, request_id=request_id)

        if result is not None:
            answer = result.answer
            sources = result.sources
            confidence = result.confidence
            abstained = result.abstained
            degraded = degraded or result.degraded

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        self.observe_latency(route, latency_ms)
        self._persist(request_id, query, decision, latency_ms, cost)

        return RouteExecution(
            decision=decision,
            request_id=request_id,
            route=route,
            answer=answer,
            sources=sources,
            confidence=confidence,
            abstained=abstained,
            degraded=degraded,
            latency_ms=latency_ms,
            estimated_cost=cost,
            trace_id=getattr(result, "request_id", None),
            pipeline_result=result,
        )

    # ------------------------------------------------------------------
    # Persistence + reporting
    # ------------------------------------------------------------------

    def _persist(
        self, request_id: str, query: str, decision: RoutingDecision, latency_ms: float, cost: float
    ) -> None:
        snapshot = decision.snapshot
        try:
            execute(
                """
                INSERT INTO router_decisions
                    (request_id, query, routed_to, reasoning, complexity, intent,
                     features_json, latency_ms, estimated_cost, always_cloud_cost,
                     oracle_route, ram_available_mb, cpu_load_pct, bandwidth_kbps,
                     api_quota_remaining, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    query,
                    decision.route.value,
                    decision.reasoning,
                    decision.complexity.value,
                    decision.intent.value,
                    json.dumps(decision.features),
                    latency_ms,
                    cost,
                    decision.always_cloud_cost,
                    decision.oracle_route.value,
                    getattr(snapshot, "ram_available_mb", None),
                    getattr(snapshot, "cpu_load_pct", None),
                    getattr(snapshot, "bandwidth_kbps", None),
                    getattr(snapshot, "api_quota_remaining", None),
                    _now(),
                ),
            )
        except Exception as exc:  # pragma: no cover - logging must not fail a request
            log.warning("could not persist router decision: %s", exc)

    def decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        return query(
            "SELECT * FROM router_decisions ORDER BY id DESC LIMIT ?", (int(limit),)
        )

    def routing_agreement(self, limit: int = 500) -> float | None:
        rows = query(
            "SELECT routed_to, oracle_route FROM router_decisions ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        if not rows:
            return None
        agree = sum(1 for r in rows if r["routed_to"] == r["oracle_route"])
        return round(agree / len(rows), 4)

    def status_detail(self) -> str:
        cls = self.classifier.status_detail()
        return f"router ready; {cls}; routes {self._latency}"

    # ------------------------------------------------------------------
    # Scenario simulator
    # ------------------------------------------------------------------

    def simulate(
        self,
        scenario: str = "stable",
        steps: int = 8,
        query_text: str = "What is the attendance policy?",
        reset: bool = True,
    ) -> list[dict[str, Any]]:
        """Replay a resource scenario and return one row per step.

        Each row is what the router would decide under that resource state, with
        the values that drove it, so the dashboard can show decisions change live.
        """
        if self.monitor is None:  # pragma: no cover - monitor always present
            return []
        steps = max(1, min(int(steps), 40))
        monitor = self.monitor
        bandwidth_scenarios = set(monitor.bandwidth.scenarios)
        is_bandwidth = scenario in bandwidth_scenarios

        original_floor = settings.ram_floor_mb
        rows: list[dict[str, Any]] = []
        try:
            if reset:
                monitor.cloud.reset()
                self._force_offline = False
            if is_bandwidth:
                monitor.bandwidth.set_scenario(scenario)
            if scenario == "ram_crash":
                # Pretend almost no RAM is available for the whole replay.
                settings.ram_floor_mb = 1 << 62
            if scenario == "quota_exhausted":
                monitor.cloud.calls_made = monitor.cloud.quota_per_day
            if scenario == "ollama_crash":
                self._force_offline = True

            for _ in range(steps):
                snapshot = monitor.step() if is_bandwidth else monitor.sample(force=True)
                decision = self.decide(query_text)
                rows.append(
                    {
                        "step": len(rows) + 1,
                        "scenario": scenario,
                        "routed_to": decision.route.value,
                        "oracle_route": decision.oracle_route.value,
                        "reasoning": decision.reasoning,
                        "ram_available_mb": snapshot.ram_available_mb,
                        "cpu_load_pct": snapshot.cpu_load_pct,
                        "bandwidth_kbps": snapshot.bandwidth_kbps,
                        "api_quota_remaining": snapshot.api_quota_remaining,
                        "estimated_cost": decision.estimated_cost,
                        "always_cloud_cost": decision.always_cloud_cost,
                    }
                )
        finally:
            settings.ram_floor_mb = original_floor
            self._force_offline = False
            if is_bandwidth:
                monitor.bandwidth.set_scenario("stable")
        return rows

    def simulate_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["routed_to"]] = counts.get(row["routed_to"], 0) + 1
        cost = sum(float(r["estimated_cost"]) for r in rows)
        baseline = sum(float(r["always_cloud_cost"]) for r in rows)
        return {
            "steps": len(rows),
            "routes": counts,
            "cumulative_cost_inr": round(cost, 4),
            "always_cloud_cost_inr": round(baseline, 4),
            "savings_inr": round(baseline - cost, 4),
            "savings_pct": round((baseline - cost) / baseline * 100.0, 2) if baseline else 0.0,
        }

    def to_response(self, execution: RouteExecution) -> RouteResponse:
        return RouteResponse(
            request_id=execution.request_id,
            routed_to=execution.route,
            reasoning=execution.decision.reasoning,
            latency_ms=execution.latency_ms,
            estimated_cost=execution.estimated_cost,
            answer=execution.answer or None,
            sources=execution.sources,
            confidence=execution.confidence if execution.answer else None,
            complexity=execution.decision.complexity,
            degraded=execution.degraded,
            resource_snapshot=(
                self.monitor.status(self.llm) if self.monitor is not None else None
            ),
        )
