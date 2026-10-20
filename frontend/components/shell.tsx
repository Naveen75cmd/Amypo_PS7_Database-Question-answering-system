"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  IconLayoutSidebar,
  IconLayoutSidebarRightCollapse,
  IconSun,
  IconMoonStars,
  IconDashboard,
  IconMessages,
  IconTarget,
  IconBook2,
  IconChecklist,
  IconShieldLock,
  IconLogout,
  IconUsers,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useRole } from "@/components/providers";

type Permission =
  | "chat"
  | "placement_cohort"
  | "placement_own"
  | "monitoring_read"
  | "monitoring_full"
  | "ingest"
  | "eval_view"
  | "eval_run"
  | "audit_log"
  | "user_admin";

/** Navigation is a view of the capability list, never a separate rule set. */
const NAV: Array<{
  href: string;
  label: string;
  icon: typeof IconMessages;
  any: Permission[];
}> = [
  { href: "/", label: "Chat", icon: IconMessages, any: ["chat"] },
  {
    href: "/placement",
    label: "Placement",
    icon: IconTarget,
    any: ["placement_own", "placement_cohort"],
  },
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: IconDashboard,
    any: ["monitoring_read", "monitoring_full"],
  },
  { href: "/knowledge", label: "Knowledge", icon: IconBook2, any: ["ingest"] },
  {
    href: "/evaluation",
    label: "Evaluation",
    icon: IconChecklist,
    any: ["eval_view", "eval_run"],
  },
  {
    href: "/audit",
    label: "Audit trail",
    icon: IconShieldLock,
    any: ["audit_log", "placement_cohort"],
  },
  { href: "/admin", label: "Users", icon: IconUsers, any: ["user_admin"] },
];

function ResourcePill() {
  const { data } = useQuery({
    queryKey: ["resource-status"],
    queryFn: api.resourceStatus,
    refetchInterval: 5_000,
  });
  if (!data) return null;
  const ollamaOk = data.ollama_status === "ok" || data.ollama_loaded;
  return (
    <Link
      href="/dashboard"
      className="hidden items-center gap-3 rounded-md border bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors duration-150 hover:text-foreground md:flex"
      title="Live resource status — opens the dashboard"
    >
      <span className="tabular-nums">RAM {data.ram_available_mb} MB</span>
      <span className="text-[var(--border)]">|</span>
      <span className="tabular-nums">{data.bandwidth_kbps} kbps</span>
      <span className="text-[var(--border)]">|</span>
      <span className="tabular-nums">quota {data.api_quota_remaining}</span>
      <span className="text-[var(--border)]">|</span>
      <span className="flex items-center gap-1">
        <span
          aria-hidden
          className={cn(
            "size-1.5 rounded-full",
            ollamaOk ? "bg-[var(--accent)]" : "bg-amber-500"
          )}
        />
        {ollamaOk ? "local model" : "offline mode"}
      </span>
    </Link>
  );
}

function ThemeToggle() {
  const [dark, setDark] = React.useState<boolean | null>(null);
  React.useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);
  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("amypo-theme", next ? "dark" : "light");
    } catch {
      /* private mode: the toggle still works for this session */
    }
  }
  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      className="grid size-8 place-items-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
    >
      {dark ? <IconSun size={16} /> : <IconMoonStars size={16} />}
    </button>
  );
}

function AccessDenied({ label }: { label: string }) {
  return (
    <div className="grid h-full place-items-center px-6">
      <div className="max-w-md rounded-lg border bg-card p-6">
        <h1 className="text-base font-semibold tracking-tight">Not permitted</h1>
        <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
          This account does not have access to {label}. Permission is decided by
          the role on your account, not by this page. If you need access, ask an
          administrator.
        </p>
      </div>
    </div>
  );
}

function UserChip() {
  const { me, signOut } = useRole();
  const [busy, setBusy] = React.useState(false);
  if (!me) return null;
  const who = me.user.student_id ?? me.user.username;
  return (
    <div className="flex items-center gap-2">
      <div className="hidden flex-col items-end leading-tight sm:flex" title={me.user.email}>
        <span className="text-[12px] font-medium">{who}</span>
        <span className="text-[11px] capitalize text-muted-foreground">
          {me.role}
          {me.departments.length ? ` · ${me.departments.join(", ")}` : ""}
        </span>
      </div>
      <button
        onClick={async () => {
          setBusy(true);
          try {
            await signOut();
          } finally {
            setBusy(false);
          }
        }}
        disabled={busy}
        className="flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-[12px] text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
        title="Sign out"
      >
        <IconLogout size={14} />
        <span className="hidden sm:inline">Sign out</span>
      </button>
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { ready, me, permissions } = useRole();
  const [collapsed, setCollapsed] = React.useState(false);

  // The login screen owns the whole viewport: no navigation, no header.
  if (pathname === "/login") return <main>{children}</main>;

  if (!ready) {
    return (
      <div className="grid h-dvh place-items-center bg-background text-[13px] text-muted-foreground">
        Loading session…
      </div>
    );
  }

  // Signed-out is already redirecting via AuthProvider; render nothing meanwhile
  // rather than flashing a page the user cannot read.
  if (!me) {
    return <div className="h-dvh bg-background" aria-busy="true" />;
  }

  const allowed = NAV.filter((item) => item.any.some((p) => permissions[p]));
  const current = NAV.find(
    (item) =>
      (item.href === "/" && pathname === "/") ||
      (item.href !== "/" && pathname.startsWith(item.href))
  );
  const denied =
    current !== undefined && !current.any.some((p) => permissions[p]);

  return (
    <div className="flex h-dvh overflow-hidden bg-background text-foreground">
      <nav
        aria-label="Primary"
        className={cn(
          "flex shrink-0 flex-col border-r bg-card transition-all duration-150",
          collapsed ? "w-12" : "w-48"
        )}
      >
        <div className="flex h-12 items-center gap-2 border-b px-3">
          <span className="grid size-6 shrink-0 place-items-center rounded bg-[var(--accent)] text-[11px] font-bold text-[var(--accent-foreground)]">
            A
          </span>
          {!collapsed && <span className="text-sm font-semibold tracking-tight">AMYPO</span>}
        </div>
        <ul className="flex-1 space-y-0.5 p-2">
          {allowed.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] transition-colors duration-150",
                    active
                      ? "bg-muted font-medium text-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                  title={collapsed ? label : undefined}
                >
                  <Icon size={16} className="shrink-0" />
                  {!collapsed && label}
                </Link>
              </li>
            );
          })}
        </ul>
        <button
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="m-2 grid size-8 place-items-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
        >
          {collapsed ? <IconLayoutSidebar size={16} /> : <IconLayoutSidebarRightCollapse size={16} />}
        </button>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card px-4">
          <button
            onClick={() => router.push("/")}
            className="text-[13px] text-muted-foreground hover:text-foreground"
          >
            Policy &amp; Placement Copilot
          </button>
          <div className="ml-auto flex items-center gap-2">
            <ResourcePill />
            <UserChip />
            <ThemeToggle />
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-hidden">
          {denied ? <AccessDenied label={current.label.toLowerCase()} /> : children}
        </main>
      </div>
    </div>
  );
}
