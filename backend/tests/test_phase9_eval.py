"""Phase 9: the evaluation harness, its report, and the /eval/run endpoint.

The harness runs the real pipeline (never a mock), so the smoke run is
module-scoped: one shared run keeps the suite fast while every assertion still
checks the actual artefacts ``make eval`` produces.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

NEEDED_KEYS = {
    "run_id",
    "generated_at",
    "scope",
    "config",
    "methodology",
    "answers",
    "per_item",
    "citation_validity",
    "retrieval",
    "routing",
    "ablations",
    "scenarios",
    "sweeps",
    "load_test",
    "failure_analysis",
    "resources",
    "headline",
}


@pytest.fixture(scope="module")
def report() -> dict:
    """One small, real harness run shared by the assertions below."""
    corpus = PROJECT_ROOT / "data" / "raw" / "attendance-policy.md"
    if not corpus.exists():
        pytest.skip("run scripts/generate_data.py then python -m app.ingest first")
    from app.eval.harness import EvalOptions, run_harness

    return run_harness(
        EvalOptions(
            limit=8,
            include_scenarios=True,
            include_sweeps=True,
            include_load_test=False,
            write_report=False,
        )
    )


def test_harness_produces_every_report_block(report) -> None:
    assert NEEDED_KEYS <= set(report), sorted(NEEDED_KEYS - set(report))
    answers = report["answers"]
    assert answers["total"] == 8
    assert 0.0 <= answers["accuracy"] <= 1.0
    assert 0.0 <= answers["groundedness"] <= 1.0
    # Every answerable item scored exactly once, and per-kind buckets sum to n.
    buckets = answers["per_kind"]
    assert sum(b["n"] for b in buckets.values()) == answers["total"]
    # Retrieval ablation: four modes, all four reported.
    assert {"dense", "bm25", "hybrid", "hybrid_rerank"} == set(report["retrieval"])
    assert report["retrieval"]["hybrid_rerank"]["mrr"] >= 0.0
    # Routing: agreement and the always-cloud cost baseline are present.
    routing = report["routing"]
    assert routing["questions"] == 8
    assert routing["always_cloud_cost_inr"] > 0
    assert routing["cumulative_cost_inr"] <= routing["always_cloud_cost_inr"]
    # Peak RAM is measured (psutil), not guessed, and must respect the budget.
    assert report["resources"]["peak_rss_mb"] > 0
    assert report["resources"]["within_budget"] is True
    # Methodology must document how each headline number was derived.
    assert "accuracy" in report["methodology"]
    assert "hallucination_rate" in report["methodology"]


def test_scenario_suite_passes(report) -> None:
    """RAM crash, Ollama down, quota, offline and bandwidth all behave."""
    scenarios = report["scenarios"]
    names = [s["scenario"] for s in scenarios]
    assert names == [
        "stable",
        "ram_crash",
        "ollama_crash",
        "quota_exhausted",
        "offline",
        "bandwidth_degrading",
    ]
    failed = [s for s in scenarios if not s["passed"]]
    assert not failed, [f"{s['scenario']}: {s['detail']}" for s in failed]


def test_threshold_sweeps_carry_the_chosen_operating_point(report) -> None:
    sweeps = report["sweeps"]
    verifier = sweeps["verifier_threshold"]
    assert [p["threshold"] for p in verifier["points"]] == [
        0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80,
    ]
    assert verifier["chosen_point"] is not None, "current config must appear in the sweep"
    cache = sweeps["cache_cosine"]
    assert cache["points"] and cache["chosen"] == 0.92
    ram = sweeps["ram_floor"]
    assert {p["floor_mb"] for p in ram["points"]} == {512, 900, 1500, 2600, 4096}
    assert sum(1 for p in ram["points"] if p["is_current"]) == 1


def test_failure_analysis_lists_at_most_ten_worst(report) -> None:
    failures = report["failure_analysis"]
    assert len(failures) <= 10
    for failure in failures:
        assert failure["cause"] and failure["fix"], failure["id"]
        assert failure["kind_of"] in {"wrong", "hallucination"}


def test_to_eval_response_matches_the_api_schema(report) -> None:
    from app.core.schemas import EvalRunResponse
    from app.eval.harness import to_eval_response

    payload = to_eval_response(report)
    assert set(payload) == set(EvalRunResponse.model_fields), (
        sorted(set(EvalRunResponse.model_fields) - set(payload)),
        sorted(set(payload) - set(EvalRunResponse.model_fields)),
    )
    response = EvalRunResponse(**payload)
    assert response.total == 8
    assert response.report_path is None  # this run did not write files
    assert 0.0 <= response.accuracy <= 1.0


def test_write_report_writes_json_and_standalone_html(report, tmp_path, monkeypatch) -> None:
    from app.core.settings import settings
    from app.eval.report import write_report

    monkeypatch.setattr(settings, "docs_dir", tmp_path)
    json_path, html_path = write_report(report)

    assert json_path == tmp_path / "eval" / "report.json"
    assert html_path == tmp_path / "eval" / "report.html"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["run_id"] == report["run_id"]

    html_text = html_path.read_text(encoding="utf-8")
    assert html_text.startswith("<!doctype html>")
    # The sections a judge must find in the artefact.
    for marker in (
        "Headline",
        "Answers",
        "Ablations",
        "Threshold sweeps",
        "Resource scenarios",
        "Load test",
        "Failure analysis",
        "Methodology",
        report["run_id"],
    ):
        assert marker in html_text, marker
    # No external assets: the report must open offline from disk.
    assert "http://" not in html_text and "https://" not in html_text
    assert "<script" not in html_text


def test_eval_endpoint_returns_metrics(client, temp_db) -> None:
    """POST /api/v1/eval/run answers 200 with every EvalRunResponse field.

    The test schema has no corpus, so this proves the wiring (options ->
    harness -> response mapping), not quality numbers; the module-scoped run
    above covers those against the seeded database.
    """
    from app.core.schemas import EvalRunResponse

    resp = client.post(
        "/api/v1/eval/run", json={"limit": 4, "kinds": None, "write_report": False}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == set(EvalRunResponse.model_fields)
    assert body["run_id"]
    assert body["total"] >= 1
    assert body["peak_ram_mb"] > 0
    assert body["report_path"] is None


def test_eval_endpoint_rejects_an_empty_kind_filter(client, temp_db) -> None:
    resp = client.post(
        "/api/v1/eval/run", json={"limit": 4, "kinds": ["no-such-kind"], "write_report": False}
    )
    assert resp.status_code == 422, resp.text


def test_evaluate_script_is_the_make_eval_entry_point() -> None:
    """`make eval` runs scripts/evaluate.py; it must at least parse --help."""
    script = PROJECT_ROOT / "scripts" / "evaluate.py"
    assert script.exists(), "scripts/evaluate.py is the Phase 9 CLI entry point"
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "scripts/evaluate.py" in makefile
    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage" in proc.stdout.lower()
