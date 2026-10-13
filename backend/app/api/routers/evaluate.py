"""POST /api/v1/eval/run — benchmark the pipeline (Phase 9).

Runs the real harness in-process: the same ``run_harness`` that ``make eval``
uses, minus the load test (that belongs in the CLI, not behind an HTTP
request). The harness persists nothing, so an eval run does not pollute
query_log or router_decisions.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ...core.schemas import EvalRunRequest, EvalRunResponse

log = logging.getLogger(__name__)

router = APIRouter(tags=["eval"])


@router.post("/eval/run", response_model=EvalRunResponse, summary="Run the benchmark suite")
def run_eval(payload: EvalRunRequest) -> EvalRunResponse:
    from ...eval.harness import EvalOptions, run_harness, to_eval_response

    options = EvalOptions(
        limit=payload.limit,
        kinds=payload.kinds,
        force_extractive=True,  # reproducible without a pulled model
        include_scenarios=True,
        include_sweeps=True,
        include_load_test=False,  # `make eval` covers the 20-user load test
        write_report=payload.write_report,
    )
    try:
        report = run_harness(options)
    except ValueError as exc:  # empty benchmark / bad filter
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - surfaced to the UI
        log.exception("eval run failed")
        raise HTTPException(status_code=500, detail=f"eval run failed: {exc}") from exc
    return EvalRunResponse(**to_eval_response(report))
