"""A bandwidth simulator that replays named scenarios.

The spec asks for scenarios (stable, degrading, flapping, offline) replayed from
``data/sim/bandwidth.json``. The file is produced by the data generator; the
built-in scenarios are the fallback so the router still has something to react
to if it is absent. Nothing here touches the network — bandwidth is a number the
demo controls, so resource adaptivity can be shown live.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..core.settings import settings

log = logging.getLogger(__name__)

# Named scenarios, in kbps. "offline" is genuinely zero, which the router must
# treat as "the cloud is unreachable", not "slow cloud".
DEFAULT_SCENARIOS: dict[str, list[int]] = {
    "stable": [20000] * 12,
    "bandwidth_degrading": [
        20000, 15000, 11000, 8000, 5000, 3000, 1800, 900, 400, 220, 120, 60,
    ],
    "bandwidth_flapping": [
        20000, 700, 18000, 500, 15000, 300, 12000, 200, 9000, 150, 8000, 100,
    ],
    "offline": [0] * 12,
    "recovery": [0, 0, 200, 800, 2000, 5000, 9000, 14000, 20000, 20000, 20000, 20000],
    "quota_exhausted": [20000] * 12,
}


def load_scenarios(path: Path | None = None) -> dict[str, list[int]]:
    """Built-in scenarios, overridden by ``data/sim/bandwidth.json`` when present."""
    scenarios = {name: list(values) for name, values in DEFAULT_SCENARIOS.items()}
    target = path or (settings.sim_dir / "bandwidth.json")
    if not target.exists():
        return scenarios
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - malformed generated file
        log.warning("could not read %s (%s); using built-in scenarios", target, exc)
        return scenarios
    raw = payload.get("scenarios", payload)
    for name, values in raw.items():
        if isinstance(values, list) and values and all(isinstance(v, int) for v in values):
            scenarios[name] = list(values)
    return scenarios


@dataclass
class BandwidthSimulator:
    """Holds the current scenario and the position within it.

    ``step()`` advances one tick; when the scenario ends it stays on the last
    value, so a "degrading" run does not silently snap back to full bandwidth.
    """

    scenarios: dict[str, list[int]] = field(default_factory=load_scenarios)
    scenario: str = "stable"
    index: int = 0

    def set_scenario(self, name: str) -> None:
        if name not in self.scenarios:
            raise KeyError(f"unknown bandwidth scenario: {name}")
        self.scenario = name
        self.index = 0

    @property
    def series(self) -> list[int]:
        series = self.scenarios.get(self.scenario)
        if series:
            return series
        # A caller may hand in a custom dict that lacks the named scenario (the
        # tests do). Fall back to any available series, never crash the monitor.
        if self.scenarios:
            return next(iter(self.scenarios.values()))
        return []

    def current(self) -> int:
        series = self.series
        if not series:
            return 0
        return int(series[min(self.index, len(series) - 1)])

    def step(self) -> int:
        self.index = min(self.index + 1, max(0, len(self.series) - 1))
        return self.current()

    def reset(self) -> None:
        self.index = 0

    def available(self) -> bool:
        """Whether any bandwidth exists. ``offline`` reports 0 and is not usable."""
        return self.current() > 0
