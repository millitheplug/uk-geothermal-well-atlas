"use client";

import * as React from "react";

import { AppHeader } from "@/components/layout/app-shell";
import { useApp } from "@/components/providers/app-provider";
import { cn } from "@/lib/utils";

/**
 * Page header wired to the session's mock-data flag.
 *
 * Every page uses this rather than composing `AppHeader` directly, so the
 * synthetic-data marker cannot be forgotten on a new page. That omission is
 * invisible in development and serious in a screenshot, which is precisely why
 * it is made impossible here.
 */
export function PageHeader({
  title,
  subtitle,
  actions,
  className,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  className?: string;
  /** Extra controls rendered in a second row under the title. */
  children?: React.ReactNode;
}) {
  const { isMock, health } = useApp();

  return (
    <AppHeader
      title={title}
      subtitle={subtitle}
      actions={actions}
      isMock={isMock}
      className={cn("shrink-0", className)}
    >
      {children}
    </AppHeader>
  );
}

/** Health readout shown on pages that talk about the platform itself. */
export function EnvironmentStrip() {
  const { health } = useApp();
  if (!health) return null;

  const items: Array<{ label: string; value: string; hint?: string }> = [
    { label: "Version", value: health.version },
    { label: "Environment", value: health.environment },
    { label: "Database", value: health.database },
    { label: "Spatial", value: health.spatial_dialect },
    { label: "Queue", value: health.redis },
    {
      label: "Interpretation",
      value: health.llm,
      hint:
        health.llm === "mock"
          ? "A language model is not configured, so agent text is produced deterministically from the calculation results. No figures change."
          : "A language model may only explain the deterministic results. It cannot compute them.",
    },
  ];

  return (
    <dl className="flex flex-wrap gap-x-5 gap-y-1 text-[12px]">
      {items.map((item) => (
        <div key={item.label} className="flex items-baseline gap-1">
          <dt className="text-muted-foreground">{item.label}</dt>
          <dd
            className="font-mono font-medium"
            title={item.hint}
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}