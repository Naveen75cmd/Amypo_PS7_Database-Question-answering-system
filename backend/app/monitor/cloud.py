"""The simulated cloud API.

This is the object behind the ``cloud_api`` route, and the whole point is that it
is a *simulation*: a quota counter, a price table in INR, injected latency and
random failures — but no network call of any kind. ``CLOUD`` is local, so a test
that blocks outbound sockets still passes while ``cloud_api`` is exercised.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..core.settings import settings


@dataclass
class CloudCall:
    ok: bool
    latency_ms: float
    cost_inr: float
    reason: str = ""


@dataclass
class SimulatedCloud:
    """Quota-limited, priced, occasionally failing cloud stand-in.

    Determinism: failures come from a seeded ``random.Random`` so a scenario
    replay produces the same decisions every time (the demo and the tests depend
    on that).
    """

    quota_per_day: int = field(default_factory=lambda: settings.cloud_quota_per_day)
    price_inr_per_call: float = field(
        default_factory=lambda: settings.cloud_price_inr_per_call
    )
    latency_ms: int = field(default_factory=lambda: settings.cloud_latency_ms)
    failure_rate: float = field(default_factory=lambda: settings.cloud_failure_rate)
    seed: int = 1234

    calls_made: int = 0
    failures: int = 0
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    # --- quota ----------------------------------------------------------

    @property
    def remaining(self) -> int:
        return max(0, self.quota_per_day - self.calls_made)

    def exhausted(self) -> bool:
        return self.remaining <= 0

    # --- the (simulated) call ------------------------------------------

    def call(self, reserve: int = 0) -> CloudCall:
        """Consume one unit of quota and return the simulated outcome.

        ``reserve`` keeps a buffer of quota untouched, which the routing policy
        uses so a burst of "high complexity" questions cannot drain the day's
        quota in a few seconds.
        """
        if self.remaining <= reserve:
            return CloudCall(
                ok=False,
                latency_ms=0.0,
                cost_inr=0.0,
                reason=(
                    f"quota reserve reached ({self.remaining} left, reserve {reserve})"
                ),
            )

        self.calls_made += 1
        failed = self._rng.random() < self.failure_rate
        # Jitter so the latency column is not suspiciously constant.
        latency = float(self.latency_ms) * self._rng.uniform(0.75, 1.35)
        cost = self.price_inr_per_call
        if failed:
            self.failures += 1
            return CloudCall(
                ok=False,
                latency_ms=round(latency, 1),
                cost_inr=cost,
                reason="simulated upstream failure",
            )
        return CloudCall(ok=True, latency_ms=round(latency, 1), cost_inr=cost)

    def reset(self) -> None:
        self.calls_made = 0
        self.failures = 0
        self._rng = random.Random(self.seed)

    def stats(self) -> dict[str, float | int]:
        return {
            "calls_made": self.calls_made,
            "failures": self.failures,
            "remaining": self.remaining,
            "price_inr_per_call": self.price_inr_per_call,
        }
