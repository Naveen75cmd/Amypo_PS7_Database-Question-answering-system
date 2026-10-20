"""Full Phase 9 evaluation: benchmark + ablations + sweeps + load test.

Writes ``docs/eval/report.json`` and ``docs/eval/report.html`` (self-contained,
no template engine) and prints a headline summary to the terminal.

Usage:
    python scripts/evaluate.py                # full run, writes the report
    python scripts/evaluate.py --limit 40     # quick stratified run
    python scripts/evaluate.py --no-load-test # skip the 20-user load test
    python scripts/evaluate.py --kinds policy numeric   # only these kinds

This is what ``make eval`` runs.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "mysql", "host.docker.internal"}


def _guard_outbound_sockets() -> None:
    """Fail the run if anything tries to leave the machine (Phase 10, item 10).

    The submission claims there is no third-party API call. The test suite proves
    it for the tests; this proves it for the evaluation run, which is the other
    long path that touches retrieval, generation and the router. Loopback stays
    allowed because MySQL and Ollama live there by design.
    """
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def guard_connect(self, address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in _LOOPBACK:
            raise AssertionError(f"evaluation attempted an outbound call to {host!r}")
        return real_connect(self, address, *args, **kwargs)

    def guard_create(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in _LOOPBACK:
            raise AssertionError(f"evaluation attempted an outbound call to {host!r}")
        return real_create(address, *args, **kwargs)

    socket.socket.connect = guard_connect  # type: ignore[assignment]
    socket.create_connection = guard_create  # type: ignore[assignment]


from app.eval.harness import EvalOptions, run_harness  # noqa: E402


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _pctv(value: float | None) -> str:
    """Percent-unit values (e.g. savings_pct) are printed as-is."""
    return "-" if value is None else f"{value:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AMYPO evaluation harness")
    parser.add_argument("--limit", type=int, default=None, help="sample N items (stratified)")
    parser.add_argument("--kinds", nargs="*", default=None, help="restrict to these kinds")
    parser.add_argument(
        "--no-load-test", action="store_true", help="skip the 20-user load test"
    )
    parser.add_argument(
        "--no-report", action="store_true", help="print metrics without writing files"
    )
    parser.add_argument(
        "--no-access-control",
        action="store_true",
        help="skip the Phase 9 access-control red-team suite (its leak count "
             "otherwise appears in the report)",
    )
    args = parser.parse_args()

    _guard_outbound_sockets()

    options = EvalOptions(
        limit=args.limit,
        kinds=args.kinds,
        force_extractive=True,
        include_scenarios=True,
        include_sweeps=True,
        include_load_test=not args.no_load_test,
        include_access_control=not args.no_access_control,
        write_report=not args.no_report,
    )
    started = time.perf_counter()
    report = run_harness(options)
    elapsed = time.perf_counter() - started

    headline = report["headline"]
    answers = report["answers"]
    print()
    print(f"AMYPO evaluation - {report['scope']} (run {report['run_id']})")
    print("-" * 72)
    print(
        f"items {answers['total']}  answered {answers['answered']}  "
        f"abstained {answers['abstained_answerable'] + answers['unanswerable_abstained']}"
    )
    print(
        f"accuracy {_pct(headline['accuracy'])}  groundedness {_pct(headline['groundedness'])}  "
        f"hallucination {_pct(headline['hallucination_rate'])}  "
        f"abstention(unans) {_pct(headline['abstention_unanswerable'])}"
    )
    print(
        f"retrieval MRR {headline['retrieval_mrr']:.3f}  "
        f"S@1 {_pct(headline['retrieval_success_at_1'])}  "
        f"citation validity {report['citation_validity'].get('validity')}"
    )
    routing = report["routing"]
    print(
        f"routing agreement {_pct(headline['routing_agreement'])}  "
        f"cost {routing['cumulative_cost_inr']:.4f} vs "
        f"{routing['always_cloud_cost_inr']:.4f} INR "
        f"(saves {_pctv(headline['cost_savings_pct'])})"
    )
    print(
        f"peak RSS {headline['peak_ram_mb']:.0f} MB / 8192 MB  "
        f"scenarios {headline['scenarios_passed']}/{headline['scenarios_total']} passed"
    )
    load = report["load_test"]
    if load.get("ran"):
        print(
            f"load: {load['completed']}/{load['requests']} ok, "
            f"{load['throughput_rps']} rps, p50 {load['p50_ms']} ms, "
            f"p95 {load['p95_ms']} ms, graceful={load['graceful']}"
        )
    else:
        print(f"load: {load.get('reason', 'skipped')}")
    access = report.get("access_control") or {}
    if access.get("ran"):
        print(
            f"access control: {access['leaks']} leaks / {access['cases']} cases "
            f"({access['prompts']} prompts, {access['requests']} requests; "
            f"{access['prompts_answered']} answered, "
            f"{access['inconclusive_count']} inconclusive, "
            f"{access['skipped_count']} not run) "
            f"- {'pass' if access['passed'] else 'FAIL'}"
        )
    else:
        print(f"access control: {access.get('reason', 'skipped')}")
    failures = report["failure_analysis"]
    print(f"failures analysed: {len(failures)}")
    if report.get("report_html"):
        print(f"report: {report['report_html']}")
        print(f"        {report['report_json']}")
    print(f"wall: {elapsed:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
