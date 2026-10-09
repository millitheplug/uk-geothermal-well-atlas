/**
 * Panels that explain how a score was reached.
 *
 * The composite score is not allowed to appear on its own anywhere in this
 * product. It is always accompanied by the component scores that produced it,
 * and the data-confidence component is always shown separately from the
 * resource components, because "this looks good" and "we can defend this" are
 * different claims.
 */

"use client";

import * as React from "react";
import {
  ChevronDown,
  ChevronUp,
  Info,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
} from "lucide-react";

import { Badge, EpistemicBadge, EvidenceDisclaimer } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SectionTitle } from "@/components/common/feedback";
import {
  CONFIDENCE_META,
  RECOMMENDATION_META,
  RISK_LABELS,
} from "@/lib/domain";
import { cn } from "@/lib/utils";
import type {
  AnalysisResult,
  ConfidenceDetail,
  RiskAssessment,
  ScoreComponentName,
} from "@/types/api";

const COMPONENT_LABELS: Record<ScoreComponentName, string> = {
  thermal: "Thermal resource",
  integrity: "Well integrity",
  demand: "Heat demand",
  economics: "Economics",
  network: "Network connection",
  geometry: "Well geometry",
  regulatory: "Regulatory burden",
  data_confidence: "Data confidence",
};

/** Weights, repeated here so the UI never has to trust an API payload for them. */
export const WEIGHTS: Record<ScoreComponentName, number> = {
  thermal: 0.25,
  integrity: 0.2,
  demand: 0.15,
  economics: 0.15,
  network: 0.1,
  geometry: 0.05,
  regulatory: 0.05,
  data_confidence: 0.05,
};

export function ScoreBreakdown({ result }: { result: AnalysisResult }) {
  const [showAll, setShowAll] = React.useState(false);
  const components = result.component_scores ?? {};
  const names = Object.keys(WEIGHTS) as ScoreComponentName[];
  const weightSum = Object.values(WEIGHTS).reduce((sum, value) => sum + value, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>How the score was built</CardTitle>
        <CardDescription>
          Each component is scored 0–100 by the Python engineering engine and
          combined with the weights below. The weights sum to{" "}
          {weightSum.toFixed(2)}, so the composite score is directly comparable
          across wells and versions are recorded on the analysis.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {names.map((name) => {
          const score = components[name];
          const weight = WEIGHTS[name];
          const isConfidence = name === "data_confidence";
          const contribution =
            typeof score === "number" ? score * weight : null;

          return (
            <div key={name}>
              <div className="flex items-baseline justify-between gap-2 text-[11px]">
                <span className="flex items-center gap-1.5">
                  {COMPONENT_LABELS[name]}
                  <span className="font-mono text-[10px] text-muted-foreground">
                    ×{weight.toFixed(2)}
                  </span>
                  {isConfidence && (
                    <Badge variant="muted" className="text-[9px]">
                      evidence
                    </Badge>
                  )}
                </span>
                <span className="tabular shrink-0">
                  {typeof score === "number" ? (
                    <>
                      {score.toFixed(0)}
                      <span className="text-muted-foreground">
                        {" → "}
                        {contribution?.toFixed(1)} pts
                      </span>
                    </>
                  ) : (
                    <span className="italic text-muted-foreground">
                      Not scored
                    </span>
                  )}
                </span>
              </div>
              <Progress
                value={typeof score === "number" ? score : 0}
                className="mt-1 h-1.5"
                tone={isConfidence ? "none" : "default"}
              />
            </div>
          );
        })}

        <div className="mt-3 flex items-baseline justify-between border-t pt-2 text-sm">
          <span className="font-medium">Composite feasibility score</span>
          <span className="tabular text-lg font-semibold">
            {Math.round(result.feasibility_score)}
            <span className="text-xs font-normal text-muted-foreground">
              /100
            </span>
          </span>
        </div>

        <button
          type="button"
          onClick={() => setShowAll((value) => !value)}
          className="flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
        >
          {showAll ? (
            <ChevronUp className="h-3 w-3" aria-hidden />
          ) : (
            <ChevronDown className="h-3 w-3" aria-hidden />
          )}
          {showAll ? "Hide" : "Show"} warnings raised by the engine
        </button>

        {showAll && (
          <div className="space-y-2 rounded-md bg-muted/50 p-2.5">
            {result.warnings.length > 0 ? (
              <ul className="space-y-1 text-[11px] leading-relaxed text-muted-foreground">
                {result.warnings.map((warning, index) => (
                  <li key={index} className="flex gap-1.5">
                    <span aria-hidden>·</span>
                    <span>{warning}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                The engine raised no warnings on this run. The calculation trace
                below records the inputs and assumptions behind every figure
                regardless.
              </p>
            )}

            {result.data_gaps.length > 0 && (
              <div>
                <SectionTitle>Data gaps that limit this result</SectionTitle>
                <ul className="mt-1 space-y-1 text-[11px] leading-relaxed text-muted-foreground">
                  {result.data_gaps.map((gap, index) => (
                    <li key={index} className="flex gap-1.5">
                      <span aria-hidden>·</span>
                      <span>{gap}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {result.unknowns.length > 0 && (
              <div>
                <SectionTitle>Values that are unknown, not zero</SectionTitle>
                <ul className="mt-1 space-y-1 text-[11px] leading-relaxed text-muted-foreground">
                  {result.unknowns.map((item, index) => (
                    <li key={index} className="flex gap-1.5">
                      <span aria-hidden>·</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ConfidencePanel({
  detail,
  score,
}: {
  detail: ConfidenceDetail | null;
  score: number;
}) {
  const meta = detail ? CONFIDENCE_META[detail.band] : CONFIDENCE_META.unknown;
  const axes = detail ? Object.entries(detail.axes) : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Evidence confidence
          <span className={cn("text-sm font-normal", meta.className)}>
            {Math.round(score * 100)}% · {meta.label}
          </span>
        </CardTitle>
        <CardDescription>{meta.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Confidence describes the <em>evidence</em>, not the resource. It is
          reported separately from the feasibility score and is deliberately not
          folded into it: a well with an excellent score and no measurements is
          the case this platform most needs to get right, and merging the two
          numbers would hide it.
        </p>

        {axes.length > 0 && (
          <div className="space-y-1.5">
            <SectionTitle>Axes</SectionTitle>
            {axes.map(([axis, detail_]) => (
              <div key={axis}>
                <div className="flex items-baseline justify-between text-[11px]">
                  <span className="capitalize">{axis.replace(/_/g, " ")}</span>
                  <span className="tabular">
                    {Math.round(detail_.score * 100)}%
                    <span className="text-muted-foreground">
                      {" "}
                      ×{detail_.weight.toFixed(2)}
                    </span>
                  </span>
                </div>
                <Progress value={detail_.score * 100} className="mt-0.5 h-1.5" />
                {detail_.notes.length > 0 && (
                  <ul className="mt-0.5 space-y-0.5 text-[10px] leading-relaxed text-muted-foreground">
                    {detail_.notes.map((note, index) => (
                      <li key={index}>· {note}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}

        {detail && detail.conflicting_sources.length > 0 && (
          <div className="rounded-md border border-priority-medium/40 bg-priority-medium/5 p-2.5">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold text-priority-medium">
              <ShieldAlert className="h-3.5 w-3.5" aria-hidden />
              Sources disagree
            </p>
            <ul className="mt-1 space-y-0.5 text-[11px] leading-relaxed">
              {detail.conflicting_sources.map((item, index) => (
                <li key={index}>· {item}</li>
              ))}
            </ul>
          </div>
        )}

        {detail && detail.unknowns.length > 0 && (
          <div className="rounded-md border border-epistemic-unknown/40 bg-epistemic-unknown/5 p-2.5">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold text-epistemic-unknown">
              <ShieldQuestion className="h-3.5 w-3.5" aria-hidden />
              Unknowns carried into the assessment
            </p>
            <ul className="mt-1 space-y-0.5 text-[11px] leading-relaxed">
              {detail.unknowns.map((item, index) => (
                <li key={index}>· {item}</li>
              ))}
            </ul>
          </div>
        )}

        {detail && (
          <p className="font-mono text-[10px] text-muted-foreground">
            confidence v{detail.confidence_version}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

const SEVERITY_ORDER = ["low", "medium", "high", "critical"] as const;

export function RiskPanel({ risk }: { risk: RiskAssessment | null }) {
  const [showResolved, setShowResolved] = React.useState(false);

  if (!risk || risk.risks.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Risk register</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            No risks were raised for this well. Given the seventeen-category
            taxonomy the engine applies, that usually means the assessment has
            not been run rather than that a well carries no risk.
          </p>
        </CardContent>
      </Card>
    );
  }

  const sorted = [...risk.risks].sort(
    (a, b) => b.uncertainty_adjusted_score - a.uncertainty_adjusted_score,
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Risk register</CardTitle>
        <CardDescription>
          {risk.risk_count} risks,{" "}
          <span className="font-semibold text-destructive">
            {risk.critical_count} critical
          </span>
          . Aggregate exposure {risk.aggregate_score.toFixed(1)}. The ranking
          below uses the uncertainty-adjusted score, so a risk nobody has
          quantified ranks above an equivalent risk that has been measured.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y">
          {sorted.map((item) => {
            const severityIndex = SEVERITY_ORDER.indexOf(
              item.severity as (typeof SEVERITY_ORDER)[number],
            );
            return (
              <li key={`${item.category}-${item.title}`} className="py-2.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-medium">{item.title}</p>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                      {item.description}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <Badge
                      className={cn(
                        "text-[9px]",
                        severityIndex >= 3
                          ? "border-destructive/40 bg-destructive/10 text-destructive"
                          : severityIndex === 2
                            ? "border-priority-low/40 bg-priority-low/10 text-priority-low"
                            : severityIndex === 1
                              ? "border-priority-medium/40 bg-priority-medium/10 text-priority-medium"
                              : "border-border text-muted-foreground",
                      )}
                    >
                      {item.severity}
                    </Badge>
                    <span className="tabular text-[11px] font-medium">
                      {item.uncertainty_adjusted_score.toFixed(1)}
                    </span>
                  </div>
                </div>

                <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] text-muted-foreground">
                  <span>
                    Category: {RISK_LABELS[item.category] ?? item.category}
                  </span>
                  <span>
                    Likelihood: {item.likelihood} ({item.probability.toFixed(2)})
                  </span>
                  <span>Impact: {item.impact}</span>
                  <span>Uncertainty: {item.uncertainty.toFixed(2)}</span>
                </dl>

                {item.evidence.length > 0 && (
                  <ul className="mt-1 space-y-0.5 text-[10px] leading-relaxed text-muted-foreground">
                    {item.evidence.map((line, index) => (
                      <li key={index}>Evidence: {line}</li>
                    ))}
                  </ul>
                )}
                {item.mitigation && (
                  <p className="mt-1 text-[10px] leading-relaxed text-primary">
                    Mitigation: {item.mitigation}
                  </p>
                )}
                {item.addresses_data_gap && showResolved && (
                  <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
                    Resolves data gap: {item.addresses_data_gap}
                  </p>
                )}
              </li>
            );
          })}
        </ul>

        <button
          type="button"
          onClick={() => setShowResolved((value) => !value)}
          className="mt-2 flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
        >
          {showResolved ? (
            <ChevronUp className="h-3 w-3" aria-hidden />
          ) : (
            <ChevronDown className="h-3 w-3" aria-hidden />
          )}
          {showResolved ? "Hide" : "Show"} which data gap each risk addresses
        </button>
      </CardContent>
    </Card>
  );
}

/** Compact decision strip: score, confidence and recommendation together. */
export function DecisionStrip({ result }: { result: AnalysisResult }) {
  const recommendation = RECOMMENDATION_META[result.recommendation];

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Card className="sm:col-span-1">
        <CardContent className="p-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Feasibility
          </div>
          <div className="tabular mt-1 text-3xl font-semibold leading-none">
            {Math.round(result.feasibility_score)}
            <span className="text-sm font-normal text-muted-foreground">/100</span>
          </div>
          <div className="mt-2">
            <Badge className={recommendation.className}>
              {result.recommendation}
            </Badge>
          </div>
          <p className="mt-1.5 text-[10px] italic text-muted-foreground">
            {recommendation.tone}
          </p>
        </CardContent>
      </Card>

      <Card className="sm:col-span-1">
        <CardContent className="p-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Evidence confidence
          </div>
          <div className="tabular mt-1 text-3xl font-semibold leading-none">
            {Math.round(result.confidence_score * 100)}
            <span className="text-sm font-normal text-muted-foreground">%</span>
          </div>
          <div className="mt-2">
            <Badge variant="outline" className="text-[10px]">
              {CONFIDENCE_META[result.confidence_band].label}
            </Badge>
          </div>
          <p className="mt-1.5 text-[10px] italic text-muted-foreground">
            Measures the evidence, not the resource.
          </p>
        </CardContent>
      </Card>

      <Card className="sm:col-span-1">
        <CardContent className="p-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Thermal output
          </div>
          <div className="mt-1 flex items-baseline gap-1.5">
            <span className="tabular text-3xl font-semibold leading-none">
              {result.thermal_output_kw !== null
                ? result.thermal_output_kw.toFixed(0)
                : "—"}
            </span>
            <span className="text-sm font-normal text-muted-foreground">
              kWth
            </span>
            <EpistemicBadge status={result.thermal_output_status} />
          </div>
          {result.thermal_output_low_kw !== null &&
            result.thermal_output_high_kw !== null && (
              <p className="mt-1 text-[10px] text-muted-foreground">
                Range {result.thermal_output_low_kw.toFixed(0)}–
                {result.thermal_output_high_kw.toFixed(0)} kWth
              </p>
            )}
          <p className="mt-1.5 flex items-start gap-1 text-[10px] italic text-muted-foreground">
            <Info className="mt-0.5 h-2.5 w-2.5 shrink-0" aria-hidden />
            Scales linearly with flow rate; no flow test has been performed
            unless the status reads measured.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

/** Footer assurance block, repeated on every analysis view. */
export function AssuranceFooter() {
  return (
    <div className="space-y-2">
      <EvidenceDisclaimer />
      <p className="flex items-start gap-1.5 text-[10px] leading-relaxed text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
        The composite score, the recommendation and every figure above were
        computed by the deterministic Python engine. The eleven analysis agents
        may only narrate these results, and a discipline gate rejects any output
        that claims commercial viability or disagrees with the engine's
        recommendation.
      </p>
    </div>
  );
}