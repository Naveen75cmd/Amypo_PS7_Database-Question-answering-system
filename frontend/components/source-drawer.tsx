"use client";

import * as React from "react";
import { IconX, IconCopy } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import type { Source, TraceResponse } from "@/lib/api";
import { TracePanel } from "@/components/trace-panel";

/**
 * The right drawer: the reasoning trace and the full cited records. A citation
 * chip in the chat opens this drawer with the source selected.
 */
export function SourceDrawer({
  open,
  onClose,
  trace,
  sources,
  selected,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  trace: TraceResponse | null;
  sources: Source[];
  selected: string | null;
  onSelect: (recordId: string) => void;
}) {
  const [tab, setTab] = React.useState<"sources" | "trace">("sources");
  const [copied, setCopied] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open && selected) setTab("sources");
  }, [open, selected]);

  function copyCitation(source: Source) {
    navigator.clipboard
      .writeText(`${source.record_id} — "${source.snippet}"`)
      .then(() => {
        setCopied(source.record_id);
        setTimeout(() => setCopied(null), 1500);
      })
      .catch(() => {});
  }

  return (
    <aside
      aria-label="Sources and trace"
      aria-hidden={!open}
      className={cn(
        "flex w-[380px] shrink-0 flex-col border-l bg-card transition-all duration-150",
        open ? "translate-x-0" : "absolute -right-[380px] top-0 h-full translate-x-full invisible"
      )}
    >
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        {(["sources", "trace"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "rounded-md px-2 py-1 text-[13px] capitalize transition-colors duration-150",
              tab === t
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {t}
          </button>
        ))}
        <button
          onClick={onClose}
          aria-label="Close panel"
          className="ml-auto grid size-8 place-items-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
        >
          <IconX size={16} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tab === "trace" ? (
          trace ? (
            <TracePanel trace={trace} />
          ) : (
            <p className="text-[13px] text-muted-foreground">
              Send a question to see the reasoning trace.
            </p>
          )
        ) : sources.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">No sources for this message.</p>
        ) : (
          <ul className="space-y-2">
            {sources.map((source, i) => (
              <li key={source.record_id + i}>
                <button
                  onClick={() => onSelect(source.record_id)}
                  className={cn(
                    "w-full rounded-lg border p-3 text-left transition-colors duration-150",
                    selected === source.record_id
                      ? "border-[var(--accent)]"
                      : "hover:bg-muted"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="grid size-5 shrink-0 place-items-center rounded border text-xs tabular-nums text-muted-foreground">
                      {i + 1}
                    </span>
                    <span className="min-w-0 truncate font-mono text-xs text-foreground">
                      {source.record_id}
                    </span>
                    <span
                      role="button"
                      tabIndex={0}
                      aria-label={copied === source.record_id ? "Copied" : "Copy citation"}
                      onClick={(e) => {
                        e.stopPropagation();
                        copyCitation(source);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.stopPropagation();
                          copyCitation(source);
                        }
                      }}
                      className="ml-auto text-muted-foreground hover:text-foreground"
                    >
                      <IconCopy size={14} />
                    </span>
                  </div>
                  <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                    {source.snippet}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
