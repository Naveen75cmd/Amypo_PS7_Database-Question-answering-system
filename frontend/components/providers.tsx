"use client";

import * as React from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { api, ApiError, type MeResponse, type Permissions, type Role } from "@/lib/api";

/*
 * Identity comes from the server, never from a client-side switch.
 *
 * `GET /auth/me` is the only source of the role, the student id and the
 * capability list. The session itself is an httpOnly cookie, so there is no
 * token in memory or localStorage for this code to leak. Every capability the
 * UI hides is also enforced by a route dependency on the backend — hiding a
 * button is a convenience, not the control.
 */

export type AppRole = Role;

const EMPTY_PERMISSIONS: Permissions = {
  chat: false,
  own_records: false,
  staff_docs: false,
  admin_docs: false,
  placement_own: false,
  placement_cohort: false,
  placement_weights: false,
  criteria_edit: false,
  ingest: false,
  ingest_approve: false,
  user_admin: false,
  router_config: false,
  monitoring_full: false,
  monitoring_read: false,
  audit_log: false,
  eval_run: false,
  eval_view: false,
  simulator: false,
  service_account: false,
};

interface RoleContextValue {
  /** The signed-in role, or `null` while signed out. */
  role: AppRole | null;
  /** The student id behind the session, or "" for a non-student account. */
  userId: string;
  me: MeResponse | null;
  permissions: Permissions;
  ready: boolean;
  /** True when the last /auth/me said "not authenticated". */
  signedOut: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  reload: () => void;
}

const RoleContext = React.createContext<RoleContextValue | null>(null);

/**
 * Kept under its old name so existing pages keep compiling, but the value is
 * now read-only session state rather than a demo switch.
 */
export function useRole() {
  const ctx = React.useContext(RoleContext);
  if (!ctx) throw new Error("useRole must be used inside Providers");
  return ctx;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 5_000 } } })
  );
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();

  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
    staleTime: 60_000,
  });

  const signedOut = error instanceof ApiError && error.status === 401;
  const me = data ?? null;

  const signIn = React.useCallback(
    async (username: string, password: string) => {
      await api.login({ username, password });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    [queryClient]
  );

  const signOut = React.useCallback(async () => {
    try {
      await api.logout();
    } finally {
      queryClient.setQueryData(["me"], null);
      queryClient.removeQueries({ queryKey: ["me"] });
      router.push("/login");
    }
  }, [queryClient, router]);

  // A signed-out visitor on any page other than the login screen is sent there
  // with a `next` parameter, and returned to that page after signing in.
  React.useEffect(() => {
    if (signedOut && pathname !== "/login") {
      const next = encodeURIComponent(pathname || "/");
      router.replace(`/login?next=${next}`);
    }
  }, [signedOut, pathname, router]);

  const value: RoleContextValue = {
    role: me?.role ?? null,
    userId: me?.student_id ?? "",
    me,
    permissions: me?.permissions ?? EMPTY_PERMISSIONS,
    ready: !isPending,
    signedOut,
    signIn,
    signOut,
    reload: () => void refetch(),
  };

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

/**
 * Applies the theme class to <html>. System-aware; a stored override wins.
 * Only the boolean class lives in storage — no user data.
 */
export function ThemeScript() {
  const code = `try{var t=localStorage.getItem("amypo-theme");if(t==="dark"||(t!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches)){document.documentElement.classList.add("dark")}}catch(e){}`;
  return <script dangerouslySetInnerHTML={{ __html: code }} />;
}
