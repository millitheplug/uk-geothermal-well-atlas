"use client";

import { AlertTriangle, CheckCircle2, HelpCircle, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EvidenceDisclaimer } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { EpistemicBadge } from "@/components/ui/badge";
import { MeasuredValue } from "@/components/ui/badge";
import {
  RECOMMENDATION_META,
  STAGE_LABELS,
  formatEnergy,
  formatGBP,
  formatPower,
  formatTemperature,
} from "@/lib/domain";
import type { AnalysisResult, Recommendation } from "@/types/api";

/**
 * Recommendation display.
 *
 * Always renders the explanation alongside the level. A bare "HIGH PRIORITY"
 * is not actionable on its own, and the platform's whole claim is that the
 * recommendation follows deterministically from the score - which is only
 * checkable if the reasoning is shown.
 */
export function RecommendationBadge({
  recommendation,
  rationale,
  className,
}: {
  recommendation: Recommendation | null;
  rationale?: string[];
  className?: string;
}) {
  if (!recommendation) return null;
  const meta = RECOMMENDATION_META[recommendation];

  return (
    <div className={className}>
      <Badge className={meta.className}>{recommendation}</Badge>
      {rationale && rationale.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
          {rationale.slice(0, 3).map((reason, index) => (
            <li key={index} className="flex gap-1.5">
              <span aria-hidden>·</span>
              <span>{reason}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1.5 text-xs text-muted-foreground italic">{meta.tone}</p>
    </div>
  );
}

/**
 * The headline result card: score, confidence, recommendation, next action.
 *
 * Score and confidence are shown side by side but never combined. A high score
 * on weak evidence is the case this platform most needs to get right, and
 * merging the two into a single number would hide it.
 */
export function FeasibilityHeadline({
  result,
}: {
  result: AnalysisResult;
}) {
  const recommendation = RECOMMENDATION_META[result.recommendation];

  return (
    <div className="grid gap-4 lg:grid-cols-[auto_1fr]">
      {/* Score dial */}
      <div className="flex items-center gap-5">
        <ScoreDial score={result.feasibility_score} />
        <div className="space-y-2.5">
          <div>
            <div className="text-[12px] font-semibold text-muted-foreground">
              Evidence confidence
            </div>
            <div className="flex items-center gap-2">
              <span className="tabular text-2xl font-semibold">
                {Math.round(result.confidence_score * 100)}%
              </span>
              <Badge variant="outline" className="text-[12px]">
                {result.confidence_band.replace("_", " ")}
              </Badge>
            </div>
          </div>
          <p className="max-w-[15rem] text-xs leading-relaxed text-muted-foreground">
            Confidence measures the <em>evidence</em>, not the resource. A well
            can be an excellent candidate that nobody has measured.
          </p>
        </div>
      </div>

      {/* Recommendation and next action */}
      <div className="flex flex-col justify-between gap-3 border-t pt-3 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
        <div>
          <div className="text-[12px] font-semibold text-muted-foreground">
            Recommendation
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Badge className={recommendation.className}>
              {result.recommendation}
            </Badge>
            <span className="text-xs text-muted-foreground">{recommendation.tone}</span>
          </div>
          {result.recommendation_rationale.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
              {result.recommendation_rationale.slice(0, 4).map((reason, index) => (
                <li key={index} className="flex gap-1.5">
                  <span aria-hidden>·</span>
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-md border border-primary/30 bg-primary/5 p-3">
          <div className="flex items-center gap-1.5 text-[12px] font-semibold text-primary">
            <CheckCircle2 className="h-3 w-3" aria-hidden />
            Next action
          </div>
          <p className="mt-1 text-sm leading-relaxed">{result.next_action}</p>
        </div>
      </div>
    </div>
  );
}

/** Circular score indicator with the score and its status label. */
export function ScoreDial({
  score,
  size = 120,
}: {
  score: number;
  size?: number;
}) {
  const radius = size / 2 - 10;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(100, score)) / 100;

  // Same ordered ramp as the map, so the dial and the marker agree.
  const colour =
    score >= 80
      ? "hsl(var(--score-100))"
      : score >= 60
        ? "hsl(var(--score-80))"
        : score >= 40
          ? "hsl(var(--score-60))"
          : score >= 20
            ? "hsl(var(--score-40))"
            : "hsl(var(--score-20))";

  return (
    <div
      className="relative shrink-0"
      role="img"
      aria-label={`Feasibility score ${Math.round(score)} out of 100`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="hsl(var(--muted))"
          strokeWidth={9}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={colour}
          strokeWidth={9}
          strokeLinecap="round"
          strokeDasharray={`${circumference * pct} ${circumference}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className="tabular text-3xl font-semibold leading-none"
          style={{ color: colour }}
        >
          {Math.round(score)}
        </span>
        <span className="mt-0.5 text-[12px] text-muted-foreground">
          of 100
        </span>
      </div>
    </div>
  );
}

/**
 * Stage-by-stage progress for an in-flight assessment.
 *
 * All nine stages are always rendered, including those not yet run, so the user
 * sees the shape of the whole assessment rather than a progress bar that only
 * resolves at the end.
 */
export function AssessmentProgress({
  stage,
  completedStages,
  percentComplete,
  stageMessages,
  errorMessage,
}: {
  stage: string;
  completedStages: string[];
  percentComplete: number;
  stageMessages?: Record<string, string>;
  errorMessage?: string | null;
}) {
  const ordered = [
    "data_validation",
    "geology",
    "temperature",
    "well_integrity",
    "heat_demand",
    "engineering",
    "economics",
    "risk",
    "final_assessment",
  ];
  const currentIndex = ordered.indexOf(stage);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Progress value={percentComplete} className="flex-1" />
        <span className="tabular w-12 text-right text-sm font-medium">
          {percentComplete}%
        </span>
      </div>

      {errorMessage && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <p>{errorMessage}</p>
        </div>
      )}

      <ol className="space-y-1">
        {ordered.map((s, index) => {
          const isDone = completedStages.includes(s);
          const isCurrent = s === stage && !isDone;
          const isPending = index > currentIndex && !isDone;

          return (
            <li
              key={s}
              className={`flex items-center gap-2.5 rounded px-2 py-1.5 text-sm ${
                isCurrent ? "bg-primary/10 font-medium" : ""
              }`}
            >
              {isDone ? (
                <CheckCircle2 className="h-4 w-4 shrink-0 text-priority-high" />
              ) : isCurrent ? (
                <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
              ) : isPending ? (
                <span className="h-4 w-4 shrink-0 rounded-full border border-dashed border-muted-foreground/40" />
              ) : (
                <HelpCircle className="h-4 w-4 shrink-0 text-muted-foreground/50" />
              )}
              <span
                className={isPending ? "text-muted-foreground/60" : ""}
              >
                {stageMessages?.[s] ?? STAGE_LABELS[s]}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Compact grid of the headline engineering and financial figures. */
export function KeyFiguresGrid({ result }: { result: AnalysisResult }) {
  const figures = [
    {
      label: "Source temperature",
      value: result.source_temperature_c,
      display: formatTemperature(result.source_temperature_c),
      status: result.temperature_status,
    },
    {
      label: "Thermal output",
      value: result.thermal_output_kw,
      display: formatPower(result.thermal_output_kw),
      status: result.thermal_output_status,
    },
    {
      label: "Annual heat",
      value: result.annual_heat_kwh,
      display: formatEnergy(result.annual_heat_kwh),
      status: result.thermal_output_status,
    },
    {
      label: "CAPEX",
      value: result.capex_gbp,
      display: formatGBP(result.capex_gbp),
      status: "ESTIMATE",
    },
    {
      label: "LCOH",
      value: result.lcoh_p_per_kwh,
      display: result.lcoh_p_per_kwh !== null ? `${result.lcoh_p_per_kwh.toFixed(1)} p/kWh` : "Not available",
      status: "DERIVED",
    },
    {
      label: "NPV",
      value: result.npv_gbp,
      display: formatGBP(result.npv_gbp),
      status: "DERIVED",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
      {figures.map((figure) => (
        <div key={figure.label}>
          <div className="text-[12px] font-semibold text-muted-foreground">
            {figure.label}
          </div>
          <div className="mt-0.5 text-lg font-medium">
            {figure.value === null || figure.value === undefined ? (
              <span className="text-sm italic text-muted-foreground">
                {figure.display}
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <span className="tabular">{figure.display}</span>
                <EpistemicBadge status={figure.status as never} />
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
