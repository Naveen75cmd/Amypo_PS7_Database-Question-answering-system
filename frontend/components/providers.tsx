"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/*
 * The role switcher is a demo affordance only: the backend still enforces
 * access control on every request, so flipping to Staff simply shows what a
 * staff account would see for cohort queries.
 */

export type AppRole = "student" | "staff";

interface RoleContextValue {
  role: AppRole;
  setRole: (role: AppRole) => void;
  userId: string;
  setUserId: (id: string) => void;
}

const RoleContext = React.createContext<RoleContextValue | null>(null);

export function useRole() {
  const ctx = React.useContext(RoleContext);
  if (!ctx) throw new Error("useRole must be used inside Providers");
  return ctx;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 5_000 } } })
  );
  const [role, setRole] = React.useState<AppRole>("staff");
  const [userId, setUserId] = React.useState("S102");

  return (
    <QueryClientProvider client={client}>
      <RoleContext.Provider value={{ role, setRole, userId, setUserId }}>
        {children}
      </RoleContext.Provider>
    </QueryClientProvider>
  );
}

/**
 * Applies the theme class to <html>. System-aware; a stored override wins.
 * Only the boolean class lives in storage — no user data.
 */
export function ThemeScript() {
  const code = `try{var t=localStorage.getItem("amypo-theme");if(t==="dark"||(t!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches)){document.documentElement.classList.add("dark")}}catch(e){}`;
  return <script dangerouslySetInnerHTML={{ __html: code }} />;
}
