"""Command-line report for the PS1 router.

Prints the three numbers the spec asks to see, from real runs rather than
claims:

* the complexity classifier's held-out accuracy / macro-F1,
* what the router actually cost versus an always-cloud policy (INR, savings),
* the router's agreement with the oracle labels.

Usage::

    cd backend
    python -m app.router                 # report everything
    python -m app.router --train         # retrain the classifier first
    python -m app.router --scenario ram_crash --steps 10
"""

from __future__ import annotations

import argparse

from .classifier import ComplexityClassifier

_SCENARIOS = (
    "stable",
    "bandwidth_degrading",
    "bandwidth_flapping",
    "offline",
    "quota_exhausted",
    "ram_crash",
    "ollama_crash",
)


def _print_classifier(classifier: ComplexityClassifier) -> None:
    print("Complexity classifier")
    print(f"  {classifier.status_detail()}")
    if classifier.report is not None:
        report = classifier.report
        per_class = ", ".join(
            f"{name} {value:.3f}" for name, value in sorted(report.per_class.items())
        )
        print(f"  per-class F1: {per_class}")


def _print_scenario(engine, scenario: str, steps: int) -> None:
    rows = engine.simulate(scenario=scenario, steps=steps)
    summary = engine.simulate_summary(rows)
    routes = ", ".join(f"{k}={v}" for k, v in sorted(summary["routes"].items()))
    print(
        f"  {scenario:<20} routes[{routes}] cost "
        f"INR {summary['cumulative_cost_inr']:.2f} vs always-cloud "
        f"INR {summary['always_cloud_cost_inr']:.2f} "
        f"(saved {summary['savings_pct']:.1f}%)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report PS1 router metrics.")
    parser.add_argument("--train", action="store_true", help="retrain the classifier first")
    parser.add_argument("--scenario", help="replay only this scenario")
    parser.add_argument("--steps", type=int, default=8, help="steps per scenario")
    args = parser.parse_args(argv)


    if args.train:
        print("Training complexity classifier ...")
        ComplexityClassifier.train(save=True)
        print("  saved artefact")

    from ..core.container import get_container

    engine = get_container().get("router")

    _print_classifier(engine.classifier)

    scenarios = (args.scenario,) if args.scenario else _SCENARIOS
    print("\nScenario replay (router vs always-cloud)")
    for scenario in scenarios:
        _print_scenario(engine, scenario, args.steps)

    agreement = engine.routing_agreement()
    if agreement is None:
        print("\nRouting agreement: no decisions recorded yet")
    else:
        print(f"\nRouting agreement vs oracle: {agreement * 100:.1f}%")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
