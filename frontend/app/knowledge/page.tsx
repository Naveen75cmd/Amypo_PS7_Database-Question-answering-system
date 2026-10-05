"use client";

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export default function KnowledgePage() {
  const client = useQueryClient();
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<string | null>(null);

  const { data: docs } = useQuery({
    queryKey: ["documents"],
    queryFn: api.documents,
  });

  async function reindex(force: boolean) {
    setBusy(true);
    setResult(null);
    try {
      const r = await api.reingest(force);
      setResult(
        `${r.documents} documents, ${r.chunks} new chunks, ${r.records} record cards ` +
          `(${r.skipped_unchanged} unchanged) in ${(r.duration_ms / 1000).toFixed(1)}s` +
          (r.errors.length ? ` — errors: ${r.errors.join("; ")}` : "")
      );
      client.invalidateQueries({ queryKey: ["documents"] });
    } catch (err) {
      setResult(err instanceof Error ? err.message : "Ingestion failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[860px] space-y-4 px-6 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-base font-semibold tracking-tight">Knowledge</h1>
          <span className="text-[13px] text-muted-foreground">
            {docs ? `${docs.length} documents indexed` : "loading…"}
          </span>
          <div className="ml-auto flex gap-2">
            <button
              onClick={() => reindex(false)}
              disabled={busy}
              className="rounded-md border bg-card px-2.5 py-1.5 text-[13px] transition-colors duration-150 hover:border-[var(--accent)] disabled:opacity-50"
            >
              Re-scan
            </button>
            <button
              onClick={() => reindex(true)}
              disabled={busy}
              className="rounded-md bg-[var(--accent)] px-2.5 py-1.5 text-[13px] font-medium text-[var(--accent-foreground)] transition-opacity duration-150 hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Ingesting…" : "Force re-index"}
            </button>
          </div>
        </div>
        <p className="text-[13px] text-muted-foreground">
          Ingestion reads the markdown corpus and structured rows, chunks them with
          stable record ids, and re-embeds only what changed. Re-scan skips
          unchanged files; force re-index rebuilds everything.
        </p>
        {result && (
          <p className="rounded-md border bg-card px-3 py-2 text-[13px] text-muted-foreground">
            {result}
          </p>
        )}

        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-3 py-2 font-medium">Document</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Scope</th>
                <th className="px-3 py-2 font-medium text-right">Chunks</th>
                <th className="px-3 py-2 font-medium">Indexed</th>
              </tr>
            </thead>
            <tbody>
              {(docs ?? []).map((d) => (
                <tr key={d.doc_id} className="border-b last:border-0">
                  <td className="px-3 py-2 text-[13px]">
                    <span className="block max-w-[320px] truncate font-medium" title={d.title}>
                      {d.title}
                    </span>
                    <span className="block font-mono text-xs text-muted-foreground">
                      {d.doc_id}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-[13px] text-muted-foreground">{d.doc_type}</td>
                  <td className="px-3 py-2 text-[13px] text-muted-foreground">{d.access_scope}</td>
                  <td className="px-3 py-2 text-right text-[13px] tabular-nums">
                    {d.chunk_count}
                  </td>
                  <td className="px-3 py-2 text-[13px] tabular-nums text-muted-foreground">
                    {d.indexed_at?.slice(0, 16).replace("T", " ") ?? "—"}
                  </td>
                </tr>
              ))}
              {(docs ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-[13px] text-muted-foreground">
                    Nothing indexed yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
