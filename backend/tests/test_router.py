"""Phase 5 definition of done: the routing policy's scenario behaviour.

Fakes are used for the LLM and the classifier (so complexity is fixed per test);
the monitor and cloud are the real objects, and the cache is the real one against
a throwaway schema.

Host RAM is *pinned* rather than sampled. The routing policy is a function of
(complexity, RAM, bandwidth, quota), so reading the live machine made these tests
change verdict whenever a local model was resident — two gigabytes of Ollama is
enough to push available RAM below the 900 MB floor and route everything to the
offline fallback. RAM is an input here, so the tests supply it.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.cache.semantic_cache import SemanticCache
from app.core.schemas import Complexity, Route
from app.core.settings import settings
from app.monitor.bandwidth import BandwidthSimulator
from app.monitor.cloud import SimulatedCloud
from app.monitor.resources import ResourceMonitor
from app.router.engine import RouterEngine, cache_scope


class _FakeEmbedder:
    dim = 2

    def _vec(self, text: str) -> np.ndarray:
        return np.array([1.0, 0.0]) if "attendance" in text.lower() else np.array([0.0, 1.0])

    def encode_one(self, text: str) -> np.ndarray:
        return self._vec(text)

    def encode(self, texts, batch_size: int = 64) -> np.ndarray:
        return np.vstack([self._vec(t) for t in texts])


class _FakeIndex:
    def __init__(self) -> None:
        self.embedder = _FakeEmbedder()


class _FakeLLM:
    def __init__(self, healthy: bool = True) -> None:
        self._healthy = healthy
        self.last_latency_ms = None

    def healthy(self) -> bool:
        return self._healthy

    def status(self) -> str:
        return "ok" if self._healthy else "degraded"

    def status_detail(self) -> str:
        return "fake llm"


class _FixedClassifier:
    def __init__(self, complexity: Complexity) -> None:
        self.complexity = complexity

    def classify(self, question, hint=None):
        return self.complexity, 1.0, "fixed for test"

    def status_detail(self) -> str:
        return "fixed classifier"


def _engine(
    *,
    complexity: Complexity = Complexity.high,
    llm_healthy: bool = True,
    ram_floor_mb: int = 900,
    ram_mb: int = 4000,
    bandwidth: str = "stable",
    quota: int = 100,
    monkeypatch: pytest.MonkeyPatch | None = None,
    cache: SemanticCache | None = None,
    latency_budget_ms: int = 6000,
) -> RouterEngine:
    if monkeypatch is not None:
        monkeypatch.setattr(settings, "ram_floor_mb", ram_floor_mb, raising=False)
        monkeypatch.setattr(settings, "latency_budget_ms", latency_budget_ms, raising=False)
        # Pinned host reading: the EWMA seeds from the first sample, so the
        # decision sees exactly ``ram_mb`` no matter what is running locally.
        monkeypatch.setattr(
            ResourceMonitor, "_read_host", lambda self: (ram_mb, 5.0), raising=True
        )
    monitor = ResourceMonitor(
        bandwidth=BandwidthSimulator(scenario=bandwidth),
        cloud=SimulatedCloud(quota_per_day=quota, failure_rate=0.0),
        persist=False,
    )
    return RouterEngine(
        index=None,
        llm=_FakeLLM(llm_healthy),
        verifier=None,
        cache=cache,
        classifier=_FixedClassifier(complexity),
        monitor=monitor,
    )


# --------------------------------------------------------------------------
# Policy scenarios
# --------------------------------------------------------------------------


def test_ram_crash_falls_back_offline(monkeypatch) -> None:
    engine = _engine(ram_floor_mb=10**9, monkeypatch=monkeypatch)
    decision = engine.decide("What is my CGPA?", user_id="S102")
    assert decision.route == Route.offline_fallback
    assert decision.oracle_route == Route.offline_fallback
    assert "RAM" in decision.reasoning


def test_llm_unhealthy_falls_back_offline(monkeypatch) -> None:
    engine = _engine(llm_healthy=False, monkeypatch=monkeypatch)
    decision = engine.decide("What is the attendance policy?")
    assert decision.route == Route.offline_fallback


def test_structured_intent_stays_local_even_when_complex(monkeypatch) -> None:
    # Complexity is fixed "high", but a personal-record question is answered from
    # SQL templates, so no model is needed.
    engine = _engine(complexity=Complexity.high, monkeypatch=monkeypatch)
    decision = engine.decide("What is my CGPA?", user_id="S102")
    assert decision.structured
    assert decision.route == Route.local_model


def test_low_complexity_routes_local(monkeypatch) -> None:
    engine = _engine(complexity=Complexity.low, monkeypatch=monkeypatch)
    decision = engine.decide("What is my CGPA?", user_id="S102")
    assert decision.route == Route.local_model


def test_high_complexity_with_good_resources_routes_to_simulated_cloud(monkeypatch) -> None:
    # A tight latency budget makes the local model's predicted latency exceed it.
    engine = _engine(complexity=Complexity.high, monkeypatch=monkeypatch, latency_budget_ms=500)
    decision = engine.decide("Compare the exam and placement attendance rules")
    assert decision.route == Route.cloud_api
    assert decision.oracle_route == Route.cloud_api
    assert "cloud" in decision.reasoning.lower()


def test_quota_exhausted_never_routes_to_cloud(monkeypatch) -> None:
    engine = _engine(
        complexity=Complexity.high, quota=0, monkeypatch=monkeypatch, latency_budget_ms=500
    )
    decision = engine.decide("Compare the exam and placement attendance rules")
    assert decision.route == Route.local_model
    assert decision.oracle_route == Route.local_model


def test_offline_bandwidth_never_routes_to_cloud(monkeypatch) -> None:
    engine = _engine(
        complexity=Complexity.high, bandwidth="offline", monkeypatch=monkeypatch,
        latency_budget_ms=500,
    )
    decision = engine.decide("Compare the exam and placement attendance rules")
    assert decision.route == Route.local_model
    assert decision.features["bandwidth_kbps"] == 0


def test_repeated_question_hits_the_cache(temp_db, monkeypatch) -> None:
    cache = SemanticCache(_FakeIndex())
    cache.store("What is the attendance policy?", "75% attendance [S1]", [], 0.9, "public")
    engine = _engine(cache=cache, monkeypatch=monkeypatch)
    decision = engine.decide("What is the attendance policy?")
    assert decision.route == Route.cache
    assert decision.oracle_route == Route.cache
    assert decision.cache_hit is not None


def test_cache_is_not_shared_across_scopes(temp_db, monkeypatch) -> None:
    cache = SemanticCache(_FakeIndex())
    cache.store("What is the attendance policy?", "75%", [], 0.9, "staff")
    engine = _engine(cache=cache, monkeypatch=monkeypatch)
    # A student asking the same question must not receive the staff entry.
    decision = engine.decide("What is the attendance policy?", user_id="S102", role="student")
    assert decision.route != Route.cache


def test_cache_scope_helper() -> None:
    assert cache_scope(None, "staff") == "staff"
    assert cache_scope("S102", "student") == "student:S102"
    assert cache_scope(None, "student") == "public"


# --------------------------------------------------------------------------
# Execution + persistence
# --------------------------------------------------------------------------


def test_cache_route_executes_without_touching_the_pipeline(temp_db, monkeypatch) -> None:
    cache = SemanticCache(_FakeIndex())
    cache.store(
        "What is the attendance policy?",
        "75% attendance [S1]",
        [{"record_id": "doc:attendance-policy#0", "snippet": "75%"}],
        0.9,
        "public",
    )
    engine = _engine(cache=cache, monkeypatch=monkeypatch)
    execution = engine.run("req-cache-1", "What is the attendance policy?")
    assert execution.route == Route.cache
    assert execution.answer == "75% attendance [S1]"
    assert execution.estimated_cost == 0.0


def test_decisions_are_persisted_and_agreement_reported(temp_db, monkeypatch) -> None:
    cache = SemanticCache(_FakeIndex())
    cache.store("What is the attendance policy?", "75%", [], 0.9, "public")
    engine = _engine(cache=cache, monkeypatch=monkeypatch)
    engine.run("req-1", "What is the attendance policy?")
    rows = engine.decisions(limit=10)
    assert rows, "the decision must be written to router_decisions"
    assert rows[0]["routed_to"] == "cache"
    assert rows[0]["oracle_route"] == "cache"
    assert engine.routing_agreement() == 1.0


def test_always_cloud_baseline_is_a_positive_per_call_cost(monkeypatch) -> None:
    engine = _engine(complexity=Complexity.low, monkeypatch=monkeypatch)
    decision = engine.decide("What is my CGPA?", user_id="S102")
    assert decision.always_cloud_cost == settings.cloud_price_inr_per_call
    assert decision.estimated_cost < decision.always_cloud_cost
