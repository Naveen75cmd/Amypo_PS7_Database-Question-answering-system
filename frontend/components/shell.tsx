"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
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
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useRole } from "@/components/providers";

const NAV = [
  { href: "/", label: "Chat", icon: IconMessages },
  { href: "/placement", label: "Placement", icon: IconTarget },
  { href: "/dashboard", label: "Dashboard", icon: IconDashboard },
  { href: "/knowledge", label: "Knowledge", icon: IconBook2 },
  { href: "/evaluation", label: "Evaluation", icon: IconChecklist },
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

function RoleSwitcher() {
  const { role, setRole } = useRole();
  return (
    <div
      role="radiogroup"
      aria-label="Demo role"
      className="flex overflow-hidden rounded-md border text-xs"
    >
      {(["student", "staff"] as const).map((r) => (
        <button
          key={r}
          role="radio"
          aria-checked={role === r}
          onClick={() => setRole(r)}
          className={cn(
            "px-2.5 py-1.5 capitalize transition-colors duration-150",
            role === r
              ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
              : "bg-card text-muted-foreground hover:text-foreground"
          )}
        >
          {r}
        </button>
      ))}
    </div>
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

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = React.useState(false);

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
          {NAV.map(({ href, label, icon: Icon }) => {
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
          <span className="text-[13px] text-muted-foreground">Policy &amp; Placement Copilot</span>
          <div className="ml-auto flex items-center gap-2">
            <ResourcePill />
            <RoleSwitcher />
            <ThemeToggle />
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
      </div>
    </div>
  );
}
