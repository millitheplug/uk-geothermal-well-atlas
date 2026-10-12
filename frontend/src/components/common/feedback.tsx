/**
 * Shared feedback and layout primitives.
 *
 * Three rules these components exist to enforce:
 *
 * 1. A loading state is never a blank screen. The user is told what is being
 *    loaded and why it takes time.
 * 2. An error state always says what to do next, and never silently retries.
 * 3. A missing value reads as missing. There is no `--` fallback anywhere in
 *    here that could be mistaken for a zero.
 */

"use client";

import * as React from "react";
import {
  AlertTriangle,
  Inbox,
  Loader2,
  RefreshCw,
  ServerOff,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Full-block loading state with an explanation of the work in progress. */
export function Loading({
  label = "Loading",
  detail,
  className,
  compact = false,
}: {
  label?: string;
  detail?: string;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col items-center justify-center gap-2 text-center",
        compact ? "py-6" : "py-16",
        className,
      )}
    >
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">{label}</p>
      {detail && (
        <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
          {detail}
        </p>
      )}
    </div>
  );
}

/** Placeholder block used while a panel loads. */
export function PanelSkeleton({ className }: { className?: string }) {
  return <div className={cn("shimmer h-24 rounded-md", className)} aria-hidden />;
}

export function ErrorState({
  title = "Could not load this view",
  message,
  hint,
  onRetry,
  isOffline,
  className,
}: {
  title?: string;
  message?: string | null;
  hint?: string;
  onRetry?: () => void;
  /** True when the API could not be reached at all, which needs a different fix. */
  isOffline?: boolean;
  className?: string;
}) {
  const Icon = isOffline ? ServerOff : AlertTriangle;

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-4",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 shrink-0 text-destructive" aria-hidden />
        <p className="text-sm font-semibold text-destructive">{title}</p>
      </div>
      {message && <p className="text-xs leading-relaxed">{message}</p>}
      {hint && <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>}
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  title = "Nothing to show",
  message,
  action,
  className,
}: {
  title?: string;
  message?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-md border border-dashed py-12 text-center",
        className,
      )}
    >
      <Inbox className="h-5 w-5 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">{title}</p>
      {message && (
        <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
          {message}
        </p>
      )}
      {action}
    </div>
  );
}

/**
 * A headline figure tile.
 *
 * `status` is optional, and when the figure is an estimate or an assumption it
 * should be passed: the tile refuses to show an estimated number without its
 * provenance label.
 */
export function StatTile({
  label,
  value,
  unit,
  status,
  sub,
  tone,
  className,
  href,
}: {
  label: string;
  value: string;
  unit?: string;
  status?: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "default" | "muted" | "warning" | "danger";
  className?: string;
  href?: string;
}) {
  const toneClass =
    tone === "danger"
      ? "text-destructive"
      : tone === "warning"
        ? "text-priority-medium"
        : tone === "muted"
          ? "text-muted-foreground"
          : "";

  const inner = (
    <>
      <div className="text-xs font-medium leading-snug text-muted-foreground">
        {label}
      </div>
      <div className={cn("mt-1.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-1", toneClass)}>
        {/* A figure gets the condensed display face; a phrase such as
            "Not available" stays in the ordinary face so it never reads as a
            number and never overflows a narrow column. */}
        <span
          className={cn(
            "tabular min-w-0 break-words",
            /\d/.test(value)
              ? "font-display text-[1.875rem] sm:text-[2.125rem]"
              : "text-lg font-semibold leading-tight",
          )}
        >
          {value}
        </span>
        {unit && (
          <span className="text-sm font-normal text-muted-foreground">{unit}</span>
        )}
        {status}
      </div>
      {sub && (
        <div className="voice-note mt-2 text-[0.8125rem] text-muted-foreground">
          {sub}
        </div>
      )}
    </>
  );

  const class_ = cn(
    "block min-w-0 border-l-2 border-foreground/20 py-0.5 pl-3.5 pr-1",
    href && "transition-colors hover:border-accent",
    className,
  );

  if (href) {
    return (
      <a href={href} className={class_}>
        {inner}
      </a>
    );
  }

  return <div className={class_}>{inner}</div>;
}

/** Grid of stat tiles. */
export function StatGrid({
  children,
  cols = 4,
  className,
}: {
  children: React.ReactNode;
  cols?: 2 | 3 | 4 | 5;
  className?: string;
}) {
  // Two columns even on a phone: a readout reads better as pairs than as a
  // long single column, and every figure stays above the fold.
  const colsClass =
    cols === 2
      ? ""
      : cols === 3
        ? "sm:grid-cols-3"
        : cols === 5
          ? "sm:grid-cols-3 xl:grid-cols-5"
          : "lg:grid-cols-4";
  return (
    <div className={cn("grid grid-cols-2 gap-x-4 gap-y-6", colsClass, className)}>
      {children}
    </div>
  );
}

/**
 * Definition list of label/value pairs, where "Not available" is styled
 * explicitly rather than left to look like a real value.
 */
export function KeyValueList({
  items,
  className,
  dense = false,
}: {
  items: Array<{
    label: string;
    value: React.ReactNode;
    hint?: string;
    missing?: boolean;
  }>;
  className?: string;
  dense?: boolean;
}) {
  return (
    <dl className={cn("divide-y", className)}>
      {items.map((item, index) => (
        <div
          key={index}
          className={cn(
            "flex items-baseline justify-between gap-3",
            dense ? "py-1" : "py-2",
          )}
        >
          <dt className="shrink-0 text-muted-foreground">
            {item.label}
            {item.hint && (
              <span className="ml-1 text-[12px] opacity-70">({item.hint})</span>
            )}
          </dt>
          <dd
            className={cn(
              "min-w-0 text-right",
              item.missing && "italic text-muted-foreground",
            )}
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Section header used inside cards and panels. */
export function SectionTitle({
  children,
  action,
  className,
}: {
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-2 border-b pb-2",
        className,
      )}
    >
      <h3 className="text-sm font-semibold tracking-tight text-foreground">
        {children}
      </h3>
      {action}
    </div>
  );
}

/**
 * Caveat block.
 *
 * Used for the limitations the backend returns alongside a result. These are
 * not decoration: a national capacity total that ignores the wells with no
 * temperature measurement is misleading without the sentence saying so.
 */
export function Caveats({
  items,
  title = "Caveats",
  className,
}: {
  items: string[];
  title?: string;
  className?: string;
}) {
  if (!items || items.length === 0) return null;
  return (
    <Card className={cn("border-dashed bg-transparent", className)}>
      <CardContent className="p-3.5 sm:p-4">
        <SectionTitle>{title}</SectionTitle>
        <ul className="voice-note mt-2 space-y-1.5 text-[0.8125rem] text-muted-foreground">
          {items.map((item, index) => (
            <li key={index} className="flex gap-1.5">
              <span aria-hidden>·</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/** Prose wrapper for markdown-ish report content, without a markdown parser. */
export function Prose({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "voice-note space-y-3 text-[0.9375rem] [&_h1]:font-sans [&_h2]:font-sans [&_h3]:font-sans [&_table]:font-sans [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-5 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:border-b [&_h2]:pb-1 [&_h3]:mt-4 [&_h3]:text-sm [&_h3]:font-semibold [&_li]:ml-4 [&_li]:list-disc [&_ol_li]:list-decimal [&_p]:text-muted-foreground [&_strong]:text-foreground [&_table]:w-full [&_table]:text-xs [&_td]:border [&_td]:p-1.5 [&_th]:border [&_th]:p-1.5 [&_th]:text-left [&_th]:font-semibold",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Page-level notice shown above content, e.g. the mock-data watermark. */
export function Notice({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: "info" | "warning" | "danger";
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const toneClass =
    tone === "danger"
      ? "border-destructive/25 border-l-destructive bg-destructive/[0.06]"
      : tone === "warning"
        ? "border-priority-medium/30 border-l-priority-medium bg-priority-medium/[0.07]"
        : "border-border border-l-primary/60 bg-card";
  const iconClass =
    tone === "danger"
      ? "text-destructive"
      : tone === "warning"
        ? "text-priority-medium"
        : "text-primary";
  const Icon = tone === "info" ? Inbox : AlertTriangle;

  return (
    <div
      role={tone === "info" ? undefined : "note"}
      className={cn("rounded-md border border-l-4 p-3.5", toneClass, className)}
    >
      <div className="flex items-start gap-2.5">
        <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", iconClass)} aria-hidden />
        <div className="min-w-0 text-sm leading-relaxed">
          {title && <p className="font-semibold text-foreground">{title}</p>}
          <div className={cn(title && "mt-0.5", "voice-note text-[0.875rem] text-foreground/85")}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}