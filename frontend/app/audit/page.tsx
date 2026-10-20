"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useRole } from "@/components/providers";

/**
 * Two audit surfaces, chosen by the session's permissions.
 *
 * Staff see the cohort-query trail: every query that ranged over many students'
 * records, with the rows it touched. Admin see the full `audit_log`: logins,
 * failures, denials, personal-data reads, ingests and role changes.
 *
 * Both pages read metadata only — never the student records themselves — so
 * reading an audit trail never widens access. The server enforces both scopes;
 * this page only decides which table to ask for.
 */
export default function AuditPage() {
  const { permissions } = useRole();
  const isAdmin = permissions.audit_log;
  const isStaff = permissions.placement_cohort;
  const [deniedOnly, setDeniedOnly] = React.useState(false);

  const cohort = useQuery({
    queryKey: ["cohort-queries"],
    queryFn: () => api.cohortQueries({ limit: 100 }),
    enabled: isStaff && !isAdmin,
  });

  const audit = useQuery({
    queryKey: ["admin-audit", deniedOnly],
    queryFn: () => api.adminAudit({ limit: 200, denied_only: deniedOnly }),
    enabled: isAdmin,
    refetchInterval: 20_000,
  });

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1040px] space-y-4 px-6 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-base font-semibold tracking-tight">Audit trail</h1>
          <p className="text-xs text-muted-foreground">
            {isAdmin
              ? "Every allowed and denied action, newest first."
              : "Cohort queries over student records, newest first."}
          </p>
          {isAdmin && (
            <label className="ml-auto flex items-center gap-2 text-[12px] text-muted-foreground">
              <input
                type="checkbox"
                checked={deniedOnly}
                onChange={(e) => setDeniedOnly(e.target.checked)}
              />
              Denied only
            </label>
          )}
        </div>

        {!isAdmin && !isStaff && (
          <p className="rounded-lg border px-3.5 py-2.5 text-[13px] text-muted-foreground">
            Audit trails are limited to staff and administrators. Your own history
            is in the chat sidebar.
          </p>
        )}

        {isAdmin && audit.data && (
          <div className="flex flex-wrap gap-4 rounded-lg border bg-card px-3.5 py-2.5 text-[12px] text-muted-foreground">
            <span>
              allowed <strong className="text-foreground">{audit.data.summary.allowed ?? 0}</strong>
            </span>
            <span>
              denied <strong className="text-foreground">{audit.data.summary.denied ?? 0}</strong>
            </span>
            <span>
              total <strong className="text-foreground">{audit.data.summary.total ?? 0}</strong>
            </span>
          </div>
        )}

        {isAdmin && audit.error && (
          <p className="rounded-lg border px-3.5 py-2.5 text-[13px] text-[var(--destructive)]">
            {audit.error instanceof Error ? audit.error.message : "The audit log could not be read."}
          </p>
        )}

        {isAdmin && audit.data && (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="border-b px-2 py-1.5 font-medium">When</th>
                <th className="border-b px-2 py-1.5 font-medium">Actor</th>
                <th className="border-b px-2 py-1.5 font-medium">Action</th>
                <th className="border-b px-2 py-1.5 font-medium">Target</th>
                <th className="border-b px-2 py-1.5 font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {audit.data.entries.map((row) => (
                <tr key={row.id} className="align-top">
                  <td className="border-b px-2 py-1.5 tabular-nums text-muted-foreground">
                    {row.created_at ? row.created_at.slice(0, 19).replace("T", " ") : "—"}
                  </td>
                  <td className="border-b px-2 py-1.5">
                    {row.actor_role ?? "anonymous"}
                    {row.actor_id ? (
                      <span className="ml-1 text-[11px] text-muted-foreground">
                        {row.actor_id.slice(0, 8)}
                      </span>
                    ) : null}
                  </td>
                  <td className="border-b px-2 py-1.5">
                    <code>{row.action}</code>
                  </td>
                  <td className="border-b px-2 py-1.5 text-muted-foreground">
                    {row.target || "—"}
                    {row.detail ? (
                      <span className="block text-[11px]">{row.detail}</span>
                    ) : null}
                  </td>
                  <td className="border-b px-2 py-1.5">
                    <span
                      className={
                        row.allowed
                          ? "rounded bg-muted px-1.5 py-0.5 text-[11px]"
                          : "rounded bg-red-500/15 px-1.5 py-0.5 text-[11px]"
                      }
                    >
                      {row.allowed ? "allowed" : "denied"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {isStaff && !isAdmin && cohort.error && (
          <p className="rounded-lg border px-3.5 py-2.5 text-[13px] text-[var(--destructive)]">
            {cohort.error instanceof Error ? cohort.error.message : "The audit log could not be read."}
          </p>
        )}

        {isStaff && !isAdmin && cohort.data && (
          cohort.data.length === 0 ? (
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
                {cohort.data.map((row) => (
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
