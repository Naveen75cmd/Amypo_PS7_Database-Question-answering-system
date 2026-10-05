"use client";

import {
  ThoughtChain,
  ThoughtChainStep,
  ThoughtChainTrigger,
  ThoughtChainContent,
  ThoughtChainItem,
} from "@/components/ui/thought-chain";
import type { TraceResponse } from "@/lib/api";

/** Route badge text: plain and specific, never "magic". */
export function routeLabel(route: string | null): string {
  if (!route) return "—";
  switch (route) {
    case "cache":
      return "Cache";
    case "local":
      return "Local model";
    case "offline_fallback":
      return "Offline (extractive)";
    case "cloud":
      return "Cloud-sim";
    default:
      return route;
  }
}

/**
 * Renders the trace the backend persisted for this request. Every step,
 * timing and count shown here was measured by the pipeline — the UI never
 * invents a stage.
 */
export function TracePanel({ trace }: { trace: TraceResponse }) {
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1 text-xs font-medium text-muted-foreground">Router decision</div>
        <div className="flex items-center gap-2 text-[13px]">
          <span className="rounded border bg-muted px-1.5 py-0.5 text-xs">
            {routeLabel(trace.route)}
          </span>
          {trace.complexity && (
            <span className="text-muted-foreground">complexity: {trace.complexity}</span>
          )}
          {trace.intent && (
            <span className="text-muted-foreground">intent: {trace.intent}</span>
          )}
        </div>
      </div>

      <ThoughtChain>
        {trace.steps.map((step) => (
          <ThoughtChainStep
            key={step.id}
            status={step.status === "failed" ? "failed" : step.status === "pending" ? "pending" : "done"}
          >
            <ThoughtChainTrigger
              meta={step.duration_ms != null ? `${step.duration_ms.toFixed(0)} ms` : undefined}
            >
              {step.title}
            </ThoughtChainTrigger>
            <ThoughtChainContent>
              {step.detail && <ThoughtChainItem>{step.detail}</ThoughtChainItem>}
              {step.items.map((item, i) => (
                <ThoughtChainItem key={i}>{item}</ThoughtChainItem>
              ))}
            </ThoughtChainContent>
          </ThoughtChainStep>
        ))}
      </ThoughtChain>

      {trace.claims.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            Verified claims (
            {trace.claims.filter((c) => c.supported).length}/{trace.claims.length} supported)
          </div>
          <ul className="space-y-1">
            {trace.claims.map((claim, i) => (
              <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed">
                <span
                  aria-hidden
                  className={
                    claim.supported
                      ? "mt-1 size-1.5 shrink-0 rounded-full bg-[var(--accent)]"
                      : "mt-1 size-1.5 shrink-0 rounded-full bg-[var(--destructive)]"
                  }
                />
                <span className="text-muted-foreground">{claim.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
