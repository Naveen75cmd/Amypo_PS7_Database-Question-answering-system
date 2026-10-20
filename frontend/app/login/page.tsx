"use client";

import * as React from "react";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { IconEye, IconEyeOff, IconLock } from "@tabler/icons-react";
import { api, ApiError } from "@/lib/api";
import { useRole } from "@/components/providers";
import { cn } from "@/lib/utils";

/*
 * The only entry point. Everything else redirects here without a session and
 * comes back to the page the user wanted afterwards.
 *
 * There is deliberately no role picker: the account decides the role, and the
 * backend reads it from the signed token. A picker here would be a lie the
 * server would ignore.
 */

type Phase = "idle" | "loading" | "error";

const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE !== "false";
const DEMO_PASSWORD = "amypo-demo-2026";

const DEMO_ACCOUNTS = [
  { label: "Admin", username: "admin", blurb: "Users, ingestion, router, audit" },
  { label: "Staff", username: "staff.cse", blurb: "CSE cohort and staff documents" },
  { label: "Student", username: "s102", blurb: "Own records and own placement" },
] as const;

function messageFor(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Incorrect username or password.";
    if (err.status === 403) return err.message || "This account is disabled.";
    if (err.status === 429) {
      return "Too many failed attempts. Wait a few minutes and try again.";
    }
    if (err.status >= 500) return "The backend is not responding properly. Try again.";
  }
  return "Cannot reach the backend. Check that the API is running, then retry.";
}

export default function LoginPage() {
  // useSearchParams needs a Suspense boundary during prerendering; the form is
  // the only part that reads it.
  return (
    <Suspense fallback={<div className="h-dvh bg-background" aria-busy="true" />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { signIn } = useRole();

  const next = params.get("next") || "";
  const expired = params.get("expired") === "1";

  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [message, setMessage] = React.useState<string | null>(null);
  const [forgotOpen, setForgotOpen] = React.useState(false);
  const [demoOpen, setDemoOpen] = React.useState(false);
  const usernameRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (phase === "loading") return;
    setPhase("loading");
    setMessage(null);
    try {
      await signIn(username.trim(), password);
      const me = await api.me();
      const fallback = me.role === "admin" ? "/dashboard" : "/";
      router.replace(next && next.startsWith("/") ? next : fallback);
    } catch (err) {
      setPhase("error");
      setMessage(messageFor(err));
    }
  }

  function fill(account: string) {
    setUsername(account);
    setPassword(DEMO_PASSWORD);
    setPhase("idle");
    setMessage(null);
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-4 py-10 text-foreground">
      <div className="grid w-full max-w-3xl gap-8 md:grid-cols-[1fr_1.1fr] md:items-center">
        {/* Quiet brand panel — a factual line, no illustration. */}
        <div className="hidden md:block">
          <span className="grid size-9 place-items-center rounded bg-[var(--accent)] text-sm font-bold text-[var(--accent-foreground)]">
            A
          </span>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">AMYPO</h1>
          <p className="mt-2 max-w-xs text-[14px] leading-relaxed text-muted-foreground">
            Answers from AMYPO&rsquo;s own records. Runs offline.
          </p>
          <ul className="mt-6 space-y-2 text-[13px] text-muted-foreground">
            <li>Every claim cites the record it came from.</li>
            <li>Your role decides what you can see.</li>
            <li>Nothing leaves this machine.</li>
          </ul>
        </div>

        <div className="rounded-lg border bg-card p-6 shadow-sm md:p-7">
          <div className="mb-6 md:hidden">
            <h1 className="text-lg font-semibold tracking-tight">AMYPO</h1>
            <p className="mt-1 text-[13px] text-muted-foreground">
              Answers from AMYPO&rsquo;s own records. Runs offline.
            </p>
          </div>

          <h2 className="text-base font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Use the account your department issued.
          </p>

          {expired && (
            <p
              role="status"
              className="mt-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[13px]"
            >
              Your session expired. Sign in again to continue.
            </p>
          )}

          <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
            <div className="space-y-1.5">
              <label htmlFor="username" className="text-[13px] font-medium">
                Email or username
              </label>
              <input
                id="username"
                ref={usernameRef}
                name="username"
                type="text"
                autoComplete="username"
                spellCheck={false}
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                aria-invalid={phase === "error" ? true : undefined}
                aria-describedby={message ? "login-error" : undefined}
                className="h-9 w-full rounded-md border bg-background px-3 text-[14px] outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
              />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-baseline justify-between">
                <label htmlFor="password" className="text-[13px] font-medium">
                  Password
                </label>
                <button
                  type="button"
                  onClick={() => setForgotOpen((v) => !v)}
                  className="text-[12px] text-muted-foreground underline-offset-2 hover:underline"
                  aria-expanded={forgotOpen}
                >
                  Forgot password?
                </button>
              </div>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-invalid={phase === "error" ? true : undefined}
                  aria-describedby={message ? "login-error" : undefined}
                  className="h-9 w-full rounded-md border bg-background px-3 pr-10 text-[14px] outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  className="absolute inset-y-0 right-0 grid w-9 place-items-center text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? <IconEyeOff size={16} /> : <IconEye size={16} />}
                </button>
              </div>
            </div>

            {forgotOpen && (
              <p className="rounded-md border bg-muted/40 px-3 py-2 text-[12px] text-muted-foreground">
                Passwords are reset by an administrator, because this system runs
                offline and cannot send email. Ask your department administrator to
                reset it from the admin console.
              </p>
            )}

            {message && (
              <p
                id="login-error"
                role="alert"
                className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-[13px]"
              >
                {message}
              </p>
            )}

            <button
              type="submit"
              disabled={phase === "loading"}
              className={cn(
                "inline-flex h-9 w-full items-center justify-center gap-2 rounded-md bg-[var(--accent)] px-4 text-[14px] font-medium text-[var(--accent-foreground)] transition-opacity duration-150",
                phase === "loading" && "opacity-70"
              )}
            >
              {phase === "loading" ? (
                <>
                  <IconLock size={15} className="animate-pulse" />
                  Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </button>
          </form>

          {DEMO_MODE && (
            <section className="mt-5 border-t pt-4">
              <button
                type="button"
                onClick={() => setDemoOpen((v) => !v)}
                aria-expanded={demoOpen}
                className="text-[12px] text-muted-foreground underline-offset-2 hover:underline"
              >
                {demoOpen ? "Hide demo accounts" : "Demo accounts"}
              </button>
              {demoOpen && (
                <div className="mt-2 space-y-1.5">
                  {DEMO_ACCOUNTS.map((account) => (
                    <button
                      key={account.username}
                      type="button"
                      onClick={() => fill(account.username)}
                      className="flex w-full items-baseline justify-between gap-3 rounded-md border bg-background px-3 py-2 text-left text-[13px] hover:border-[var(--accent)]"
                    >
                      <span className="font-medium">{account.label}</span>
                      <span className="text-[12px] text-muted-foreground">
                        {account.blurb}
                      </span>
                    </button>
                  ))}
                  <p className="px-1 pt-1 text-[11px] text-muted-foreground">
                    Fills the credentials for the demo dataset. The password is
                    shared by the demo accounts and only exists when the backend
                    runs with AMYPO_DEMO_MODE=true.
                  </p>
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
