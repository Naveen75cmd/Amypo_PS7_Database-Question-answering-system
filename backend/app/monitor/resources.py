"""Resource monitoring: live RAM/CPU plus the simulated bandwidth and cloud.

The monitor is the router's eyes. It samples with ``psutil`` (smoothed with an
EWMA so a single spike does not flip the route), owns the bandwidth scenario
playback and the simulated-cloud quota, and persists samples so the dashboard and
the evaluation can show a real series rather than a made-up one.

Sampling is on demand with a short cache (``monitor_interval_s``); the API is
polled frequently but psutil is not hammered. A background loop is available via
``start_background`` for the dashboard, and it is stopped on shutdown.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..core.settings import settings
from ..db import execute
from .bandwidth import BandwidthSimulator
from .cloud import SimulatedCloud

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:  # pragma: no cover - psutil is a declared dependency
        return None


@dataclass
class ResourceSnapshot:
    ram_available_mb: int
    cpu_load_pct: float
    bandwidth_kbps: int
    api_quota_remaining: int
    bandwidth_scenario: str = "stable"
    sampled_at: str = field(default_factory=_now)

    def as_dict(self) -> dict:
        return {
            "ram_available_mb": self.ram_available_mb,
            "cpu_load_pct": self.cpu_load_pct,
            "bandwidth_kbps": self.bandwidth_kbps,
            "api_quota_remaining": self.api_quota_remaining,
            "bandwidth_scenario": self.bandwidth_scenario,
            "sampled_at": self.sampled_at,
        }


class ResourceMonitor:
    """Tracks the resource state the routing policy reads."""

    def __init__(
        self,
        bandwidth: BandwidthSimulator | None = None,
        cloud: SimulatedCloud | None = None,
        persist: bool = True,
    ) -> None:
        self.bandwidth = bandwidth or BandwidthSimulator()
        self.cloud = cloud or SimulatedCloud()
        self.persist_enabled = persist
        self._lock = threading.Lock()
        self._last: ResourceSnapshot | None = None
        self._last_at: float = 0.0
        self._ewma_ram: float | None = None
        self._ewma_cpu: float | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # --- sampling -------------------------------------------------------

    def _read_host(self) -> tuple[int, float]:
        psutil = _psutil()
        if psutil is None:  # pragma: no cover
            return settings.ram_comfort_mb, 0.0
        vm = psutil.virtual_memory()
        ram_mb = int(vm.available / (1024 * 1024))
        # interval=None is non-blocking: percent since the previous call.
        cpu = float(psutil.cpu_percent(interval=None))
        return ram_mb, cpu

    def sample(self, force: bool = False) -> ResourceSnapshot:
        """Return the current resource snapshot, cached for one interval."""
        now = time.perf_counter()
        with self._lock:
            if (
                not force
                and self._last is not None
                and (now - self._last_at) < settings.monitor_interval_s
            ):
                return self._last

            ram_mb, cpu = self._read_host()
            alpha = settings.ewma_alpha
            self._ewma_ram = ram_mb if self._ewma_ram is None else (
                alpha * ram_mb + (1 - alpha) * self._ewma_ram
            )
            self._ewma_cpu = cpu if self._ewma_cpu is None else (
                alpha * cpu + (1 - alpha) * self._ewma_cpu
            )

            snapshot = ResourceSnapshot(
                ram_available_mb=int(self._ewma_ram),
                cpu_load_pct=round(float(self._ewma_cpu), 2),
                bandwidth_kbps=self.bandwidth.current(),
                api_quota_remaining=self.cloud.remaining,
                bandwidth_scenario=self.bandwidth.scenario,
            )
            self._last = snapshot
            self._last_at = now

        if self.persist_enabled:
            self._persist(snapshot)
        return snapshot

    def _persist(self, snapshot: ResourceSnapshot) -> None:
        try:
            execute(
                """
                INSERT INTO resource_samples
                    (ram_available_mb, cpu_load_pct, bandwidth_kbps,
                     api_quota_remaining, ollama_status, scenario, sampled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.ram_available_mb,
                    snapshot.cpu_load_pct,
                    snapshot.bandwidth_kbps,
                    snapshot.api_quota_remaining,
                    None,
                    snapshot.bandwidth_scenario,
                    snapshot.sampled_at,
                ),
            )
        except Exception as exc:  # pragma: no cover - never fail a request over a sample
            log.debug("could not persist resource sample: %s", exc)

    # --- scenario control ----------------------------------------------

    def set_bandwidth_scenario(self, name: str) -> None:
        with self._lock:
            self.bandwidth.set_scenario(name)
        self.sample(force=True)

    def step(self) -> ResourceSnapshot:
        """Advance the bandwidth scenario one tick and re-sample."""
        with self._lock:
            self.bandwidth.step()
        return self.sample(force=True)

    def reset_cloud(self) -> None:
        self.cloud.reset()
        self.sample(force=True)

    # --- reporting ------------------------------------------------------

    def status(self, llm=None):
        """Build the ``ResourceStatus`` contract model, with optional Ollama state."""
        from ..core.schemas import ResourceStatus

        snap = self.sample()
        loaded = False
        ollama_status = "unknown"
        last_latency = None
        if llm is not None:
            ollama_status = llm.status()
            loaded = ollama_status == "ok"
            last_latency = llm.last_latency_ms
        return ResourceStatus(
            ram_available_mb=snap.ram_available_mb,
            cpu_load_pct=snap.cpu_load_pct,
            bandwidth_kbps=snap.bandwidth_kbps,
            api_quota_remaining=snap.api_quota_remaining,
            ollama_loaded=loaded,
            ollama_status=ollama_status,
            ollama_last_latency_ms=last_latency,
            bandwidth_scenario=snap.bandwidth_scenario,
            sampled_at=snap.sampled_at,
        )

    def status_detail(self) -> str:
        snap = self.sample()
        return (
            f"RAM {snap.ram_available_mb} MB, CPU {snap.cpu_load_pct}%, "
            f"bandwidth {snap.bandwidth_kbps} kbps ({snap.bandwidth_scenario}), "
            f"quota {snap.api_quota_remaining}"
        )

    # --- background loop ------------------------------------------------

    def start_background(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def run() -> None:
            while not self._stop.wait(settings.monitor_interval_s):
                try:
                    self.step()
                except Exception:  # pragma: no cover - a monitor must not crash the app
                    log.debug("monitor tick failed", exc_info=True)

        self._thread = threading.Thread(target=run, name="amypo-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
