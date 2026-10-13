"""Pydantic v2 models for the HTTP contract.

This module is the single source of truth for request/response shapes. The four
mandatory endpoints keep exactly the field names from the PS7/PS1 statement;
extra fields are additive and documented in ``openapi.yaml``.
``tests/test_contract.py`` asserts the mandatory fields are still present.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class Route(str, Enum):
    """The four PS1 execution paths plus the pure-SQL short circuit."""

    cache = "cache"
    local_model = "local_model"
    offline_fallback = "offline_fallback"
    cloud_api = "cloud_api"


class Intent(str, Enum):
    policy_lookup = "policy_lookup"
    personal_record = "personal_record"
    aggregate_stat = "aggregate_stat"
    placement_eligibility = "placement_eligibility"
    skill_gap = "skill_gap"
    candidate_recommendation = "candidate_recommendation"
    general = "general"


class Complexity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Role(str, Enum):
    student = "student"
    staff = "staff"


# --------------------------------------------------------------------------
# Shared primitives
# --------------------------------------------------------------------------


class Source(BaseModel):
    """A citation. ``record_id`` is the stable id from the ingestion layer."""

    record_id: str = Field(description="e.g. doc:attendance-policy#3 or db:students:S102")
    snippet: str = Field(max_length=400, description="Verbatim supporting text (<=240 chars)")


class Criterion(BaseModel):
    """One deterministic eligibility check. No black box."""

    name: str
    required: Any
    actual: Any
    passed: bool
    gap: str | None = None


# --------------------------------------------------------------------------
# Mandatory endpoints
# --------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    user_id: str | None = Field(default=None, description="e.g. S102; drives access scope")
    role: Role = Role.student
    top_k: int | None = None
    complexity_hint: Complexity | None = None


class ConflictPayload(BaseModel):
    """Two retrieved records disagree; the newer one won (Phase 8, item 6)."""

    model_config = ConfigDict(extra="forbid")

    newer_title: str
    superseded_title: str
    # Source numbers ([S1], [S2] ...) the two records carry in the answer, so
    # the UI can point at the passages instead of only naming their titles.
    newer_index: int = 0
    superseded_index: int = 0
    winner_value: str = ""
    loser_value: str = ""
    reason: str = ""


class CohortQuery(BaseModel):
    """One audited query that ranged over many students' records (item 7)."""

    model_config = ConfigDict(extra="ignore")

    id: int
    kind: str
    query: str
    company: str | None = None
    role_title: str | None = None
    role_id: int | None = None
    department: str | None = None
    user_id: str | None = None
    role: str = "staff"
    result_count: int = 0
    created_at: str | None = None


class ClosestRecord(BaseModel):
    """The nearest record when we could not answer (Phase 8, item 3).

    An abstention that only says "not found" leaves the user with nowhere to go;
    naming what *was* retrieved lets them see whether the question was misread,
    and gives them something to correct.
    """

    model_config = ConfigDict(extra="forbid")

    index: int = Field(description="Source number in the answer ([S1], [S2] ...)")
    record_id: str
    title: str = ""
    snippet: str = ""


class CarbonEstimate(BaseModel):
    """Rough energy/cost of this query vs always-cloud (Phase 8, item 9)."""

    model_config = ConfigDict(extra="forbid")

    kwh: float
    inr: float
    source: str = "estimate"


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    sources: list[Source]
    confidence: float = Field(ge=0.0, le=1.0)
    # --- additive, documented in openapi.yaml ---------------------------
    route: Route | None = None
    trace_id: str | None = None
    degraded: bool = False
    abstained: bool = False
    latency_ms: float | None = None
    estimated_cost: float | None = Field(default=None, description="INR")
    # --- Phase 8 add-ons -----------------------------------------------
    # Shown alongside an abstention so the user can narrow the question.
    clarifying_question: str | None = None
    # What retrieval found even though nothing grounded an answer.
    closest_records: list[ClosestRecord] = Field(default_factory=list)
    # Set only when two retrieved records genuinely disagree.
    conflict: ConflictPayload | None = None
    # Energy/cost estimate for the route this answer took.
    carbon: CarbonEstimate | None = None
    # Experimental: non-English input detected by script; answered in English.
    detected_language: str | None = None
    # Which local degradation tier produced the answer (primary/downgraded/
    # extractive), so the UI can show the visible "degraded" state.
    model_tier: str | None = None


class FeedbackRequest(BaseModel):
    """A thumbs rating for a previous answer (Phase 8, item 1)."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, description="The answer being rated")
    # +1 helpful, -1 not helpful. Written to query_log.feedback so the
    # classifier can be retrained from real signal rather than guesses.
    rating: int = Field(ge=-1, le=1)
    user_id: str | None = None


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    rating: int
    recorded: bool


class RetrainResponse(BaseModel):
    """Result of an on-demand classifier retrain, for the dashboard delta."""

    model_config = ConfigDict(extra="forbid")

    accuracy: float
    macro_f1: float
    samples: int
    # The headline number: what agreement was before vs after this retrain.
    previous_accuracy: float | None = None
    delta: float | None = None
    # How the number was produced, so the delta is auditable rather than magic:
    # every retrain is scored on the same fixed holdout, and the training set
    # grew by ``from_feedback`` rated questions (``confirmed`` thumbs-up,
    # ``corrected`` thumbs-down relabelled one step harder).
    holdout: int = 0
    from_feedback: int = 0
    confirmed: int = 0
    corrected: int = 0


class HealthComponent(BaseModel):
    status: Literal["ok", "degraded", "down", "not_loaded"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    components: dict[str, HealthComponent]
    versions: dict[str, str] = Field(default_factory=dict)


class RouteRequest(BaseModel):
    request_id: str | None = None
    query: str = Field(min_length=1)
    complexity_hint: Complexity | None = None
    user_id: str | None = None
    role: Role = Role.student
    execute: bool = Field(
        default=True,
        description="True: route then run the chosen path. False: decision only.",
    )


class RouteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    routed_to: Route
    reasoning: str
    latency_ms: float
    estimated_cost: float = Field(description="INR")
    # --- additive -------------------------------------------------------
    answer: str | None = None
    sources: list[Source] = Field(default_factory=list)
    confidence: float | None = None
    complexity: Complexity | None = None
    degraded: bool = False
    resource_snapshot: ResourceStatus | None = None


class ResourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ram_available_mb: int
    cpu_load_pct: float
    bandwidth_kbps: int
    api_quota_remaining: int
    # --- additive -------------------------------------------------------
    ollama_loaded: bool = False
    ollama_status: str = "unknown"
    ollama_last_latency_ms: float | None = None
    bandwidth_scenario: str = "stable"
    sampled_at: str | None = None


# --------------------------------------------------------------------------
# Trace
# --------------------------------------------------------------------------


class TraceStep(BaseModel):
    """One real pipeline stage. The UI renders these; it never fakes them."""

    id: str
    title: str
    status: Literal["done", "active", "pending", "failed"]
    detail: str | None = None
    items: list[str] = Field(default_factory=list)
    duration_ms: float | None = None
    started_at: str | None = None


class TraceClaim(BaseModel):
    text: str
    supported: bool
    score: float
    evidence_record_id: str | None = None
    evidence_snippet: str | None = None
    reason: str | None = None


class TraceResponse(BaseModel):
    request_id: str
    question: str
    answer: str | None = None
    route: Route | None = None
    confidence: float | None = None
    abstained: bool = False
    degraded: bool = False
    intent: Intent | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    complexity: Complexity | None = None
    steps: list[TraceStep] = Field(default_factory=list)
    claims: list[TraceClaim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    retrieval: list[dict[str, Any]] = Field(default_factory=list)
    reasoning: str | None = None
    created_at: str | None = None


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------


class IngestRequest(BaseModel):
    path: str | None = Field(default=None, description="Defaults to data/raw")
    force: bool = Field(default=False, description="Re-index even if hashes match")


class IngestResponse(BaseModel):
    documents: int
    chunks: int
    records: int
    skipped_unchanged: int
    duration_ms: float
    errors: list[str] = Field(default_factory=list)
    # Phase 8 item 5: historical questions warmed into the semantic cache.
    warmed: int = 0


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------


class EligibilityQuery(BaseModel):
    student_id: str | None = None
    company: str | None = None
    role: str | None = None
    role_id: int | None = None


class EligibilityResult(BaseModel):
    student_id: str
    student_name: str
    company: str
    role: str
    role_id: int
    eligible: bool
    criteria: list[Criterion]
    failing: list[str] = Field(default_factory=list)
    suitability: float | None = None
    factors: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class EligibilityResponse(BaseModel):
    results: list[EligibilityResult]
    total: int


class MatchRequest(BaseModel):
    role_id: int | None = None
    company: str | None = None
    role: str | None = None
    top_n: int = 5
    department: str | None = None


class MatchResponse(BaseModel):
    company: str
    role: str
    role_id: int
    weights: dict[str, float]
    candidates: list[EligibilityResult]
    closest_misses: list[EligibilityResult]
    sources: list[Source] = Field(default_factory=list)


class SkillGapItem(BaseModel):
    skill: str
    skill_id: str | None = None
    category: str
    current_level: int
    required_level: int
    severity: Literal["blocking", "weak", "ok"]
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class LearningStep(BaseModel):
    order: int
    title: str
    kind: Literal["module", "skill", "tool"]
    effort_weeks: float
    record_id: str | None = None
    snippet: str | None = None


class SkillGapResponse(BaseModel):
    student_id: str
    student_name: str
    target_role: str | None
    company: str | None
    gaps: list[SkillGapItem]
    learning_path: list[LearningStep]
    sources: list[Source] = Field(default_factory=list)


class WhatIfRequest(BaseModel):
    student_id: str
    cgpa: float | None = None
    attendance_pct: float | None = None
    backlogs: int | None = None
    communication_score: float | None = None
    project_count: int | None = None
    skill_levels: dict[str, int] = Field(default_factory=dict)


class WhatIfResponse(BaseModel):
    student_id: str
    baseline_eligible: list[str]
    projected_eligible: list[str]
    opened_up: list[str]
    lost: list[str]
    per_role: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Monitoring / router introspection
# --------------------------------------------------------------------------


class RouterDecision(BaseModel):
    request_id: str
    query: str
    routed_to: Route
    reasoning: str
    complexity: Complexity | None = None
    intent: Intent | None = None
    latency_ms: float
    estimated_cost: float
    always_cloud_cost: float
    ram_available_mb: int | None = None
    bandwidth_kbps: int | None = None
    api_quota_remaining: int | None = None
    created_at: str | None = None


class DecisionsResponse(BaseModel):
    decisions: list[RouterDecision]
    total: int


class MetricsResponse(BaseModel):
    total_requests: int
    cache_hit_rate: float
    requests_by_route: dict[str, int]
    latency_p50_ms: dict[str, float]
    latency_p95_ms: dict[str, float]
    cumulative_cost_inr: float
    always_cloud_cost_inr: float
    savings_inr: float
    savings_pct: float
    abstention_rate: float
    avg_confidence: float
    groundedness_avg: float
    routing_agreement: float | None = None
    resource_series: list[dict[str, Any]] = Field(default_factory=list)


class SimulateRequest(BaseModel):
    scenario: Literal[
        "stable", "ram_crash", "bandwidth_degrading", "bandwidth_flapping",
        "quota_exhausted", "ollama_crash", "offline", "recovery",
    ] = "stable"
    steps: int = 8
    query: str = "What is the attendance policy?"
    reset: bool = True


class SimulateResponse(BaseModel):
    scenario: str
    steps: list[dict[str, Any]]
    summary: dict[str, Any]


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


class EvalRunRequest(BaseModel):
    limit: int | None = None
    kinds: list[str] | None = None
    write_report: bool = True


class EvalRunResponse(BaseModel):
    run_id: str
    total: int
    accuracy: float
    groundedness: float
    hallucination_rate: float
    abstention_rate_unanswerable: float
    precision_at_1: float
    precision_at_3: float
    precision_at_5: float
    recall_at_k: float
    mrr: float
    routing_agreement: float | None = None
    cumulative_cost_inr: float
    always_cloud_cost_inr: float
    savings_pct: float
    latency_p50_ms: float
    latency_p95_ms: float
    peak_ram_mb: float
    report_path: str | None = None
    per_kind: dict[str, Any] = Field(default_factory=dict)


# Resolve the forward reference in RouteResponse.
RouteResponse.model_rebuild()
