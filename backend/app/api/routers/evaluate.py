"""POST /api/v1/eval/run — benchmark the pipeline (Phase 9)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.schemas import EvalRunRequest, EvalRunResponse

router = APIRouter(tags=["eval"])


@router.post("/eval/run", response_model=EvalRunResponse, summary="Run the benchmark suite")
def run_eval(payload: EvalRunRequest) -> EvalRunResponse:
    raise HTTPException(status_code=503, detail="Evaluation available after Phase 9.")
