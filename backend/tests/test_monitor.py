"""Phase 5: the resource monitor, bandwidth simulator and simulated cloud."""

from __future__ import annotations

from app.monitor.bandwidth import BandwidthSimulator, load_scenarios
from app.monitor.cloud import SimulatedCloud
from app.monitor.resources import ResourceMonitor


# --------------------------------------------------------------------------
# Bandwidth simulator
# --------------------------------------------------------------------------


def test_offline_scenario_reports_zero_and_is_not_available() -> None:
    sim = BandwidthSimulator(scenarios={"offline": [0, 0, 0]}, scenario="offline")
    assert sim.current() == 0
    assert not sim.available()


def test_degrading_scenario_is_monotonic_and_does_not_snap_back() -> None:
    sim = BandwidthSimulator(scenario="bandwidth_degrading")
    values = [sim.current()]
    for _ in range(len(sim.series) + 3):
        values.append(sim.step())
    # Non-increasing while replaying, then pinned to the final value.
    assert all(b <= a for a, b in zip(values, values[1:]))
    assert values[-1] == sim.series[-1]
    assert sim.available() is (sim.series[-1] > 0)


def test_unknown_scenario_is_refused() -> None:
    sim = BandwidthSimulator()
    try:
        sim.set_scenario("does-not-exist")
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("an unknown scenario must not be accepted")


def test_load_scenarios_always_includes_the_defaults() -> None:
    scenarios = load_scenarios()
    assert {"stable", "offline", "bandwidth_degrading", "bandwidth_flapping"} <= set(scenarios)


# --------------------------------------------------------------------------
# Simulated cloud
# --------------------------------------------------------------------------


def test_cloud_succeeds_when_failure_rate_is_zero() -> None:
    cloud = SimulatedCloud(quota_per_day=5, failure_rate=0.0)
    result = cloud.call()
    assert result.ok
    assert result.cost_inr == cloud.price_inr_per_call
    assert cloud.remaining == 4


def test_cloud_failures_are_deterministic() -> None:
    a = SimulatedCloud(quota_per_day=10, failure_rate=1.0)
    b = SimulatedCloud(quota_per_day=10, failure_rate=1.0)
    assert [a.call().ok for _ in range(4)] == [b.call().ok for _ in range(4)]
    assert a.failures == 4


def test_cloud_quota_is_enforced_and_reserve_is_respected() -> None:
    cloud = SimulatedCloud(quota_per_day=2, failure_rate=0.0)
    assert cloud.call().ok
    assert cloud.call().ok
    third = cloud.call()
    assert not third.ok
    assert "quota" in third.reason
    assert cloud.remaining == 0

    reserved = SimulatedCloud(quota_per_day=1, failure_rate=0.0)
    blocked = reserved.call(reserve=1)
    assert not blocked.ok
    assert reserved.calls_made == 0, "a reserved call must not consume quota"


def test_cloud_reset_restores_quota() -> None:
    cloud = SimulatedCloud(quota_per_day=1, failure_rate=0.0)
    cloud.call()
    assert cloud.exhausted()
    cloud.reset()
    assert not cloud.exhausted()
    assert cloud.remaining == 1


# --------------------------------------------------------------------------
# Resource monitor
# --------------------------------------------------------------------------


def test_monitor_sample_and_status() -> None:
    monitor = ResourceMonitor(persist=False)
    snapshot = monitor.sample(force=True)
    assert snapshot.ram_available_mb > 0
    assert snapshot.cpu_load_pct >= 0
    assert snapshot.bandwidth_kbps == 20000

    status = monitor.status()
    assert status.bandwidth_scenario == "stable"
    assert status.api_quota_remaining == 100
    assert status.sampled_at


def test_monitor_reflects_scenario_switches() -> None:
    monitor = ResourceMonitor(persist=False)
    monitor.set_bandwidth_scenario("offline")
    assert monitor.status().bandwidth_kbps == 0
    monitor.set_bandwidth_scenario("stable")
    assert monitor.status().bandwidth_kbps == 20000


def test_monitor_caches_within_the_sample_interval() -> None:
    monitor = ResourceMonitor(persist=False)
    first = monitor.sample(force=True)
    cached = monitor.sample()  # inside monitor_interval_s -> same snapshot
    assert cached is first
    forced = monitor.sample(force=True)
    assert forced is not first


# --------------------------------------------------------------------------
# Endpoint wiring
# --------------------------------------------------------------------------


def test_resource_status_endpoint(client) -> None:
    resp = client.get("/api/v1/resource-status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) >= {
        "ram_available_mb", "cpu_load_pct", "bandwidth_kbps", "api_quota_remaining",
    }
    assert body["ram_available_mb"] > 0
