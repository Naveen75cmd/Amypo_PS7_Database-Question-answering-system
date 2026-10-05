"use client";

import * as React from "react";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";

type EvalResult = Awaited<ReturnType<typeof api.runEval>>;

const METRICS: Array<{ key: keyof EvalResult; label: string; pct?: boolean }> = [
  { key: "accuracy", label: "Answer accuracy", pct: true },
  { key: "groundedness", label: "Groundedness", pct: true },
  { key: "hallucination_rate", label: "Hallucination rate", pct: true },
  { key: "precision_at_1", label: "Precision@1", pct: true },
  { key: "precision_at_3", label: "Precision@3", pct: true },
  { key: "precision_at_5", label: "Precision@5", pct: true },
  { key: "recall_at_k", label: "Recall@k", pct: true },
  { key: "mrr", label: "MRR", pct: true },
  { key: "abstention_rate_unanswerable", label: "Abstention (unanswerable)", pct: true },
  { key: "routing_agreement", label: "Routing agreement", pct: true },
  { key: "cumulative_cost_inr", label: "Benchmark cost (INR)" },
  { key: "always_cloud_cost_inr", label: "Always-cloud cost (INR)" },
];

export default function EvaluationPage() {
  const [result, setResult] = React.useState<EvalResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(limit: number | null) {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.runEval(limit));
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "The benchmark run failed."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[860px] space-y-4 px-6 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-base font-semibold tracking-tight">Evaluation</h1>
          <div className="ml-auto flex gap-2">
            <button
              onClick={() => run(40)}
              disabled={busy}
              className="rounded-md border bg-card px-2.5 py-1.5 text-[13px] transition-colors duration-150 hover:border-[var(--accent)] disabled:opacity-50"
            >
              Quick run (40)
            </button>
            <button
              onClick={() => run(null)}
              disabled={busy}
              className="rounded-md bg-[var(--accent)] px-2.5 py-1.5 text-[13px] font-medium text-[var(--accent-foreground)] transition-opacity duration-150 hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Running…" : "Full benchmark"}
            </button>
          </div>
        </div>

        {error && (
          <p className="rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-[13px] text-amber-700 dark:text-amber-400">
            {error}
          </p>
        )}

        {result && (
          <div className="space-y-3">
            <p className="text-[13px] text-muted-foreground">
              Run {result.run_id} · {result.total} questions
            </p>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              {METRICS.map(({ key, label, pct }) => {
                const value = result[key];
                return (
                  <div key={String(key)} className="rounded-lg border bg-card p-3">
                    <div className="text-xs text-muted-foreground">{label}</div>
                    <div className="mt-1 text-lg font-semibold tabular-nums">
                      {value == null
                        ? "—"
                        : pct
                          ? `${((value as number) * 100).toFixed(1)}%`
                          : (value as number).toFixed(2)}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {!result && !error && (
          <p className="rounded-lg border bg-card px-3 py-4 text-[13px] text-muted-foreground">
            The benchmark replays labelled questions through the real pipeline and
            reports accuracy, grounding, retrieval and routing metrics. The eval
            harness lands in Phase 9; the buttons will report that until then.
          </p>
        )}
      </div>
    </div>
  );
}
