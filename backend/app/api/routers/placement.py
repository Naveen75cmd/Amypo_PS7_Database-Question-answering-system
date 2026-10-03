"""Placement eligibility, matching, skill gaps and what-if simulation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.schemas import (
    EligibilityQuery,
    EligibilityResponse,
    MatchRequest,
    MatchResponse,
    SkillGapResponse,
    WhatIfRequest,
    WhatIfResponse,
)

router = APIRouter(tags=["placement"])


@router.get(
    "/placement/eligibility",
    response_model=EligibilityResponse,
    summary="Deterministic per-criterion eligibility for a student or role",
)
def eligibility(
    student_id: str | None = None,
    company: str | None = None,
    role: str | None = None,
    role_id: int | None = None,
) -> EligibilityResponse:
    raise HTTPException(status_code=503, detail="Placement available after Phase 6.")


@router.post(
    "/placement/match",
    response_model=MatchResponse,
    summary="Rank eligible candidates for a role with the reasons why",
)
def match(payload: MatchRequest) -> MatchResponse:
    raise HTTPException(status_code=503, detail="Placement available after Phase 6.")


@router.get(
    "/placement/skill-gap/{student_id}",
    response_model=SkillGapResponse,
    summary="Missing skills and an ordered learning path for a target role",
)
def skill_gap(student_id: str, company: str | None = None, role: str | None = None) -> SkillGapResponse:
    raise HTTPException(status_code=503, detail="Placement available after Phase 6.")


@router.post(
    "/placement/what-if",
    response_model=WhatIfResponse,
    summary="Recompute eligibility with overrides, without persisting them",
)
def what_if(payload: WhatIfRequest) -> WhatIfResponse:
    raise HTTPException(status_code=503, detail="Placement available after Phase 6.")
