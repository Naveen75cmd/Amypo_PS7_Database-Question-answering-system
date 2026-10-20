"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useRole } from "@/components/providers";
import { cn } from "@/lib/utils";

/**
 * Recent answered questions from the query log. Clicking one restores that
 * exchange (the trace is fetched from /ask/trace/{id}); it does not re-ask.
 */
export function HistorySidebar({
  open,
  onReopen,
}: {
  open: boolean;
  onReopen: (requestId: string, question: string) => void;
}) {
  const { ready } = useRole();
  const { data } = useQuery({
    // The server scopes this to the session, so the cache key needs no role.
    queryKey: ["history"],
    queryFn: () => api.history({ limit: 30 }),
    enabled: open && ready,
    refetchInterval: 15_000,
  });

  if (!open) return null;
  return (
    <aside
      aria-label="Chat history"
      className="w-56 shrink-0 overflow-y-auto border-r bg-card"
    >
      <div className="px-3 py-2.5 text-xs font-medium text-muted-foreground">
        Recent questions
      </div>
      <ul className="px-2 pb-3">
        {(data ?? []).map((row) => (
          <li key={row.request_id}>
            <button
              onClick={() => onReopen(row.request_id, row.question)}
              title={row.question}
              className={cn(
                "mb-0.5 w-full rounded-md px-2 py-1.5 text-left text-[13px] transition-colors duration-150",
                "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <span className="line-clamp-2 leading-snug">{row.question}</span>
              <span className="mt-0.5 block text-[11px] tabular-nums text-muted-foreground/70">
                {row.created_at?.slice(0, 16).replace("T", " ")}
                {row.abstained ? " · abstained" : ""}
              </span>
            </button>
          </li>
        ))}
        {(data ?? []).length === 0 && (
          <li className="px-2 py-1.5 text-[13px] text-muted-foreground">
            Nothing yet — ask a question.
          </li>
        )}
      </ul>
    </aside>
  );
}
