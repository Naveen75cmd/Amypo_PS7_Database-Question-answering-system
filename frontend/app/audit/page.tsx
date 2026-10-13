"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useRole } from "@/components/providers";

/**
 * Audit trail for staff cohort queries (Phase 8, item 7).
 *
 * Every query that ranges over many students' records is written to
 * `cohort_queries` by the backend; this page is the other half of that control —
 * a log nobody can read is not an audit trail. It shows query metadata (who ran
 * it, over which cohort, how many rows it touched), never student records, so
 * opening it does not widen anyone's access. The backend enforces staff-only and
 * returns 403 for a student, which is rendered as a plain explanation rather
 * than an error.
 */
export default function AuditPage() {
  const { role } = useRole();
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["cohort-queries", role],
    queryFn: () => api.cohortQueries({ limit: 100, requester_role: role }),
  });

  const denied = error instanceof Error && /staff/i.test(error.message);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[980px] space-y-4 px-6 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-base font-semibold tracking-tight">Audit trail</h1>
          <p className="text-xs text-muted-foreground">
            Cohort queries over student records, newest first.
          </p>
          {role === "staff" && (
            <button
              onClick={() => refetch()}
              className="ml-auto rounded-md border bg-card px-2.5 py-1.5 text-[13px] transition-colors duration-150 hover:border-[var(--accent)]"
            >
              Refresh
            </button>
          )}
        </div>

        {role !== "staff" && (
          <p className="rounded-lg border px-3.5 py-2.5 text-[13px] text-muted-foreground">
            Cohort queries are limited to staff. A student account can see its own
            eligibility and nothing about other students.
          </p>
        )}

        {denied && (
          <p className="rounded-lg border px-3.5 py-2.5 text-[13px] text-muted-foreground">
            The server refused this list for the current role.
          </p>
        )}

        {role === "staff" && isPending && (
          <div className="space-y-2" aria-busy>
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-9 animate-pulse rounded-md bg-muted" />
            ))}
          </div>
        )}

        {role === "staff" && error && !denied && (
          <p className="rounded-lg border px-3.5 py-2.5 text-[13px] text-[var(--destructive)]">
            {error instanceof Error ? error.message : "The audit log could not be read."}
          </p>
        )}

        {role === "staff" && data && (
          data.length === 0 ? (
            <p className="rounded-lg border px-3.5 py-2.5 text-[13px] text-muted-foreground">
              No cohort queries recorded yet. Run an eligibility or cohort question
              and it will appear here.
            </p>
          ) : (
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="border-b px-2 py-1.5 font-medium">When</th>
                  <th className="border-b px-2 py-1.5 font-medium">Kind</th>
                  <th className="border-b px-2 py-1.5 font-medium">Query</th>
                  <th className="border-b px-2 py-1.5 font-medium">Cohort</th>
                  <th className="border-b px-2 py-1.5 text-right font-medium">Rows</th>
                </tr>
              </thead>
              <tbody>
                {data.map((row) => (
                  <tr key={row.id} className="align-top">
                    <td className="border-b px-2 py-1.5 tabular-nums text-muted-foreground">
                      {row.created_at ? row.created_at.slice(0, 19).replace("T", " ") : "—"}
                    </td>
                    <td className="border-b px-2 py-1.5">
                      <code>{row.kind}</code>
                    </td>
                    <td className="border-b px-2 py-1.5">{row.query}</td>
                    <td className="border-b px-2 py-1.5 text-muted-foreground">
                      {[row.company, row.role_title, row.department]
                        .filter(Boolean)
                        .join(" · ") || "all records"}
                    </td>
                    <td className="border-b px-2 py-1.5 text-right tabular-nums">
                      {row.result_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
    </div>
  );
}
