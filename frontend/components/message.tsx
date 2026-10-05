"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { IconCopy } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import type { Source } from "@/lib/api";
import { routeLabel } from "@/components/trace-panel";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  sources?: Source[];
  confidence?: number;
  route?: string | null;
  degraded?: boolean;
  abstained?: boolean;
  latencyMs?: number | null;
  costInr?: number | null;
  claimsSupported?: number;
  claimsTotal?: number;
  traceId?: string | null;
  error?: string;
}

/** Splits text into prose and [Sn]/[n] citation chips so chips can be buttons. */
function ContentWithCitations({
  text,
  onCitation,
}: {
  text: string;
  onCitation?: (n: number) => void;
}) {
  const parts = React.useMemo(() => {
    const out: Array<{ kind: "text"; value: string } | { kind: "cite"; n: number }> = [];
    const re = /\[(?:S)?(\d+)\]/g;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push({ kind: "text", value: text.slice(last, m.index) });
      out.push({ kind: "cite", n: Number(m[1]) });
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push({ kind: "text", value: text.slice(last) });
    return out;
  }, [text]);

  return (
    <div className="space-y-2 text-[14.5px] leading-relaxed">
      {parts.map((part, i) =>
        part.kind === "text" ? (
          <span key={i} className="inline [&>p]:inline [&>p]:m-0">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.value}</ReactMarkdown>
          </span>
        ) : (
          <button
            key={i}
            onClick={() => onCitation?.(part.n)}
            aria-label={`Show source ${part.n}`}
            className="mx-0.5 inline-grid h-[18px] min-w-[18px] place-items-center rounded border bg-muted align-middle text-[11px] tabular-nums text-muted-foreground transition-colors duration-150 hover:border-[var(--accent)] hover:text-foreground"
          >
            {part.n}
          </button>
        )
      )}
    </div>
  );
}

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const tone = value >= 0.7 ? "bg-[var(--accent)]" : value >= 0.45 ? "bg-amber-500" : "bg-[var(--destructive)]";
  return (
    <span className="flex items-center gap-1.5" title={`Confidence ${pct}%`}>
      <span className="h-1 w-14 overflow-hidden rounded-full bg-muted">
        <span className={cn("block h-full rounded-full transition-all duration-150", tone)} style={{ width: `${pct}%` }} />
      </span>
      <span className="tabular-nums">{pct}%</span>
    </span>
  );
}

export function Message({
  message,
  onCitation,
}: {
  message: ChatMessage;
  onCitation?: (n: number) => void;
}) {
  const [copied, setCopied] = React.useState(false);
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg rounded-br-sm border bg-muted px-3.5 py-2.5 text-[14.5px] leading-relaxed">
          {message.text}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[85%] space-y-1.5">
      {message.degraded && !message.abstained && !message.error && (
        <p className="rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-1.5 text-[13px] text-amber-700 dark:text-amber-400">
          Answered in offline mode: the local language model was unavailable, so the
          answer was extracted directly from cited records.
        </p>
      )}

      {message.error ? (
        <div className="rounded-lg border px-3.5 py-2.5">
          <p className="text-[14.5px] text-[var(--destructive)]">{message.error}</p>
        </div>
      ) : message.abstained ? (
        <div className="rounded-lg border px-3.5 py-2.5">
          <p className="text-[14.5px] leading-relaxed">{message.text}</p>
          <p className="mt-1 text-[13px] text-muted-foreground">
            No record supported an answer, so nothing was asserted. Check the sources
            panel for the nearest records.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border bg-card px-3.5 py-2.5">
          <ContentWithCitations text={message.text} onCitation={onCitation} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-xs text-muted-foreground">
        {message.route && <span>{routeLabel(message.route)}</span>}
        {message.latencyMs != null && <span className="tabular-nums">{Math.round(message.latencyMs)} ms</span>}
        {message.costInr != null && message.costInr > 0 && (
          <span className="tabular-nums">INR {message.costInr.toFixed(4)}</span>
        )}
        {message.confidence != null && <ConfidenceMeter value={message.confidence} />}
        {message.claimsTotal != null && message.claimsTotal > 0 && (
          <span>
            grounded {message.claimsSupported}/{message.claimsTotal} claims
          </span>
        )}
        {message.sources && message.sources.length > 0 && (
          <span>
            {message.sources.length} source{message.sources.length > 1 ? "s" : ""}
          </span>
        )}
        <button
          onClick={() => {
            navigator.clipboard.writeText(message.text).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            });
          }}
          className="ml-auto flex items-center gap-1 transition-colors duration-150 hover:text-foreground"
        >
          <IconCopy size={12} />
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}
