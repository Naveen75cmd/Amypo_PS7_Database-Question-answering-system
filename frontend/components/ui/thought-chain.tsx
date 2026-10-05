"use client";

/*
 * Adapted from the provided ThoughtChain component. Structure (collapsible
 * steps with status icons and items) is kept; the presentation is restyled to
 * the AMYPO design system: neutral palette, hairline connector, the accent
 * green for completed steps and a plain spinner for active ones. The shimmer
 * text effect was removed — motion is 150ms opacity/transform only.
 */

import React, { createContext, useContext, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Check, Loader2, Circle, ChevronDown } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

type Status = "done" | "active" | "pending" | "failed";

type StepContextType = {
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
  status: Status;
};

const StepContext = createContext<StepContextType | null>(null);

const statusStyles: Record<
  Status,
  { label: string; line: string; icon: string }
> = {
  done: {
    label: "text-muted-foreground",
    line: "bg-[var(--accent)]/30",
    icon: "",
  },
  active: {
    label: "text-foreground",
    line: "bg-[var(--border)]",
    icon: "text-[var(--accent)]",
  },
  pending: {
    label: "text-muted-foreground",
    line: "bg-[var(--border)]",
    icon: "text-muted-foreground",
  },
  failed: {
    label: "text-[var(--destructive)]",
    line: "bg-[var(--destructive)]/30",
    icon: "text-[var(--destructive)]",
  },
};

function StatusIcon({ status }: { status: Status }) {
  if (status === "done") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-[var(--accent)]">
        <Check className="size-3 text-[var(--accent-foreground)]" strokeWidth={3} />
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="flex size-5 items-center justify-center">
        <Loader2 className={cn("size-4 animate-spin", statusStyles.active.icon)} />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full border border-[var(--destructive)] text-xs font-semibold text-[var(--destructive)]">
        !
      </span>
    );
  }
  return <Circle className={cn("size-3.5", statusStyles.pending.icon)} />;
}

export function ThoughtChain({ children }: { children: React.ReactNode }) {
  const steps = React.Children.toArray(children);
  const total = steps.length;

  return (
    <div>
      {steps.map((step, index) =>
        React.isValidElement(step)
          ? React.cloneElement(step as React.ReactElement<{ _isLast?: boolean }>, {
              _isLast: index === total - 1,
            })
          : step
      )}
    </div>
  );
}

export function ThoughtChainStep({
  children,
  status = "pending",
  defaultOpen = true,
  _isLast = false,
}: {
  children: React.ReactNode;
  status?: Status;
  defaultOpen?: boolean;
  _isLast?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <StepContext.Provider value={{ open, setOpen, status }}>
      <Collapsible open={open} onOpenChange={setOpen}>
        <div className="flex gap-3">
          <div className="flex shrink-0 flex-col items-center">
            <span className="mt-0.5">
              <StatusIcon status={status} />
            </span>
            {!_isLast && (
              <span
                className={cn(
                  "mt-1.5 w-0.5 flex-1 rounded-sm",
                  statusStyles[status].line
                )}
              />
            )}
          </div>
          <div className={cn("flex-1", !_isLast && "pb-2")}>{children}</div>
        </div>
      </Collapsible>
    </StepContext.Provider>
  );
}

export function ThoughtChainTrigger({
  children,
  meta,
}: {
  children: React.ReactNode;
  /** Right-aligned detail, e.g. a measured duration. */
  meta?: string;
}) {
  const { open, status } = useContext(StepContext)!;

  return (
    <CollapsibleTrigger className="flex w-full cursor-pointer select-none items-center gap-1.5 outline-none">
      <span
        className={cn("text-[13px] font-semibold tracking-tight", statusStyles[status].label)}
      >
        {children}
      </span>
      {meta && (
        <span className="ml-auto pr-1 text-xs tabular-nums text-muted-foreground">
          {meta}
        </span>
      )}
      <motion.span
        animate={{ rotate: open ? 180 : 0 }}
        transition={{ duration: 0.15, ease: "easeInOut" }}
        className="flex items-center text-muted-foreground"
      >
        <ChevronDown className="size-3.5" />
      </motion.span>
    </CollapsibleTrigger>
  );
}

export function ThoughtChainContent({ children }: { children: React.ReactNode }) {
  const { open } = useContext(StepContext)!;

  return (
    <CollapsibleContent forceMount>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.15, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="mt-1 pl-0.5">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </CollapsibleContent>
  );
}

export function ThoughtChainItem({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 py-1">
      <span className="mt-[7px] size-1 shrink-0 rounded-full bg-muted-foreground/50" />
      <span className="text-[13px] leading-relaxed text-muted-foreground">
        {children}
      </span>
    </div>
  );
}

export default ThoughtChain;
