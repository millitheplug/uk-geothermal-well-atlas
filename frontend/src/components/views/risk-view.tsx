/**
 * Risk register, nationally and per well.
 *
 * Two ideas drive the presentation. First, exposure is ranked by the
 * uncertainty-adjusted score, not the raw likelihood×impact product: a hazard
 * nobody has quantified is more dangerous than one that has been, and treating
 * them as equal is how unknown risks get ignored. Second, risks that exist
 * because a field is missing are shown differently from risks that come from
 * adverse geology, because only one of the two can be bought off with a data
 * gathering exercise.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import { ShieldAlert, TriangleAlert } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import {
  EmptyState,
  ErrorState,
  Loading,
  Notice,
  SectionTitle,
  StatGrid,
  StatTile,
} from "@/components/common/feedback";
import { BreakdownBars, RiskBars, type BreakdownItem } from "@/components/charts/charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import { RISK_LABELS, humanise } from "@/lib/domain";
import type { CandidateRow, NationalDashboard, RiskCategory } from "@/types/api";

/** Categories whose presence is caused by absent data rather than by physics. */
const DATA_GAP_CATEGORIES: RiskCategory[] = [
  "well_integrity",
  "temperature_uncertainty",
  "heat_demand_uncertainty",
  "land_access",
  "customer_connection",
];

export function RiskView() {
  const [selected, setSelected] = React.useState<string | null>(null);

  const dashboard = useApiData<NationalDashboard>(
    (signal) => api.nationalDashboard(true, signal),
    [],
  );
  const candidates = useApiData(
    (signal) => api.candidates({ limit: 200, order_by: "feasibility_score" }, signal),
    [],
  );
  const analyses = useApiData(
    (signal) =>
      api.listAnalyses(
        selected ? { well_id: selected, limit: 1 } : { limit: 40 },
        signal,
      ),
    [selected],
  );

  React.useEffect(() => {
    if (!selected && candidates.data && candidates.data.items.length > 0) {
      setSelected(candidates.data.items[0]?.well_id ?? null);
    }
  }, [candidates.data, selected]);

  const nationalItems: BreakdownItem[] = React.useMemo(() => {
    if (!dashboard.data) return [];
    return Object.entries(dashboard.data.risk_category_totals)
      .map(([key, value]) => ({
        key,
        label: RISK_LABELS[key as RiskCategory] ?? humanise(key),
        value,
      }))
      .sort((a, b) => b.value - a.value);
  }, [dashboard.data]);

  const selectedAnalysis = selected ? (analyses.data?.[0] ?? null) : null;
  // Derived rather than read straight off the analysis: the `?? []` fallback
  // would otherwise be a fresh array on every render, which keeps the memo
  // below from ever holding its value. selectedAnalysis is stable while the
  // cached analysis is unchanged.
  const risks = React.useMemo(
    () => selectedAnalysis?.risk?.risks ?? [],
    [selectedAnalysis],
  );

  const severityCounts = React.useMemo(() => {
    const counts = new Map<string, number>();
    for (const risk of risks) {
      counts.set(risk.severity, (counts.get(risk.severity) ?? 0) + 1);
    }
    return counts;
  }, [risks]);

  return (
    <>
      <PageHeader
        title="Risk register"
        subtitle="Seventeen categories, ranked by exposure including how well each is quantified"
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="space-y-4 p-4">
          <Notice tone="info" title="How exposure is ranked">
            Each risk carries a likelihood, an impact and an explicit
            uncertainty, all in the range 0 to 1. The uncertainty-adjusted score
            divides the raw product by (1 + uncertainty), so a risk nobody has
            measured ranks above an equivalent risk that has. A register ranked on
            raw likelihood×impact systematically buries the unknowns.
          </Notice>

          {dashboard.loading && !dashboard.data && <Loading label="Loading risk aggregates" />}
          {dashboard.error && (
            <ErrorState message={dashboard.error} onRetry={dashboard.refresh} />
          )}

          {dashboard.data && (
            <StatGrid cols={4}>
              <StatTile
                label="Wells assessed"
                value={Object.keys(dashboard.data.recommendation_breakdown).length > 0
                  ? dashboard.data.candidate_wells.toLocaleString("en-GB")
                  : "Not assessed"}
                sub="A risk register needs an analysis behind each well"
                tone={Object.keys(dashboard.data.recommendation_breakdown).length === 0 ? "warning" : "default"}
              />
              <StatTile
                label="Wells needing more data"
                value={dashboard.data.wells_needing_more_data.toLocaleString("en-GB")}
                tone="warning"
                sub="At least one field the model needs is missing"
              />
              <StatTile
                label="Highest-priority risk category"
                value={nationalItems[0]?.label ?? "None recorded"}
                tone="default"
                sub={
                  nationalItems[0]
                    ? `${nationalItems[0].value.toLocaleString("en-GB")} aggregate exposure across assessed wells`
                    : undefined
                }
              />
              <StatTile
                label="Categories in the taxonomy"
                value={String(Object.keys(RISK_LABELS).length)}
                sub="The engine evaluates all of them for every assessment, whether or not any are raised"
              />
            </StatGrid>
          )}

          <div className="grid gap-3 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>National exposure by category</CardTitle>
                <CardDescription>
                  Summed uncertainty-adjusted scores across every assessed well.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <BreakdownBars
                  items={nationalItems}
                  emptyLabel="No risks have been raised yet. Run an assessment."
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Well register</CardTitle>
                <CardDescription>
                  Pick a well to see its individual risks with evidence,
                  mitigations and the data gap each one would close.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <Select value={selected ?? ""} onValueChange={setSelected}>
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder="Choose a well" />
                  </SelectTrigger>
                  <SelectContent>
                    {(candidates.data?.items ?? []).map((row: CandidateRow) => (
                      <SelectItem key={row.well_id} value={row.well_id} className="text-xs">
                        {row.well_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {selectedAnalysis && (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge variant="outline">
                      {selectedAnalysis.risk?.risk_count ?? 0} risks
                    </Badge>
                    {(selectedAnalysis.risk?.critical_count ?? 0) > 0 && (
                      <Badge className="border-destructive/40 bg-destructive/10 text-destructive">
                        {selectedAnalysis.risk?.critical_count} critical
                      </Badge>
                    )}
                    <span className="text-muted-foreground">
                      Aggregate exposure{" "}
                      {selectedAnalysis.risk?.aggregate_score.toFixed(1) ?? "Not available"}
                    </span>
                  </div>
                )}

                {analyses.loading && !analyses.data && (
                  <Loading label="Loading the well register" compact />
                )}
              </CardContent>
            </Card>
          </div>

          {selectedAnalysis?.risk && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Exposure ranked by uncertainty</CardTitle>
                  <CardDescription>
                    {selectedAnalysis.well_name}. Categories marked{" "}
                    <Badge variant="outline" className="text-[11px]">
                      data gap
                    </Badge>{" "}
                    exist because a field is missing rather than because the
                    subsurface is adverse.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <RiskBars
                    items={risks.map((risk) => ({
                      label: RISK_LABELS[risk.category] ?? risk.category,
                      value: risk.uncertainty_adjusted_score,
                      severity: risk.severity,
                    }))}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Severity mix</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-4">
                    {["critical", "high", "medium", "low"].map((severity) => (
                      <div key={severity}>
                        <div className="text-[12px] text-muted-foreground">
                          {severity}
                        </div>
                        <div className="tabular text-2xl font-semibold">
                          {severityCounts.get(severity) ?? 0}
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <ShieldAlert className="h-4 w-4" aria-hidden />
                    Individual risks
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className="divide-y">
                    {risks.map((risk) => (
                      <li key={`${risk.category}-${risk.title}`} className="py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-xs font-medium">{risk.title}</p>
                            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                              {risk.description}
                            </p>
                          </div>
                          <div className="flex shrink-0 flex-col items-end gap-1">
                            <Badge
                              className={
                                risk.severity === "critical"
                                  ? "border-destructive/40 bg-destructive/10 text-destructive"
                                  : "border-border text-muted-foreground"
                              }
                            >
                              {risk.severity}
                            </Badge>
                            {DATA_GAP_CATEGORIES.includes(risk.category) && (
                              <Badge variant="muted" className="text-[11px]">
                                data gap
                              </Badge>
                            )}
                            <span className="tabular text-xs font-medium">
                              {risk.uncertainty_adjusted_score.toFixed(1)}
                            </span>
                          </div>
                        </div>

                        <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[12px] text-muted-foreground">
                          <span>
                            Likelihood {risk.likelihood} ({risk.probability.toFixed(2)})
                          </span>
                          <span>Impact {risk.impact}</span>
                          <span>Uncertainty {risk.uncertainty.toFixed(2)}</span>
                          <span>
                            Raw score {risk.risk_score.toFixed(1)} → adjusted{" "}
                            {risk.uncertainty_adjusted_score.toFixed(1)}
                          </span>
                        </dl>

                        {risk.evidence.length > 0 && (
                          <ul className="mt-1 space-y-0.5 text-[12px] leading-relaxed text-muted-foreground">
                            {risk.evidence.map((line, index) => (
                              <li key={index}>Evidence: {line}</li>
                            ))}
                          </ul>
                        )}
                        {risk.mitigation && (
                          <p className="mt-1 text-[12px] leading-relaxed text-primary">
                            Mitigation: {risk.mitigation}
                          </p>
                        )}
                        {risk.addresses_data_gap && (
                          <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
                            Closed by obtaining: {risk.addresses_data_gap}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>

                  <Button variant="outline" size="sm" className="mt-3" asChild>
                    <Link href={`/wells/${selectedAnalysis.well_id}`}>
                      Open the full well record
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            </>
          )}

          {!analyses.loading && risks.length === 0 && (
            <EmptyState
              title="No risk register for this well yet"
              message="Run an assessment on the well record page. The engine evaluates all seventeen categories and records the ones that apply, so an empty register almost always means no assessment rather than no risk."
              action={
                selected ? (
                  <Link
                    href={`/wells/${selected}`}
                    className="text-xs text-primary hover:underline"
                  >
                    Open {candidates.data?.items.find((r) => r.well_id === selected)?.well_name ?? "the well"}
                  </Link>
                ) : undefined
              }
            />
          )}

          <Card>
            <CardContent className="p-4 sm:p-5">
              <SectionTitle>What this register cannot cover</SectionTitle>
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted-foreground">
                <li className="flex gap-1.5">
                  <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                  <span>
                    Subsurface hazards with no recorded indicator. Scaling,
                    corrosion and gas are only risks where somebody logged
                    evidence of them.
                  </span>
                </li>
                <li className="flex gap-1.5">
                  <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                  <span>
                    Induced seismicity from injection, and any consequence for a
                    third party&apos;s water supply. These are real and cannot be
                    assessed from a desk.
                  </span>
                </li>
                <li className="flex gap-1.5">
                  <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                  <span>
                    Thermal decline over the project lifetime. The engine models
                    it from a parameter, and the parameter is a modelling choice
                    rather than a measurement of this specific reservoir.
                  </span>
                </li>
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}