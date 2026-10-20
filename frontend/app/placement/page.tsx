"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { api, downloadEligibilityPdf } from "@/lib/api";
import type {
  EligibilityResult,
  MatchResponse,
  SkillGapResponse,
  WhatIfResponse,
} from "@/lib/api";
import { useRole } from "@/components/providers";

/** "skill:python" -> "Python" style criterion labels for the table. */
function criterionLabel(name: string): string {
  if (!name.startsWith("skill:")) return name;
  const id = name.split(":", 1)[1] ?? name.slice(6);
  return id.replace(/[^a-z0-9]+/gi, " ").trim() || id;
}

function PassFail({ passed }: { passed: boolean }) {
  return (
    <span
      aria-label={passed ? "passed" : "failed"}
      className={cn(
        "grid size-4 place-items-center rounded-full text-[10px] font-bold text-white",
        passed ? "bg-[var(--accent)]" : "bg-[var(--destructive)]"
      )}
    >
      {passed ? "✓" : "✕"}
    </span>
  );
}

function CriteriaPopover({ result }: { result: EligibilityResult }) {
  return (
    <details className="group/crit">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[13px] text-muted-foreground transition-colors duration-150 hover:text-foreground">
        {result.criteria.filter((c) => !c.passed).length} of {result.criteria.length} criteria
        <ChevronDown size={12} className="transition-transform duration-150 group-open/crit:rotate-180" />
      </summary>
      <ul className="mt-1.5 space-y-1 rounded-md border bg-card p-2 text-[13px]">
        {result.criteria.map((c, i) => (
          <li key={i} className="flex items-center gap-2">
            <PassFail passed={c.passed} />
            <span className="text-foreground">{criterionLabel(c.name)}</span>
            <span className="text-muted-foreground">
              {c.passed ? "met" : c.gap ?? "not met"}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function CandidateRow({ result }: { result: EligibilityResult }) {
  return (
    <tr className="border-b last:border-0">
      <td className="py-2 pr-3 text-[13px] font-medium">{result.student_name}</td>
      <td className="py-2 pr-3 text-[13px] tabular-nums text-muted-foreground">
        {result.student_id}
      </td>
      <td className="py-2 pr-3">
        {result.eligible ? (
          <span className="tabular-nums font-medium text-[var(--accent)]">
            {result.suitability?.toFixed(1)}
          </span>
        ) : (
          <span className="text-[13px] text-muted-foreground">—</span>
        )}
      </td>
      <td className="py-2">
        <CriteriaPopover result={result} />
      </td>
    </tr>
  );
}

function DownloadReport({ studentId }: { studentId: string }) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  return (
    <span className="flex items-center gap-2">
      <button
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await downloadEligibilityPdf(studentId);
          } catch (err) {
            setError(err instanceof Error ? err.message : "Download failed.");
          } finally {
            setBusy(false);
          }
        }}
        disabled={busy}
        className="rounded-md border bg-card px-2.5 py-1.5 text-[13px] transition-colors duration-150 hover:border-[var(--accent)] disabled:opacity-50"
      >
        {busy ? "Preparing..." : "Download PDF"}
      </button>
      {error && <span className="text-xs text-[var(--destructive)]">{error}</span>}
    </span>
  );
}

function RoleSelector({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (roleId: number) => void;
}) {
  const { data: roles } = useQuery({
    queryKey: ["placement-roles"],
    queryFn: api.placementRoles,
    staleTime: 60_000,
  });

  const grouped = React.useMemo(() => {
    const map = new Map<string, typeof roles>();
    for (const r of roles ?? []) {
      map.set(r.company, [...(map.get(r.company) ?? []), r]);
    }
    return [...map.entries()];
  }, [roles]);

  return (
    <select
      aria-label="Company and role"
      value={value ?? ""}
      onChange={(e) => onChange(Number(e.target.value))}
      className="rounded-md border bg-card px-2.5 py-1.5 text-[13px] outline-none"
    >
      <option value="" disabled>
        Select a role…
      </option>
      {grouped.map(([company, list]) => (
        <optgroup key={company} label={company}>
          {list?.map((r) => (
            <option key={r.role_id} value={r.role_id}>
              {company} {r.title}
              {r.min_cgpa ? ` (min CGPA ${r.min_cgpa})` : ""}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

function EligibilityTable({
  title,
  results,
}: {
  title: string;
  results: EligibilityResult[];
}) {
  if (results.length === 0) {
    return (
      <section>
        <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">{title}</h2>
        <p className="rounded-lg border bg-card px-3 py-4 text-[13px] text-muted-foreground">
          No student meets the eligibility criteria.
        </p>
      </section>
    );
  }
  return (
    <section>
      <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">{title}</h2>
      <div className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-3 py-2 font-medium">Student</th>
              <th className="px-3 py-2 font-medium">ID</th>
              <th className="px-3 py-2 font-medium">Suitability</th>
              <th className="px-3 py-2 font-medium">Criteria</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <CandidateRow key={r.student_id} result={r} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SkillGapPanel({ report }: { report: SkillGapResponse }) {
  const gaps = report.gaps.filter((g) => g.severity !== "ok");
  const maxLevel = Math.max(5, ...gaps.map((g) => g.required_level));
  return (
    <section>
      <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">
        Skill gap{report.target_role ? ` for ${report.company} ${report.target_role}` : ""}
      </h2>
      <div className="space-y-2 rounded-lg border bg-card p-3">
        {gaps.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            All required skills are at the needed level.
          </p>
        ) : (
          gaps.map((g) => (
            <div key={g.skill} className="text-[13px]">
              <div className="mb-1 flex items-center justify-between">
                <span>{g.skill}</span>
                <span className="tabular-nums text-muted-foreground">
                  level {g.current_level} of {g.required_level}
                  {g.severity === "weak" ? " (preferred)" : ""}
                </span>
              </div>
              <div className="flex gap-0.5" aria-hidden>
                {Array.from({ length: maxLevel }, (_, i) => (
                  <span
                    key={i}
                    className={cn(
                      "h-2 flex-1 rounded-sm",
                      i < g.required_level
                        ? g.current_level > i
                          ? "bg-[var(--accent)]"
                          : "bg-[var(--destructive)]/40"
                        : g.current_level > i
                          ? "bg-[var(--accent)]/40"
                          : "bg-muted"
                    )}
                  />
                ))}
              </div>
            </div>
          ))
        )}
        {report.learning_path.length > 0 && (
          <div className="border-t pt-2">
            <h3 className="mb-1.5 text-xs font-medium text-muted-foreground">
              Suggested learning path
            </h3>
            <ol className="space-y-1">
              {report.learning_path.map((step) => (
                <li key={step.order} className="flex items-baseline gap-2 text-[13px]">
                  <span className="tabular-nums text-muted-foreground">{step.order}.</span>
                  <span>{step.title}</span>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    ~{step.effort_weeks} wk
                  </span>
                  {step.record_id && (
                    <span className="ml-auto truncate font-mono text-xs text-muted-foreground">
                      {step.record_id}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </section>
  );
}

function WhatIfPanel({
  studentId,
  skills,
}: {
  studentId: string;
  /** Current levels; a boost is applied on top of these. */
  skills: Array<{ skill_id: string | null; current_level: number }>;
}) {
  const [cgpa, setCgpa] = React.useState(0);
  const [skillBoost, setSkillBoost] = React.useState(0);
  const [result, setResult] = React.useState<WhatIfResponse | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function run() {
    setBusy(true);
    try {
      const skill_levels =
        skillBoost > 0
          ? Object.fromEntries(
              skills
                .filter((s) => s.skill_id)
                .map((s) => [s.skill_id as string, s.current_level + skillBoost])
            )
          : undefined;
      setResult(
        await api.whatIf({
          student_id: studentId,
          cgpa: cgpa > 0 ? cgpa : null,
          skill_levels,
        })
      );
    } catch {
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">What-if</h2>
      <div className="space-y-3 rounded-lg border bg-card p-3">
        <div className="text-[13px]">
          <div className="mb-1 flex items-center justify-between">
            <label htmlFor="whatif-cgpa">Projected CGPA</label>
            <span className="tabular-nums text-muted-foreground">
              {cgpa === 0 ? "keep current" : cgpa.toFixed(1)}
            </span>
          </div>
          <input
            id="whatif-cgpa"
            type="range"
            min={0}
            max={10}
            step={0.1}
            value={cgpa}
            onChange={(e) => setCgpa(Number(e.target.value))}
            className="w-full accent-[var(--accent)]"
          />
        </div>
        <div className="text-[13px]">
          <div className="mb-1 flex items-center justify-between">
            <label htmlFor="whatif-skills">Improve all skills (levels)</label>
            <span className="tabular-nums text-muted-foreground">
              {skillBoost === 0 ? "keep current" : `+${skillBoost}`}
            </span>
          </div>
          <input
            id="whatif-skills"
            type="range"
            min={0}
            max={4}
            step={1}
            value={skillBoost}
            onChange={(e) => setSkillBoost(Number(e.target.value))}
            className="w-full accent-[var(--accent)]"
          />
        </div>
        <button
          onClick={run}
          disabled={busy}
          className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-[13px] font-medium text-[var(--accent-foreground)] transition-opacity duration-150 hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Recomputing…" : "Recompute eligibility"}
        </button>
        {result && (
          <div className="space-y-1 border-t pt-2 text-[13px]">
            {result.opened_up.length === 0 && result.lost.length === 0 ? (
              <p className="text-muted-foreground">
                No role opens up or closes with these changes.
              </p>
            ) : (
              <>
                {result.opened_up.map((r) => (
                  <p key={r}>
                    <span className="font-medium text-[var(--accent)]">Opens up:</span>{" "}
                    {r}
                  </p>
                ))}
                {result.lost.map((r) => (
                  <p key={r}>
                    <span className="font-medium text-[var(--destructive)]">Lost:</span> {r}
                  </p>
                ))}
              </>
            )}
            <p className="text-xs text-muted-foreground">
              {result.baseline_eligible.length} roles eligible now →{" "}
              {result.projected_eligible.length} after the change. Nothing is saved.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

export default function PlacementPage() {
  const { role, userId } = useRole();
  const [roleId, setRoleId] = React.useState<number | null>(null);
  const [studentId, setStudentId] = React.useState("");

  React.useEffect(() => {
    setStudentId(role === "student" ? userId : "");
  }, [role, userId]);

  const isStaff = role === "staff" || role === "admin";

  const { data: placementRoles } = useQuery({
    queryKey: ["placement-roles"],
    queryFn: api.placementRoles,
    staleTime: 60_000,
  });
  const selectedRole = placementRoles?.find((r) => r.role_id === roleId) ?? null;

  const match = useQuery({
    queryKey: ["match", roleId],
    queryFn: () => api.match({ role_id: roleId!, top_n: 10 }),
    enabled: isStaff && roleId !== null,
  });

  const eligibility = useQuery({
    queryKey: ["eligibility", studentId, roleId],
    queryFn: () =>
      api.eligibility({
        student_id: studentId,
        role_id: roleId ?? undefined,
      }),
    enabled: !isStaff && studentId !== "",
  });

  const skillGap = useQuery({
    queryKey: ["skill-gap", studentId, selectedRole?.role_id],
    queryFn: () =>
      api.skillGap(studentId, {
        company: selectedRole?.company,
        role: selectedRole?.title,
      }),
    enabled: !isStaff && studentId !== "",
  });

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[860px] space-y-5 px-6 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-base font-semibold tracking-tight">Placement</h1>
          <RoleSelector value={roleId} onChange={setRoleId} />
          {/* The report is generated server-side and streamed with
              Content-Disposition, so a plain link is the whole download path.
              Same-origin cookies carry the session. */}
          {!isStaff && studentId !== "" && <DownloadReport studentId={studentId} />}
          {!isStaff && (
            <input
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              placeholder={userId}
              aria-label="Student ID"
              className="w-36 rounded-md border bg-card px-2.5 py-1.5 text-[13px] outline-none placeholder:text-muted-foreground"
            />
          )}
          {roleId !== null && !isStaff && studentId === "" && (
            <span className="text-[13px] text-muted-foreground">
              Enter a student ID to check eligibility.
            </span>
          )}
        </div>

        {isStaff ? (
          roleId === null ? (
            <p className="rounded-lg border bg-card px-3 py-4 text-[13px] text-muted-foreground">
              Select a role to rank eligible candidates.
            </p>
          ) : match.isLoading ? (
            <div className="h-24 animate-pulse rounded-lg border bg-muted" />
          ) : match.data ? (
            <div className="space-y-5">
              <EligibilityTable
                title={`Eligible for ${match.data.company} ${match.data.role}`}
                results={match.data.candidates}
              />
              {match.data.closest_misses.length > 0 && (
                <EligibilityTable
                  title="Closest misses (one criterion short)"
                  results={match.data.closest_misses}
                />
              )}
            </div>
          ) : (
            <p className="rounded-lg border bg-card px-3 py-4 text-[13px] text-muted-foreground">
              {match.error instanceof Error ? match.error.message : "No result."}
            </p>
          )
        ) : eligibility.data || skillGap.data ? (
          <div className="space-y-5">
            {eligibility.data && (
              <EligibilityTable title="Eligibility" results={eligibility.data.results} />
            )}
            {skillGap.data && <SkillGapPanel report={skillGap.data} />}
            <WhatIfPanel
              studentId={studentId || userId}
              skills={skillGap.data?.gaps ?? []}
            />
          </div>
        ) : (
          <div className="h-24 animate-pulse rounded-lg border bg-muted" />
        )}
      </div>
    </div>
  );
}
