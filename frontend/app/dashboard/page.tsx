"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { routeLabel } from "@/components/trace-panel";

function Tile({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "ok" | "warn";
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 text-lg font-semibold tabular-nums",
          tone === "warn" && "text-amber-600 dark:text-amber-400"
        )}
      >
        {value}
      </div>
      {detail && <div className="mt-0.5 text-xs text-muted-foreground">{detail}</div>}
    </div>
  );
}

function LiveTiles() {
  const { data } = useQuery({
    queryKey: ["resource-status"],
    queryFn: api.resourceStatus,
    refetchInterval: 5_000,
  });
  if (!data) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg border bg-muted" />
        ))}
      </div>
    );
  }
  const ollamaOk = data.ollama_status === "ok" || data.ollama_loaded;
  // A server that answers but lacks the model is not "down": the card says so
  // and names the one command that fixes it, instead of a bare "unavailable".
  const modelMissing = data.ollama_status === "model_missing";
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Tile label="RAM available" value={`${data.ram_available_mb} MB`} />
        <Tile label="CPU load" value={`${data.cpu_load_pct.toFixed(1)}%`} />
        <Tile
          label="Bandwidth"
          value={`${data.bandwidth_kbps} kbps`}
          detail={
            data.bandwidth_scenario !== "stable"
              ? `scenario: ${data.bandwidth_scenario}`
              : undefined
          }
          tone={data.bandwidth_scenario !== "stable" ? "warn" : undefined}
        />
        <Tile label="Cloud-sim quota left" value={String(data.api_quota_remaining)} />
        <Tile
          label="Ollama"
          value={ollamaOk ? "loaded" : modelMissing ? "model not pulled" : "unavailable"}
          detail={
            ollamaOk && data.ollama_last_latency_ms != null
              ? `last reply ${data.ollama_last_latency_ms.toFixed(0)} ms`
              : undefined
          }
          tone={ollamaOk ? undefined : "warn"}
        />
      </div>
      {!ollamaOk && (
        <p className="text-xs text-muted-foreground">
          {/* The model has to live in the Ollama the backend talks to; a pull
              into the Windows/macOS Ollama app does not fill the container. */}
          {modelMissing
            ? "The model must be in the Ollama server the backend uses — pull it into the container with "
            : "The backend cannot reach Ollama at the configured address. Start it with "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
            {modelMissing ? "docker compose run --rm ollama-pull" : "docker compose up -d ollama"}
          </code>
          {" — answers fall back to quoted evidence until then."}
        </p>
      )}
    </div>
  );
}

function RouterRetrain() {
  // On-demand retrain with the accuracy delta (Phase 8, item 1).
  //
  // The spec's example line is "router improved from 84% to 89% agreement";
  // this renders exactly that, and only after a retrain actually ran — before
  // then it says so rather than inventing a baseline.
  const client = useQueryClient();
  const retrain = useMutation({
    mutationFn: api.retrain,
    onSuccess: () => client.invalidateQueries({ queryKey: ["metrics"] }),
  });

  const result = retrain.data;

  return (
    <section className="rounded-lg border bg-card p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-medium text-muted-foreground">
            Self-optimizing router
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Retrains from the benchmark plus your thumbs ratings in the query log. Both
            numbers are scored on the same held-out questions, so the delta is comparable.
          </p>
        </div>
        <button
          onClick={() => retrain.mutate()}
          disabled={retrain.isPending}
          className="rounded-md border px-2.5 py-1 text-xs transition-colors duration-150 hover:bg-muted disabled:opacity-50"
        >
          {retrain.isPending ? "Retraining…" : "Retrain"}
        </button>
      </div>

      {retrain.isError && (
        <p className="mt-2 text-xs text-[var(--destructive)]">
          Retrain failed; the previous model is still in use.
        </p>
      )}

      {result && (
        <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
          {result.previous_accuracy != null && result.delta != null ? (
            <>
              <span className="tabular-nums">
                {Math.round(result.previous_accuracy * 100)}%
                <span className="mx-1 text-muted-foreground">→</span>
                {Math.round(result.accuracy * 100)}%
              </span>
              <span
                className={cn(
                  "tabular-nums text-xs",
                  result.delta >= 0
                    ? "text-[var(--accent)]"
                    : "text-amber-600 dark:text-amber-400"
                )}
              >
                {result.delta >= 0 ? "+" : ""}
                {(result.delta * 100).toFixed(1)} pts
              </span>
            </>
          ) : (
            <span className="tabular-nums">
              First retrain: {Math.round(result.accuracy * 100)}% accuracy
            </span>
          )}
          <span className="text-xs text-muted-foreground">
            macro-F1 {(result.macro_f1 * 100).toFixed(1)}% on {result.samples} samples ·{" "}
            {result.holdout} held out
          </span>
          <span className="text-xs text-muted-foreground">
            {result.from_feedback > 0
              ? `${result.confirmed} thumbs-up confirmed, ${result.corrected} thumbs-down corrected`
              : "no thumbs feedback yet — rate an answer in chat to feed the next retrain"}
          </span>
        </div>
      )}
    </section>
  );
}

function MetricsCharts() {
  const { data } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, refetchInterval: 10_000 });
  if (!data) {
    return <div className="h-56 animate-pulse rounded-lg border bg-muted" />;
  }
  const byRoute = Object.entries(data.requests_by_route).map(([route, count]) => ({
    route: routeLabel(route),
    count,
  }));
  const latency = Object.keys(data.latency_p50_ms).map((route) => ({
    route: routeLabel(route),
    p50: Math.round(data.latency_p50_ms[route] ?? 0),
    p95: Math.round(data.latency_p95_ms[route] ?? 0),
  }));
  const cost = [
    { name: "AMYPO actual", value: data.cumulative_cost_inr },
    { name: "Always cloud (baseline)", value: data.always_cloud_cost_inr },
  ];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="rounded-lg border bg-card p-3">
        <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">
          Requests by route
        </h2>
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={byRoute}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="route" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
              <YAxis tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="var(--accent)" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="rounded-lg border bg-card p-3">
        <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">
          Latency p50 / p95 per route (ms)
        </h2>
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={latency}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="route" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
              <YAxis tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
              <Tooltip />
              <Bar dataKey="p50" fill="var(--accent)" radius={[3, 3, 0, 0]} />
              <Bar dataKey="p95" fill="var(--muted-foreground)" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="rounded-lg border bg-card p-3">
        <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">
          Cumulative cost vs always-cloud baseline (INR)
        </h2>
        <div className="h-40">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={cost} layout="vertical">
              <XAxis type="number" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
              <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
              <Tooltip />
              <Bar dataKey="value" fill="var(--accent)" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-[13px] text-muted-foreground">
          Saved INR {data.savings_inr.toFixed(2)} ({data.savings_pct.toFixed(1)}%) so far ·
          cache hit rate {(data.cache_hit_rate * 100).toFixed(0)}% ·{" "}
          {data.total_requests} requests
        </p>
      </section>

      <section className="rounded-lg border bg-card p-3">
        <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">Answer quality</h2>
        <div className="space-y-2 text-[13px]">
          <div className="flex justify-between border-b pb-1.5">
            <span className="text-muted-foreground">Average confidence</span>
            <span className="tabular-nums">{(data.avg_confidence * 100).toFixed(0)}%</span>
          </div>
          <div className="flex justify-between border-b pb-1.5">
            <span className="text-muted-foreground">Groundedness</span>
            <span className="tabular-nums">{(data.groundedness_avg * 100).toFixed(0)}%</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Abstention rate</span>
            <span className="tabular-nums">{(data.abstention_rate * 100).toFixed(0)}%</span>
          </div>
        </div>
      </section>
    </div>
  );
}

const SCENARIOS = ["stable", "ram_crash", "quota_exhausted", "ollama_crash", "bandwidth"] as const;

function DecisionLog() {
  const client = useQueryClient();
  const [running, setRunning] = React.useState<string | null>(null);
  const [summary, setSummary] = React.useState<string | null>(null);
  const { data } = useQuery({
    queryKey: ["decisions"],
    queryFn: () => api.decisions(50),
    refetchInterval: 10_000,
  });

  async function runScenario(scenario: string) {
    setRunning(scenario);
    setSummary(null);
    try {
      const res = await api.simulate({ scenario, steps: 6, reset: false });
      setSummary(res.summary);
      client.invalidateQueries({ queryKey: ["decisions"] });
      client.invalidateQueries({ queryKey: ["resource-status"] });
      client.invalidateQueries({ queryKey: ["metrics"] });
    } catch (err) {
      setSummary(err instanceof Error ? err.message : "Simulation failed.");
    } finally {
      setRunning(null);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[13px] font-medium text-muted-foreground">Scenarios</h2>
        {SCENARIOS.map((s) => (
          <button
            key={s}
            onClick={() => runScenario(s)}
            disabled={running !== null}
            className={cn(
              "rounded-md border bg-card px-2.5 py-1 text-xs transition-colors duration-150 hover:border-[var(--accent)]",
              running === s && "opacity-50"
            )}
          >
            {s === "stable" ? "reset to stable" : s.replace(/_/g, " ")}
          </button>
        ))}
        {running && <span className="text-xs text-muted-foreground">running {running}…</span>}
      </div>
      {summary && (
        <p className="rounded-md border bg-card px-3 py-2 text-[13px] text-muted-foreground">
          {summary}
        </p>
      )}

      <div className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-3 py-2 font-medium">Query</th>
              <th className="px-3 py-2 font-medium">Routed to</th>
              <th className="px-3 py-2 font-medium">Complexity</th>
              <th className="px-3 py-2 font-medium">Cost (INR)</th>
              <th className="px-3 py-2 font-medium">Reasoning</th>
            </tr>
          </thead>
          <tbody>
            {(data?.decisions ?? []).map((d) => (
              <tr key={d.request_id} className="border-b align-top last:border-0">
                <td className="max-w-[220px] truncate px-3 py-2 text-[13px]" title={d.query}>
                  {d.query}
                </td>
                <td className="px-3 py-2 text-[13px]">{routeLabel(d.routed_to)}</td>
                <td className="px-3 py-2 text-[13px] text-muted-foreground">
                  {d.complexity ?? "—"}
                </td>
                <td className="px-3 py-2 text-[13px] tabular-nums">
                  {d.estimated_cost.toFixed(4)}
                </td>
                <td className="max-w-[280px] px-3 py-2 text-xs text-muted-foreground">
                  {d.reasoning ?? "—"}
                </td>
              </tr>
            ))}
            {(data?.decisions ?? []).length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-[13px] text-muted-foreground">
                  No decisions recorded yet — ask a question in the chat.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function DashboardPage() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[960px] space-y-5 px-6 py-6">
        <h1 className="text-base font-semibold tracking-tight">Dashboard</h1>
        <LiveTiles />
        <RouterRetrain />
        <MetricsCharts />
        <DecisionLog />
      </div>
    </div>
  );
}
