/**
 * The three composable UI primitives the whole interface is built from.
 *
 * All three exist to serve one requirement: every figure carries its provenance
 * label inline. A badge in the flow of the value - not in a tooltip, not in a
 * legend the user has to find - is what stops an estimate being read as a
 * measurement.
 */

"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import {
  AlertTriangle,
  Calculator,
  CircleDashed,
  ClipboardCheck,
  FileText,
  FlaskConical,
  HelpCircle,
  Ruler,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { EPISTEMIC_META } from "@/lib/domain";
import type { EpistemicStatus } from "@/types/api";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[12px] font-semibold transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        muted: "border-transparent bg-muted text-muted-foreground",
      },
      size: {
        default: "px-2.5 py-1 text-xs",
        sm: "px-1.5 py-0 text-[11px]",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, size, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant, size }), className)} {...props} />
  );
}

/** Icon per epistemic status, so status is never carried by colour alone. */
const EPISTEMIC_ICONS: Record<EpistemicStatus, LucideIcon> = {
  FACT: FileText,
  MEASURED: Ruler,
  DERIVED: Calculator,
  MODELLED: FlaskConical,
  ESTIMATE: AlertTriangle,
  ASSUMPTION: CircleDashed,
  UNKNOWN: HelpCircle,
};

export interface EpistemicBadgeProps {
  status: EpistemicStatus;
  /** Show the full word rather than the three-letter abbreviation. */
  expanded?: boolean;
  /** Render a tooltip with the full explanation. */
  withTooltip?: boolean;
  className?: string;
}

/**
 * The provenance label for a figure.
 *
 * `UNKNOWN` is rendered as an explicit "unknown" rather than a blank, because a
 * blank reads as an oversight and an unknown is a finding. This is the single
 * component that guarantees it.
 */
export function EpistemicBadge({
  status,
  expanded = false,
  withTooltip = true,
  className,
}: EpistemicBadgeProps) {
  const meta = EPISTEMIC_META[status];
  const Icon = EPISTEMIC_ICONS[status];

  const badge = (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-sm border px-1.5 py-[3px] align-middle text-[11px] font-semibold uppercase leading-none tracking-wide",
        meta.className,
        className,
      )}
      title={withTooltip ? `${meta.label}: ${meta.description}` : undefined}
      aria-label={`${meta.label}. ${meta.description}`}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {expanded ? meta.label : meta.short}
    </span>
  );

  return badge;
}

/**
 * A figure with its unit and provenance label.
 *
 * The value, the unit and the badge sit together. When the value is unknown the
 * unit is dropped too - "Not available kW" is noise, and the absence of a unit
 * is itself a signal that there is no figure.
 */
export interface MeasuredValueProps {
  value: number | string | null | undefined;
  unit?: string;
  status: EpistemicStatus;
  /** Formatter applied to numeric values. */
  format?: (value: number) => string;
  decimals?: number;
  className?: string;
  /** Show the badge even when the value is unknown. Defaults to true. */
  showBadge?: boolean;
  compact?: boolean;
}

export function MeasuredValue({
  value,
  unit,
  status,
  format,
  decimals = 0,
  className,
  showBadge = true,
  compact = false,
}: MeasuredValueProps) {
  const isNumeric = typeof value === "number" && Number.isFinite(value);

  const display = !isNumeric && value !== null && value !== undefined && value !== ""
    ? String(value)
    : isNumeric && format
      ? format(value as number)
      : isNumeric
        ? (value as number).toLocaleString("en-GB", {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
          })
        : "Not available";

  const unavailable = display === "Not available";

  return (
    <span
      className={cn(
        "inline-flex items-baseline gap-1.5 whitespace-nowrap",
        compact && "text-xs",
        className,
      )}
    >
      <span
        className={cn(
          "tabular font-medium",
          unavailable && "text-muted-foreground italic",
        )}
      >
        {display}
        {!unavailable && unit && (
          <span className="ml-0.5 text-[0.85em] font-normal text-muted-foreground">
            {unit}
          </span>
        )}
      </span>
      {showBadge && <EpistemicBadge status={status} />}
    </span>
  );
}

/**
 * Banner shown when the current view contains synthetic development data.
 *
 * Rendered at the top of any view drawing on mock datasets. The requirement it
 * enforces is that no screenshot or shared view of development data can be
 * mistaken for production analysis.
 */
export function MockDataBanner({
  isMock,
  className,
  what = "these figures",
}: {
  isMock: boolean;
  className?: string;
  what?: string;
}) {
  if (!isMock) return null;

  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-md border border-l-[6px] border-destructive/30 border-l-destructive bg-destructive/10 px-3.5 py-3 text-sm",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 h-[18px] w-[18px] shrink-0 text-destructive" aria-hidden />
      <div className="min-w-0">
        <p className="font-semibold text-destructive">
          Synthetic development data
        </p>
        <p className="voice-note mt-1 text-[0.875rem] text-foreground/90">
          {what.charAt(0).toUpperCase() + what.slice(1)} come from a development
          dataset. No well shown here corresponds to a real UK borehole, and
          nothing on this screen may be presented as production well data.
        </p>
      </div>
    </div>
  );
}

/** Inline checklist confirming the evidence guarantees the platform makes. */
export function EvidenceDisclaimer({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "voice-note flex items-start gap-2.5 rounded-md border border-dashed border-border px-3.5 py-2.5 text-[0.8125rem] text-muted-foreground",
        className,
      )}
    >
      <ClipboardCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <p>
        This is a <strong className="text-foreground">screening analysis</strong>,
        not a statement of commercial viability. Every figure carries a provenance
        label, and all engineering calculations are performed in Python by the
        deterministic engine. A language model may explain these results but
        cannot compute them, alter them, or set the feasibility score.
      </p>
    </div>
  );
}
