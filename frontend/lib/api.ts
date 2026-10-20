/**
 * Typed client for the AMYPO backend. Types mirror backend/app/core/schemas.py;
 * the Next.js rewrite in next.config.ts proxies /api/v1 to the backend, so the
 * browser never needs CORS.
 */

export type Role = "student" | "staff" | "admin" | "eval";

export interface UserOut {
  id: string;
  username: string;
  email: string;
  role: Role;
  student_id: string | null;
  department: string | null;
  cohort: string | null;
  is_active: boolean;
  created_at: string | null;
  last_login: string | null;
}

/** What the signed-in session may do. Presentation only — the backend enforces it. */
export interface Permissions {
  chat: boolean;
  own_records: boolean;
  staff_docs: boolean;
  admin_docs: boolean;
  placement_own: boolean;
  placement_cohort: boolean;
  placement_weights: boolean;
  criteria_edit: boolean;
  ingest: boolean;
  ingest_approve: boolean;
  user_admin: boolean;
  router_config: boolean;
  monitoring_full: boolean;
  monitoring_read: boolean;
  audit_log: boolean;
  eval_run: boolean;
  eval_view: boolean;
  simulator: boolean;
  service_account: boolean;
}

export interface MeResponse {
  user: UserOut;
  role: Role;
  cache_scope: string;
  student_id: string | null;
  departments: string[];
  cohorts: string[];
  assignments: Array<{ id: number; scope_kind: string; scope_value: string }>;
  permissions: Permissions;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserOut;
}

export interface AuditEntry {
  id: number;
  actor_id: string | null;
  actor_role: string | null;
  action: string;
  target: string | null;
  scope: string | null;
  ip: string | null;
  allowed: boolean;
  detail: string | null;
  created_at: string | null;
}

export interface AuditResponse {
  entries: AuditEntry[];
  total: number;
  summary: Record<string, number>;
}

export interface Source {
  record_id: string;
  snippet: string;
}

export interface CohortQuery {
  id: number;
  kind: string;
  query: string;
  company: string | null;
  role_title: string | null;
  department: string | null;
  user_id: string | null;
  role: string;
  result_count: number;
  created_at: string | null;
}

export interface ClosestRecord {
  index: number;
  record_id: string;
  title: string;
  snippet: string;
}

export interface ConflictPayload {
  newer_title: string;
  superseded_title: string;
  /** Source numbers the two records carry in the answer ([S1], [S3] ...). */
  newer_index: number;
  superseded_index: number;
  winner_value: string;
  loser_value: string;
  reason: string;
}

export interface CarbonEstimate {
  kwh: number;
  inr: number;
  source: string;
}

export type ModelTier = "primary" | "downgraded" | "extractive";

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
  // --- Phase 8 add-ons -------------------------------------------------
  /** Follow-up that narrows an abstained question (item 3). */
  clarifying_question: string | null;
  /** Nearest records found when the answer abstained (item 3). */
  closest_records: ClosestRecord[];
  /** Set when two retrieved records disagree (item 6). */
  conflict: ConflictPayload | null;
  /** Rough kWh/INR for this query (item 9). */
  carbon: CarbonEstimate | null;
  /** Non-English input detected by script; experimental (item 10). */
  detected_language: string | null;
  /** Which local degradation tier answered (item 4). */
  model_tier: ModelTier | null;
}

export interface FeedbackResponse {
  request_id: string;
  rating: number;
  recorded: boolean;
}

export interface RetrainResponse {
  accuracy: number;
  holdout: number;
  from_feedback: number;
  confirmed: number;
  corrected: number;
  macro_f1: number;
  samples: number;
  previous_accuracy: number | null;
  delta: number | null;
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
  /** ok | model_missing | degraded | unknown */
  ollama_status: string;
  ollama_detail: string | null;
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

export function apiBase(): string {
  return "/api/v1";
}

/**
 * Download a student's eligibility report.
 *
 * Deliberately not a plain <a href>: the access token lives fifteen minutes, and
 * a link cannot refresh it. A user who leaves the tab open and then clicks
 * Download would get a 401 page instead of a PDF. This mirrors request()'s
 * one-shot refresh, then turns the body into a client-side download.
 */
export async function downloadEligibilityPdf(studentId: string): Promise<void> {
  const path = `/placement/eligibility/${encodeURIComponent(studentId)}/report.pdf`;
  const send = () =>
    fetch(`/api/v1${path}`, { credentials: "include" });

  let res = await send();
  if (res.status === 401) {
    const refreshed = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "include",
    });
    if (refreshed.ok) res = await send();
  }
  if (!res.ok) throw new ApiError(res.status, res.statusText);

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${studentId}-eligibility.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/**
 * One fetch helper for the whole client.
 *
 * ``credentials: "include"`` is what carries the httpOnly session cookie; no
 * token is ever read from JavaScript. A 401 on a normal call is retried once
 * after hitting /auth/refresh, because the access token lives fifteen minutes
 * and an idle tab should not eject the user back to the login screen. The
 * refresh call itself is never retried.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const send = () =>
    fetch(`/api/v1${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...init,
    });

  let res = await send();
  if (res.status === 401 && !path.startsWith("/auth/")) {
    const refreshed = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "include",
    });
    if (refreshed.ok) res = await send();
  }

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
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  /** The four auth calls that are not "just another API resource". */
  login: (payload: { username: string; password: string }) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  logout: () => request<{ ok: boolean; revoked: boolean }>("/auth/logout", { method: "POST" }),

  me: () => request<MeResponse>("/auth/me"),

  ask: (payload: {
    question: string;
    /** Ignored by the server; the student scope comes from the session. */
    user_id?: string | null;
    /** Deprecated: the role comes from the session. */
    role?: Role;
  }) =>
    request<AskResponse>("/ask", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  trace: (requestId: string) => request<TraceResponse>(`/ask/trace/${requestId}`),

  /** Thumbs rating for a previous answer (Phase 8, item 1). */
  feedback: (payload: { request_id: string; rating: -1 | 0 | 1 }) =>
    request<FeedbackResponse>("/ask/feedback", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /** Staff cohort-query audit trail (item 7). Staff role only. */
  cohortQueries: (params: { limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    return request<CohortQuery[]>(`/placement/cohort-queries?${qs.toString()}`);
  },

  /** On-demand classifier retrain; returns the accuracy delta (item 1). */
  retrain: () =>
    request<RetrainResponse>("/router/retrain", { method: "POST" }),

  history: (params: { limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
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
      savings_pct: number;
      latency_p50_ms: number;
      latency_p95_ms: number;
      peak_ram_mb: number;
      report_path: string | null;
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

  skillGap: (studentId: string, params: { company?: string; role?: string } = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    return request<SkillGapResponse>(
      `/placement/skill-gap/${studentId}?${qs.toString()}`
    );
  },

  /** Admin console. Every call is audited and admin-only on the server. */
  adminUsers: (params: { limit?: number; role?: Role } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.role) qs.set("role", params.role);
    return request<UserOut[]>(`/admin/users?${qs.toString()}`);
  },

  adminPatchUser: (
    userId: string,
    payload: {
      is_active?: boolean;
      role?: Role;
      password?: string;
      assignments?: Array<{ scope_kind: string; scope_value: string }>;
    }
  ) =>
    request<UserOut>(`/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  adminAudit: (params: { limit?: number; denied_only?: boolean } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.denied_only) qs.set("denied_only", "true");
    return request<AuditResponse>(`/admin/audit?${qs.toString()}`);
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
