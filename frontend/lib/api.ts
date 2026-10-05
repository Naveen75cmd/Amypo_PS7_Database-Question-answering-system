/**
 * Typed client for the AMYPO backend. Types mirror backend/app/core/schemas.py;
 * the Next.js rewrite in next.config.ts proxies /api/v1 to the backend, so the
 * browser never needs CORS.
 */

export type Role = "student" | "staff";

export interface Source {
  record_id: string;
  snippet: string;
}

export interface AskResponse {
  answer: string;
  sources: Source[];
  confidence: number;
  route: string | null;
  trace_id: string | null;
  degraded: boolean;
  abstained: boolean;
  latency_ms: number | null;
  estimated_cost: number | null;
}

export interface TraceStep {
  id: string;
  title: string;
  status: "done" | "active" | "pending" | "failed";
  detail: string | null;
  items: string[];
  duration_ms: number | null;
  started_at: string | null;
}

export interface TraceClaim {
  text: string;
  supported: boolean;
  score: number;
  reason: string | null;
  evidence_record_id: string | null;
  evidence_snippet: string | null;
}

export interface TraceResponse {
  request_id: string;
  question: string;
  answer: string | null;
  route: string | null;
  confidence: number | null;
  abstained: boolean;
  degraded: boolean;
  intent: string | null;
  entities: Record<string, unknown>;
  complexity: string | null;
  steps: TraceStep[];
  claims: TraceClaim[];
  sources: Source[];
  retrieval: Array<Record<string, unknown>>;
}

export interface ResourceStatus {
  ram_available_mb: number;
  cpu_load_pct: number;
  bandwidth_kbps: number;
  api_quota_remaining: number;
  ollama_loaded: boolean;
  ollama_status: string;
  ollama_last_latency_ms: number | null;
  bandwidth_scenario: string;
  sampled_at: string | null;
}

export interface MetricsResponse {
  total_requests: number;
  cache_hit_rate: number;
  requests_by_route: Record<string, number>;
  latency_p50_ms: Record<string, number>;
  latency_p95_ms: Record<string, number>;
  cumulative_cost_inr: number;
  always_cloud_cost_inr: number;
  savings_inr: number;
  savings_pct: number;
  abstention_rate: number;
  avg_confidence: number;
  groundedness_avg: number;
}

export interface RouterDecision {
  request_id: string;
  query: string;
  routed_to: string;
  reasoning: string | null;
  complexity: string | null;
  intent: string | null;
  latency_ms: number;
  estimated_cost: number;
  always_cloud_cost: number;
  ram_available_mb: number | null;
  bandwidth_kbps: number | null;
  api_quota_remaining: number | null;
  created_at: string | null;
}

export interface DecisionsResponse {
  decisions: RouterDecision[];
  total: number;
}

export interface SimulateStep {
  step: number;
  ram_available_mb: number;
  bandwidth_kbps: number;
  api_quota_remaining: number;
  routed_to: string;
  reason: string;
}

export interface SimulateResponse {
  scenario: string;
  steps: SimulateStep[];
  summary: string;
}

export interface PlacementRole {
  role_id: number;
  company: string;
  title: string;
  location: string | null;
  package_lpa: number | null;
  min_cgpa: number | null;
}

export interface Criterion {
  name: string;
  required: unknown;
  actual: unknown;
  passed: boolean;
  gap: string | null;
}

export interface EligibilityResult {
  student_id: string;
  student_name: string;
  company: string;
  role: string;
  role_id: number;
  eligible: boolean;
  criteria: Criterion[];
  failing: string[];
  suitability: number | null;
  factors: Array<{ name: string; value: number; weight: number; contribution: number }>;
  sources: Source[];
}

export interface MatchResponse {
  company: string;
  role: string;
  role_id: number;
  candidates: EligibilityResult[];
  closest_misses: EligibilityResult[];
  sources: Source[];
}

export interface SkillGapItem {
  skill: string;
  skill_id: string | null;
  category: string;
  current_level: number;
  required_level: number;
  severity: "blocking" | "weak" | "ok";
}

export interface LearningStep {
  order: number;
  title: string;
  kind: string;
  effort_weeks: number;
  record_id: string | null;
  snippet: string | null;
}

export interface SkillGapResponse {
  student_id: string;
  student_name: string;
  target_role: string | null;
  company: string | null;
  gaps: SkillGapItem[];
  learning_path: LearningStep[];
  sources: Source[];
}

export interface WhatIfResponse {
  student_id: string;
  baseline_eligible: string[];
  projected_eligible: string[];
  opened_up: string[];
  lost: string[];
  per_role: Array<{
    role: string;
    was_eligible: boolean;
    now_eligible: boolean;
    still_failing: Array<Record<string, unknown>>;
    suitability: number | null;
  }>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* status text is the best we have */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  ask: (payload: {
    question: string;
    user_id?: string | null;
    role: Role;
  }) =>
    request<AskResponse>("/ask", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  trace: (requestId: string) => request<TraceResponse>(`/ask/trace/${requestId}`),

  history: (params: { limit?: number; user_id?: string | null; requester_role: Role }) => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.user_id) qs.set("user_id", params.user_id);
    qs.set("requester_role", params.requester_role);
    return request<
      Array<{
        request_id: string;
        question: string;
        user_id: string | null;
        intent: string | null;
        confidence: number | null;
        abstained: boolean;
        created_at: string;
      }>
    >(`/ask/history?${qs.toString()}`);
  },

  documents: () =>
    request<
      Array<{
        doc_id: string;
        title: string;
        doc_type: string;
        access_scope: string;
        version: number;
        updated_at: string;
        indexed_at: string | null;
        chunk_count: number;
      }>
    >("/ingest/documents"),

  reingest: (force: boolean) =>
    request<{
      documents: number;
      chunks: number;
      records: number;
      skipped_unchanged: number;
      duration_ms: number;
      errors: string[];
    }>("/ingest", { method: "POST", body: JSON.stringify({ path: null, force }) }),

  runEval: (limit: number | null) =>
    request<{
      run_id: string;
      total: number;
      accuracy: number;
      groundedness: number;
      hallucination_rate: number;
      abstention_rate_unanswerable: number;
      precision_at_1: number;
      precision_at_3: number;
      precision_at_5: number;
      recall_at_k: number;
      mrr: number;
      routing_agreement: number | null;
      cumulative_cost_inr: number;
      always_cloud_cost_inr: number;
    }>("/eval/run", { method: "POST", body: JSON.stringify({ limit, write_report: true }) }),

  resourceStatus: () => request<ResourceStatus>("/resource-status"),

  metrics: () => request<MetricsResponse>("/metrics"),

  decisions: (limit = 50) =>
    request<DecisionsResponse>(`/router/decisions?limit=${limit}`),

  simulate: (payload: { scenario: string; steps?: number; query?: string; reset?: boolean }) =>
    request<SimulateResponse>("/simulate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  placementRoles: () => request<PlacementRole[]>("/placement/roles"),

  eligibility: (params: {
    student_id?: string;
    company?: string;
    role?: string;
    role_id?: number;
    user_id?: string | null;
    requester_role: Role;
  }) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    return request<{ results: EligibilityResult[]; total: number }>(
      `/placement/eligibility?${qs.toString()}`
    );
  },

  match: (payload: { company?: string; role?: string; role_id?: number; top_n?: number }) =>
    request<MatchResponse>("/placement/match", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  skillGap: (studentId: string, params: { company?: string; role?: string; user_id?: string | null; requester_role: Role }) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    return request<SkillGapResponse>(
      `/placement/skill-gap/${studentId}?${qs.toString()}`
    );
  },

  whatIf: (payload: {
    student_id: string;
    cgpa?: number | null;
    backlogs?: number | null;
    skill_levels?: Record<string, number>;
  }) =>
    request<WhatIfResponse>("/placement/what-if", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
