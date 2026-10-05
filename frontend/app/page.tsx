"use client";

import * as React from "react";
import { api, type TraceResponse } from "@/lib/api";
import { useRole } from "@/components/providers";
import { AskInput } from "@/components/ask-input";
import { Message, type ChatMessage } from "@/components/message";
import { SourceDrawer } from "@/components/source-drawer";

const STARTERS: Record<"student" | "staff", string[]> = {
  student: [
    "Am I eligible for Zoho SDE?",
    "What am I missing for Infosys?",
    "Which roles am I eligible for?",
    "What is the attendance policy?",
  ],
  staff: [
    "Who is eligible for Capgemini Analyst?",
    "Top 5 for TCS Digital",
    "What is the refund policy for hostel fees?",
    "How is the router saving cost?",
  ],
};

export default function ChatPage() {
  const { role, userId } = useRole();
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [pending, setPending] = React.useState(false);
  const [trace, setTrace] = React.useState<TraceResponse | null>(null);
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [selectedSource, setSelectedSource] = React.useState<string | null>(null);
  const [activeSources, setActiveSources] = React.useState<typeof messages[number]["sources"]>([]);
  const listRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, pending]);

  // "/" focuses the chat input, per the keyboard contract.
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (e.key === "/" && !["TEXTAREA", "INPUT"].includes(target.tagName)) {
        e.preventDefault();
        inputRef.current?.querySelector("textarea")?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function ask(question: string) {
    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", text: question };
    setMessages((prev) => [...prev, userMsg]);
    setPending(true);
    try {
      const res = await api.ask({
        question,
        user_id: role === "student" ? userId : null,
        role,
      });
      let claimsSupported: number | undefined;
      let claimsTotal: number | undefined;
      let traceData: TraceResponse | null = null;
      if (res.trace_id) {
        try {
          traceData = await api.trace(res.trace_id);
          claimsTotal = traceData.claims.length;
          claimsSupported = traceData.claims.filter((c) => c.supported).length;
        } catch {
          /* the trace is supplementary; the answer stands without it */
        }
        setTrace(traceData);
      }
      setActiveSources(res.sources);
      setMessages((prev) => [
        ...prev,
        {
          id: res.trace_id ?? crypto.randomUUID(),
          role: "assistant",
          text: res.answer,
          sources: res.sources,
          confidence: res.confidence,
          route: res.route,
          degraded: res.degraded,
          abstained: res.abstained,
          latencyMs: res.latency_ms,
          costInr: res.estimated_cost,
          claimsSupported,
          claimsTotal,
          traceId: res.trace_id,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: "",
          error: err instanceof Error ? err.message : "The request failed.",
        },
      ]);
    } finally {
      setPending(false);
    }
  }

  function openSource(n: number) {
    const source = activeSources?.[n - 1];
    if (!source) return;
    setSelectedSource(source.record_id);
    setDrawerOpen(true);
  }

  const isEmpty = messages.length === 0;

  return (
    <div className="relative flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-[760px] flex-col gap-5 px-4 py-6">
            {isEmpty ? (
              <div className="mt-16 space-y-6">
                <div>
                  <h1 className="text-lg font-semibold tracking-tight">
                    Ask AMYPO
                  </h1>
                  <p className="mt-1 text-[14px] text-muted-foreground">
                    Answers are grounded in campus records and policies; every claim
                    carries the record it came from.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {STARTERS[role].map((s) => (
                    <button
                      key={s}
                      onClick={() => ask(s)}
                      className="rounded-md border bg-card px-3 py-1.5 text-[13px] text-muted-foreground transition-colors duration-150 hover:border-[var(--accent)] hover:text-foreground"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m) => (
                <Message key={m.id} message={m} onCitation={openSource} />
              ))
            )}
            {pending && (
              <p className="px-1 text-[13px] text-muted-foreground" aria-live="polite">
                Checking records…
              </p>
            )}
          </div>
        </div>

        <div ref={inputRef} className="shrink-0 border-t bg-background px-4 py-3">
          <div className="mx-auto max-w-[760px]">
            <AskInput disabled={pending} onSubmit={(value) => ask(value)} />
          </div>
        </div>
      </div>

      <SourceDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        trace={trace}
        sources={activeSources ?? []}
        selected={selectedSource}
        onSelect={setSelectedSource}
      />
    </div>
  );
}
