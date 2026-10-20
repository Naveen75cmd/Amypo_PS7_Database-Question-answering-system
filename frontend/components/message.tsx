"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { IconCopy, IconThumbDown, IconThumbUp } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type {
  CarbonEstimate,
  ClosestRecord,
  ConflictPayload,
  ModelTier,
  Source,
  TraceClaim,
} from "@/lib/api";
import { routeLabel } from "@/components/trace-panel";
import { useRole } from "@/components/providers";

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
  // --- Phase 8 add-ons -------------------------------------------------
  clarifyingQuestion?: string | null;
  /** Nearest records retrieval found when the answer abstained (item 3). */
  closestRecords?: ClosestRecord[];
  conflict?: ConflictPayload | null;
  carbon?: CarbonEstimate | null;
  detectedLanguage?: string | null;
  modelTier?: ModelTier | null;
  /** Per-claim support status for in-answer highlighting (item 2). */
  claims?: TraceClaim[];
  /** Placement intents open the Career Readiness card (item 8). */
  intent?: string | null;
}

/** Intents that warrant the Career Readiness card. */
const CAREER_INTENTS = new Set([
  "placement_eligibility",
  "skill_gap",
  "candidate_recommendation",
]);

/** Tier labels: honest about what actually produced the answer (item 4). */
const TIER_LABEL: Record<ModelTier, string> = {
  primary: "local model",
  downgraded: "small model (low RAM)",
  extractive: "extractive (no model)",
};

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

/**
 * Claim-level citation highlighting (Phase 8, item 2).
 *
 * Claims are the answer's own sentences, so each one is located in the text and
 * underlined in place: green where the verifier found evidence, red where it did
 * not. Clicking a claim reveals the evidence sentence it was checked against,
 * which is the "proof" half of the feature — an underline with nothing behind it
 * would just be decoration.
 */
/** One inline token in a claim-highlighted answer. */
type Part =
  | { kind: "text"; value: string }
  | { kind: "cite"; n: number }
  | { kind: "claim"; index: number; value: string; supported: boolean };

function ClaimHighlightedText({
  text,
  claims,
  onCitation,
}: {
  text: string;
  claims: TraceClaim[];
  onCitation?: (n: number) => void;
}) {
  const [open, setOpen] = React.useState<number | null>(null);

  // One flat, ordered list of inline parts: prose, citation chips and
  // underlined claims. Tokenising once (rather than nesting a chip button
  // inside a claim button) keeps the DOM valid — interactive elements are
  // siblings, never descendants of one another.
  const parts = React.useMemo(() => {
    const out: Part[] = [];

    // Locate claims first so their spans are known before tokenising text.
    const marks: Array<{ start: number; end: number; index: number }> = [];
    let cursor = 0;
    claims.forEach((claim, i) => {
      const at = text.indexOf(claim.text, cursor);
      if (at < 0) return; // not present verbatim; leave as plain prose
      marks.push({ start: at, end: at + claim.text.length, index: i });
      cursor = at + claim.text.length;
    });

    const pushProse = (chunk: string) => {
      const re = /\[(?:S)?(\d+)\]/g;
      let last = 0;
      let m: RegExpExecArray | null;
      while ((m = re.exec(chunk))) {
        if (m.index > last) out.push({ kind: "text", value: chunk.slice(last, m.index) });
        out.push({ kind: "cite", n: Number(m[1]) });
        last = m.index + m[0].length;
      }
      if (last < chunk.length) out.push({ kind: "text", value: chunk.slice(last) });
    };

    let pos = 0;
    for (const mark of marks) {
      if (mark.start > pos) pushProse(text.slice(pos, mark.start));
      const claim = claims[mark.index];
      const value = text.slice(mark.start, mark.end);
      // Citation markers inside a claim still need to be clickable chips.
      pushClaim(value, mark.index, claim.supported, out);
      pos = mark.end;
    }
    if (pos < text.length) pushProse(text.slice(pos));
    return out;
  }, [text, claims]);

  return (
    <div className="space-y-2 text-[14.5px] leading-relaxed">
      <p>
        {parts.map((part, i) => {
          if (part.kind === "text") {
            return (
              <span key={i} className="inline [&>p]:inline [&>p]:m-0">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.value}</ReactMarkdown>
              </span>
            );
          }
          if (part.kind === "cite") {
            return (
              <button
                key={i}
                type="button"
                onClick={() => onCitation?.(part.n)}
                aria-label={`Show source ${part.n}`}
                className="mx-0.5 inline-grid h-[18px] min-w-[18px] place-items-center rounded border bg-muted align-middle text-[11px] tabular-nums text-muted-foreground transition-colors duration-150 hover:border-[var(--accent)] hover:text-foreground"
              >
                {part.n}
              </button>
            );
          }
          const isOpen = open === part.index;
          const claim = claims[part.index];
          return (
            <span key={i} className="inline">
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : part.index)}
                aria-expanded={isOpen}
                title={
                  part.supported
                    ? "Supported by a cited record — click for the evidence"
                    : (claim.reason ?? "Unsupported claim — click for detail")
                }
                className={cn(
                  "cursor-pointer rounded-sm px-0.5 underline decoration-2 underline-offset-2 transition-colors duration-150",
                  part.supported
                    ? "decoration-[var(--accent)] hover:bg-[var(--accent)]/10"
                    : "decoration-[var(--destructive)] hover:bg-[var(--destructive)]/10"
                )}
              >
                {part.value}
              </button>
              {!part.supported && (
                <span
                  role="img"
                  aria-label="Unsupported claim"
                  title={claim.reason ?? "No record supported this claim"}
                  className="ml-0.5 align-super text-[10px] text-[var(--destructive)]"
                >
                  ⚠
                </span>
              )}
            </span>
          );
        })}
      </p>

      {open != null && claims[open] && (
        <div className="rounded-md border border-dashed px-3 py-2 text-[13px]">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span
              className={
                claims[open].supported
                  ? "text-[var(--accent)]"
                  : "text-[var(--destructive)]"
              }
            >
              {claims[open].supported ? "Supported" : "Not supported"}
            </span>
            {claims[open].evidence_record_id && (
              <code>{claims[open].evidence_record_id}</code>
            )}
            {typeof claims[open].score === "number" && (
              <span className="tabular-nums">score {claims[open].score.toFixed(2)}</span>
            )}
          </div>
          {claims[open].evidence_snippet ? (
            <p className="text-muted-foreground">“{claims[open].evidence_snippet}”</p>
          ) : (
            <p className="text-muted-foreground">
              {claims[open].reason ?? "No evidence sentence was found for this claim."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Split one claim's text into underlined parts and citation chips, appending
 * them to ``out``. Claim text carries its own ``[S1]`` markers, so those become
 * sibling chips rather than buttons nested inside the claim's button — nested
 * interactive elements are invalid HTML and break keyboard navigation.
 */
function pushClaim(
  value: string,
  index: number,
  supported: boolean,
  out: Part[]
) {
  const re = /\[(?:S)?(\d+)\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  const push = (chunk: string) => {
    if (chunk) out.push({ kind: "claim", index, value: chunk, supported });
  };
  while ((m = re.exec(value))) {
    if (m.index > last) push(value.slice(last, m.index));
    out.push({ kind: "cite", n: Number(m[1]) });
    last = m.index + m[0].length;
  }
  if (last < value.length) push(value.slice(last));
}

/**
 * Career Readiness card (Phase 8, item 8).
 *
 * The brief asks for the Phase 6 what-if and learning-path work to be reachable
 * from chat rather than only from the placement page, so a student who just got
 * a placement answer can open it without navigating away.
 *
 * It renders nothing unless the message is actually a placement answer, so the
 * card never shows up on an unrelated question.
 */
function CareerReadinessCard({ studentId }: { studentId?: string | null }) {
  const [open, setOpen] = React.useState(false);

  return (
    <div className="rounded-lg border bg-card px-3.5 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[13px] font-medium">Career Readiness</div>
          <p className="text-[12px] text-muted-foreground">
            Eligibility, skill gaps, learning path and what-if.
          </p>
        </div>
        <a
          href="/placement"
          onClick={() => setOpen(true)}
          className="shrink-0 rounded-md border px-2.5 py-1 text-xs transition-colors duration-150 hover:bg-muted"
        >
          {open ? "Open placement →" : "Open placement"}
        </a>
      </div>
      {studentId && (
        <p className="mt-1.5 text-[12px] text-muted-foreground">
          Loaded for {studentId} — the panel carries your baseline and projected
          eligibility.
        </p>
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
  // Thumbs feed /router/retrain; the dashboard cites this count, so the control
  // has to exist here rather than only as an endpoint.
  const [rated, setRated] = React.useState<-1 | 1 | null>(null);
  const isUser = message.role === "user";
  // The session decides whether this reader gets a personal career card.
  const { userId, permissions } = useRole();

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
            No record supported an answer, so nothing was asserted.
          </p>
          {message.closestRecords && message.closestRecords.length > 0 && (
            <div className="mt-2">
              <span className="text-[12px] text-muted-foreground">
                Closest records:
              </span>
              <ul className="mt-1 space-y-0.5">
                {message.closestRecords.map((record) => (
                  <li key={record.record_id} className="text-[13px]">
                    <button
                      type="button"
                      onClick={() => onCitation?.(record.index)}
                      className="rounded px-0.5 text-left underline decoration-dotted underline-offset-2 transition-colors duration-150 hover:bg-muted"
                    >
                      <span className="tabular-nums text-muted-foreground">
                        [{record.index}]{" "}
                      </span>
                      {record.title || record.record_id}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {message.clarifyingQuestion && (
            <p className="mt-2 rounded-md border border-dashed px-2.5 py-1.5 text-[13px]">
              {message.clarifyingQuestion}
            </p>
          )}
        </div>
      ) : message.claims && message.claims.length > 0 ? (
        <div className="rounded-lg border bg-card px-3.5 py-2.5">
          <ClaimHighlightedText
            text={message.text}
            claims={message.claims}
            onCitation={onCitation}
          />
        </div>
      ) : (
        <div className="rounded-lg border bg-card px-3.5 py-2.5">
          <ContentWithCitations text={message.text} onCitation={onCitation} />
        </div>
      )}

      {message.conflict && (
        <div className="rounded-md border border-amber-500/50 bg-amber-500/5 px-3 py-2 text-[13px]">
          <span className="font-medium text-amber-700 dark:text-amber-400">
            Conflicting records:
          </span>{" "}
          <span className="text-muted-foreground">
            {message.conflict.superseded_title} states {message.conflict.loser_value}
            {" "}
            <span className="tabular-nums">[S{message.conflict.superseded_index}]</span>, while{" "}
            {message.conflict.newer_title} states {message.conflict.winner_value}{" "}
            <span className="tabular-nums">[S{message.conflict.newer_index}]</span>. The newer
            record was used.
          </span>
        </div>
      )}

      {message.detectedLanguage && (
        <p className="px-1 text-[12px] text-muted-foreground">
          Experimental: {message.detectedLanguage} input detected by script; answered in
          English.
        </p>
      )}

      {message.intent && CAREER_INTENTS.has(message.intent) && (
        <CareerReadinessCard studentId={permissions.own_records ? userId : null} />
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-xs text-muted-foreground">
        {message.route && <span>{routeLabel(message.route)}</span>}
        {message.latencyMs != null && <span className="tabular-nums">{Math.round(message.latencyMs)} ms</span>}
        {message.costInr != null && message.costInr > 0 && (
          <span className="tabular-nums">INR {message.costInr.toFixed(4)}</span>
        )}
        {message.confidence != null && <ConfidenceMeter value={message.confidence} />}
        {message.modelTier && (
          <span title={`Tier: ${message.modelTier}`}>
            {TIER_LABEL[message.modelTier]}
          </span>
        )}
        {message.carbon && (
          <span
            className="tabular-nums"
            title="Estimated, not measured"
          >
            {message.carbon.kwh.toExponential(1)} kWh
          </span>
        )}
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
        <div className="ml-auto flex items-center gap-1">
          {message.traceId && (
            <>
              {([
                { value: 1 as const, label: "Helpful", Icon: IconThumbUp },
                { value: -1 as const, label: "Not helpful", Icon: IconThumbDown },
              ]).map(({ value, label, Icon }) => (
                <button
                  key={label}
                  aria-label={label}
                  aria-pressed={rated === value}
                  title={rated === value ? `${label} - recorded` : label}
                  onClick={() => {
                    if (!message.traceId) return;
                    const previous = rated;
                    setRated(value);
                    api
                      .feedback({ request_id: message.traceId, rating: value })
                      .catch(() => setRated(previous));
                  }}
                  className={cn(
                    "grid size-5 place-items-center rounded transition-colors duration-150 hover:text-foreground",
                    rated === value && "text-[var(--accent)]"
                  )}
                >
                  <Icon size={12} />
                </button>
              ))}
            </>
          )}
          <button
            onClick={() => {
              navigator.clipboard.writeText(message.text).then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              });
            }}
            className="flex items-center gap-1 transition-colors duration-150 hover:text-foreground"
          >
            <IconCopy size={12} />
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
    </div>
  );
}
