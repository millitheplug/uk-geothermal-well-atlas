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
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className={cn("mt-1 flex items-baseline gap-1.5", toneClass)}>
        <span className="tabular text-2xl font-semibold leading-none">{value}</span>
        {unit && (
          <span className="text-xs font-normal text-muted-foreground">{unit}</span>
        )}
        {status}
      </div>
      {sub && <div className="mt-1.5 text-[11px] text-muted-foreground">{sub}</div>}
    </>
  );

  const class_ = cn(
    "rounded-md border bg-card p-3",
    href && "transition-colors hover:bg-muted/50",
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
  const colsClass =
    cols === 2
      ? "sm:grid-cols-2"
      : cols === 3
        ? "sm:grid-cols-2 lg:grid-cols-3"
        : cols === 5
          ? "sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5"
          : "sm:grid-cols-2 lg:grid-cols-4";
  return (
    <div className={cn("grid grid-cols-1 gap-3", colsClass, className)}>
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
            dense ? "py-1" : "py-1.5",
          )}
        >
          <dt className="shrink-0 text-muted-foreground">
            {item.label}
            {item.hint && (
              <span className="ml-1 text-[10px] opacity-70">({item.hint})</span>
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
        "flex items-center justify-between gap-2 border-b pb-1.5",
        className,
      )}
    >
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
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
    <Card className={cn("bg-muted/40", className)}>
      <CardContent className="p-3">
        <SectionTitle>{title}</SectionTitle>
        <ul className="mt-1.5 space-y-1 text-[11px] leading-relaxed text-muted-foreground">
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
        "space-y-3 text-sm leading-relaxed [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-5 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:border-b [&_h2]:pb-1 [&_h3]:mt-4 [&_h3]:text-sm [&_h3]:font-semibold [&_li]:ml-4 [&_li]:list-disc [&_ol_li]:list-decimal [&_p]:text-muted-foreground [&_strong]:text-foreground [&_table]:w-full [&_table]:text-xs [&_td]:border [&_td]:p-1.5 [&_th]:border [&_th]:p-1.5 [&_th]:text-left [&_th]:font-semibold",
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
      ? "border-destructive/40 bg-destructive/5 text-destructive"
      : tone === "warning"
        ? "border-priority-medium/40 bg-priority-medium/5 text-priority-medium"
        : "border-border bg-muted/50 text-foreground";
  const Icon = tone === "info" ? Inbox : AlertTriangle;

  return (
    <div className={cn("rounded-md border p-3", toneClass, className)}>
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <div className="min-w-0 text-xs leading-relaxed">
          {title && <p className="font-semibold">{title}</p>}
          <div className={cn(title && "mt-0.5", "text-foreground/80")}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}