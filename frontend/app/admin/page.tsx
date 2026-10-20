"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Role, type UserOut } from "@/lib/api";
import { useRole } from "@/components/providers";

/**
 * Account administration. Admin only, enforced by `/admin/*` on the server.
 *
 * Every action here is an audited server call: disabling an account also ends
 * its sessions, resetting a password revokes the refresh chain, and changing a
 * role invalidates the tokens issued under the old role. This page is the
 * control panel; the backend is the control.
 */

const ROLES: Role[] = ["admin", "staff", "student", "eval"];

export default function AdminPage() {
  const { me } = useRole();
  const queryClient = useQueryClient();
  const [roleFilter, setRoleFilter] = React.useState<Role | "">("");
  const [search, setSearch] = React.useState("");
  const [resetTarget, setResetTarget] = React.useState<UserOut | null>(null);
  const [newPassword, setNewPassword] = React.useState("");
  const [notice, setNotice] = React.useState<string | null>(null);
  const [problem, setProblem] = React.useState<string | null>(null);

  const users = useQuery({
    queryKey: ["admin-users", roleFilter],
    queryFn: () => api.adminUsers({ limit: 500, role: roleFilter || undefined }),
  });

  const overview = useQuery({
    queryKey: ["admin-overview"],
    queryFn: () => api.adminAudit({ limit: 1 }),
  });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof api.adminPatchUser>[1] }) =>
      api.adminPatchUser(id, body),
    onSuccess: (row) => {
      setNotice(`${row.username} updated.`);
      setProblem(null);
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (err) => {
      setProblem(err instanceof Error ? err.message : "The update failed.");
      setNotice(null);
    },
  });

  const visible = (users.data ?? []).filter((u) =>
    search ? u.username.toLowerCase().includes(search.toLowerCase()) : true
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1040px] space-y-4 px-6 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-base font-semibold tracking-tight">Users</h1>
          <p className="text-xs text-muted-foreground">
            Accounts, roles and access. {overview.data ? `${overview.data.summary.total ?? 0} audited actions` : ""}
          </p>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by username"
            aria-label="Filter accounts by username"
            className="ml-auto h-8 w-48 rounded-md border bg-background px-2 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
          />
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value as Role | "")}
            aria-label="Filter by role"
            className="h-8 rounded-md border bg-background px-2 text-[13px]"
          >
            <option value="">All roles</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>

        {notice && (
          <p role="status" className="rounded-lg border px-3.5 py-2.5 text-[13px]">
            {notice}
          </p>
        )}
        {problem && (
          <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-3.5 py-2.5 text-[13px]">
            {problem}
          </p>
        )}

        {users.error && (
          <p className="rounded-lg border px-3.5 py-2.5 text-[13px] text-[var(--destructive)]">
            {users.error instanceof Error ? users.error.message : "Accounts could not be read."}
          </p>
        )}

        {users.isPending && (
          <div className="space-y-2" aria-busy>
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-9 animate-pulse rounded-md bg-muted" />
            ))}
          </div>
        )}

        {visible.length > 0 && (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="border-b px-2 py-1.5 font-medium">Account</th>
                <th className="border-b px-2 py-1.5 font-medium">Role</th>
                <th className="border-b px-2 py-1.5 font-medium">Scope</th>
                <th className="border-b px-2 py-1.5 font-medium">Last login</th>
                <th className="border-b px-2 py-1.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((user) => (
                <tr key={user.id} className="align-middle">
                  <td className="border-b px-2 py-1.5">
                    <span className="font-medium">{user.username}</span>
                    {user.id === me?.user.id && (
                      <span className="ml-1 text-[11px] text-muted-foreground">(you)</span>
                    )}
                    <span className="block text-[11px] text-muted-foreground">{user.email}</span>
                  </td>
                  <td className="border-b px-2 py-1.5">
                    <select
                      value={user.role}
                      aria-label={`Role for ${user.username}`}
                      onChange={(e) =>
                        patch.mutate({ id: user.id, body: { role: e.target.value as Role } })
                      }
                      className="h-7 rounded border bg-background px-1 text-[12px] capitalize"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="border-b px-2 py-1.5 text-muted-foreground">
                    {user.student_id ?? user.department ?? "—"}
                  </td>
                  <td className="border-b px-2 py-1.5 tabular-nums text-muted-foreground">
                    {user.last_login ? user.last_login.slice(0, 16).replace("T", " ") : "never"}
                  </td>
                  <td className="border-b px-2 py-1.5 text-right">
                    <div className="flex justify-end gap-1.5">
                      <button
                        onClick={() =>
                          patch.mutate({ id: user.id, body: { is_active: !user.is_active } })
                        }
                        className="rounded border px-2 py-1 text-[12px] hover:border-[var(--accent)]"
                      >
                        {user.is_active ? "Disable" : "Enable"}
                      </button>
                      <button
                        onClick={() => {
                          setResetTarget(user);
                          setNewPassword("");
                        }}
                        className="rounded border px-2 py-1 text-[12px] hover:border-[var(--accent)]"
                      >
                        Reset password
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {resetTarget && (
          <div className="rounded-lg border bg-card p-4">
            <h2 className="text-[13px] font-medium">
              Reset password for {resetTarget.username}
            </h2>
            <p className="mt-1 text-[12px] text-muted-foreground">
              This also ends every session that account currently holds.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="New password (8+ characters)"
                aria-label="New password"
                autoComplete="new-password"
                className="h-8 w-64 rounded-md border bg-background px-2 text-[13px]"
              />
              <button
                disabled={newPassword.length < 8}
                onClick={() => {
                  patch.mutate(
                    { id: resetTarget.id, body: { password: newPassword } },
                    {
                      onSuccess: () => {
                        setResetTarget(null);
                        setNewPassword("");
                      },
                    }
                  );
                }}
                className="h-8 rounded-md border px-3 text-[13px] hover:border-[var(--accent)] disabled:opacity-50"
              >
                Save
              </button>
              <button
                onClick={() => setResetTarget(null)}
                className="h-8 rounded-md px-3 text-[13px] text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
