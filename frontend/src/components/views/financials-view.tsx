/**
 * Financial view for a single well.
 *
 * A financials page without a well selected is meaningless, so this view opens
 * on a well picker fed from the candidate ranking rather than on a chart of
 * nothing. Every figure is labelled with what kind of number it is: CAPEX and
 * OPEX are estimates built from documented unit rates, LCOH and NPV are derived
 * from them, and the discount rate and heat price are assumptions about a
 * market that nobody has observed.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import {
  Banknote,
  Calculator,
  PieChart,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import {
  EmptyState,
  ErrorState,
  KeyValueList,
  Loading,
  Notice,
  SectionTitle,
  SectionTitle as PanelTitle,
  StatGrid,
  StatTile,
} from "@/components/common/feedback";
import { Badge, EpistemicBadge, EvidenceDisclaimer } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { ScenarioPanel } from "@/components/analysis/whatif-panel";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import { RECOMMENDATION_META } from "@/lib/domain";
import { fmtGBP } from "@/lib/utils";
import type { AnalysisResult, CandidateRow } from "@/types/api";

export function FinancialsView() {
  const [selected, setSelected] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<AnalysisResult | null>(null);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const candidates = useApiData(
    (signal) => api.candidates({ limit: 300, order_by: "feasibility_score" }, signal),
    [],
  );

  // Auto-select the top-ranked candidate so the page is never empty.
  React.useEffect(() => {
    if (!selected && candidates.data && candidates.data.items.length > 0) {
      const first = candidates.data.items[0];
      if (first) setSelected(first.well_id);
    }
  }, [candidates.data, selected]);

  React.useEffect(() => {
    if (!selected) {
      setResult(null);
      return;
    }
    let cancelled = false;
    setRunning(true);
    setError(null);

    const run = async () => {
      try {
        const computed = await api.runAnalysis(selected, {}, false);
        if (!cancelled) setResult(computed);
      } catch (caught) {
        if (!cancelled) {
          setError(
            caught instanceof Error ? caught.message : "The analysis failed.",
          );
          setResult(null);
        }
      } finally {
        if (!cancelled) setRunning(false);
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const rows: CandidateRow[] = candidates.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Financials"
        subtitle="CAPEX, OPEX, levelised cost and return for a single well"
        actions={
          result ? (
            <Button variant="outline" size="sm" asChild>
              <Link href={`/wells/${result.well_id}`}>
                Full analysis and trace
              </Link>
            </Button>
          ) : undefined
        }
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="space-y-4 p-4">
          {/* Well picker */}
          <div className="flex flex-wrap items-end gap-3 rounded-md border bg-card p-3">
            <div className="min-w-[16rem] flex-1">
              <div className="mb-1 text-[12px] font-semibold text-muted-foreground">
                Well
              </div>
              <Select value={selected ?? ""} onValueChange={setSelected}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Choose a candidate well" />
                </SelectTrigger>
                <SelectContent>
                  {rows.map((row) => (
                    <SelectItem key={row.well_id} value={row.well_id} className="text-xs">
                      #{row.rank} {row.well_name}
                      {row.lcoh_p_per_kwh !== null
                        ? ` — ${row.lcoh_p_per_kwh.toFixed(1)} p/kWh`
                        : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {candidates.loading && (
              <p className="text-xs text-muted-foreground">Loading candidates…</p>
            )}
            {candidates.error && (
              <p className="text-xs text-destructive">{candidates.error}</p>
            )}
          </div>

          {error && (
            <ErrorState
              title="The financial analysis failed"
              message={error}
              onRetry={() => setSelected(selected)}
            />
          )}

          {running && !result && <Loading label="Running the economic model" />}

          {!running && !result && !error && (
            <EmptyState
              title="Choose a well"
              message="Financials are computed per well, because CAPEX depends on completion geometry and depth and OPEX depends on flow rate and pumping depth."
            />
          )}

          {result && (
            <>
              <Notice tone="info" title="These are screening economics">
                Every figure assumes the well converts, the consent is granted
                and a heat offtake exists at the assumed price. None of that is
                established by this analysis. The numbers answer &quot;would this
                pencil in&quot;, not &quot;should we invest&quot;.
              </Notice>

              {/* Headline economics */}
              <StatGrid cols={5}>
                <StatTile
                  label="Capital cost"
                  value={
                    result.capex_gbp !== null ? fmtGBP(result.capex_gbp) : "Not available"
                  }
                  status={<EpistemicBadge status="ESTIMATE" />}
                  sub="Unit rates × depth, completion geometry and network length"
                />
                <StatTile
                  label="Annual operating cost"
                  value={
                    result.opex_gbp_per_year !== null
                      ? fmtGBP(result.opex_gbp_per_year)
                      : "Not available"
                  }
                  status={<EpistemicBadge status="ESTIMATE" />}
                  sub="Pumping, maintenance, monitoring and network running cost"
                />
                <StatTile
                  label="Levelised cost of heat"
                  value={
                    result.lcoh_p_per_kwh !== null
                      ? result.lcoh_p_per_kwh.toFixed(1)
                      : "Not available"
                  }
                  unit={result.lcoh_p_per_kwh !== null ? "p/kWh" : undefined}
                  status={<EpistemicBadge status="DERIVED" />}
                  sub="CAPEX and OPEX spread over lifetime heat delivered"
                />
                <StatTile
                  label="Net present value"
                  value={
                    result.npv_gbp !== null ? fmtGBP(result.npv_gbp) : "Not available"
                  }
                  status={<EpistemicBadge status="DERIVED" />}
                  tone={result.npv_gbp !== null && result.npv_gbp < 0 ? "danger" : "default"}
                  sub={
                    result.npv_gbp !== null && result.npv_gbp < 0
                      ? "Negative at the assumed heat price and discount rate"
                      : "Positive at the assumed heat price and discount rate"
                  }
                />
                <StatTile
                  label="Internal rate of return"
                  value={
                    result.irr_pct !== null ? result.irr_pct.toFixed(1) : "Not available"
                  }
                  unit={result.irr_pct !== null ? "%" : undefined}
                  status={<EpistemicBadge status="DERIVED" />}
                  tone={
                    result.irr_pct === null
                      ? "muted"
                      : result.irr_pct < 0
                        ? "danger"
                        : "default"
                  }
                  sub={
                    result.irr_pct === null
                      ? "No sign change in the cash flow, so no IRR exists. This is not a zero."
                      : "Against the discounted cash flow the engine produced"
                  }
                />
              </StatGrid>

              {/* Recommendation and break-even */}
              <div className="grid gap-3 lg:grid-cols-3">
                <Card>
                  <CardContent className="p-4 sm:p-5">
                    <PanelTitle>Where this sits</PanelTitle>
                    <div className="mt-2 flex items-baseline gap-3">
                      <span className="tabular text-3xl font-semibold">
                        {Math.round(result.feasibility_score)}
                        <span className="text-sm font-normal text-muted-foreground">
                          /100
                        </span>
                      </span>
                      <Badge
                        className={RECOMMENDATION_META[result.recommendation].className}
                      >
                        {result.recommendation}
                      </Badge>
                    </div>
                    <div className="mt-3">
                      <div className="flex items-baseline justify-between text-xs">
                        <span className="text-muted-foreground">
                          Evidence confidence
                        </span>
                        <span className="tabular">
                          {Math.round(result.confidence_score * 100)}%
                        </span>
                      </div>
                      <Progress
                        value={result.confidence_score * 100}
                        className="mt-1"
                        tone="none"
                      />
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                      {RECOMMENDATION_META[result.recommendation].tone}
                    </p>
                    <Link
                      href={`/wells/${result.well_id}`}
                      className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                    >
                      See how the score was built
                    </Link>
                  </CardContent>
                </Card>

                <Card>
                  <CardContent className="p-4 sm:p-5">
                    <PanelTitle>Break-even and payback</PanelTitle>
                    <div className="mt-2">
                      <KeyValueList
                        dense
                        items={[
                          {
                            label: "Break-even heat price",
                            value:
                              result.break_even_heat_price_p_per_kwh !== null ? (
                                <>
                                  {result.break_even_heat_price_p_per_kwh.toFixed(1)} p/kWh
                                  <span className="ml-1">
                                    <EpistemicBadge status="DERIVED" />
                                  </span>
                                </>
                              ) : (
                                "No break-even within the tested range"
                              ),
                            missing: result.break_even_heat_price_p_per_kwh === null,
                          },
                          {
                            label: "Simple payback",
                            value:
                              result.payback_years !== null ? (
                                <>
                                  {result.payback_years.toFixed(1)} years
                                  <span className="ml-1">
                                    <EpistemicBadge status="DERIVED" />
                                  </span>
                                </>
                              ) : (
                                "Not reached within the project lifetime"
                              ),
                            missing: result.payback_years === null,
                          },
                          {
                            label: "Annual heat delivered",
                            value:
                              result.annual_heat_kwh !== null
                                ? `${Math.round(result.annual_heat_kwh).toLocaleString("en-GB")} kWh`
                                : "Not available",
                            missing: result.annual_heat_kwh === null,
                          },
                          {
                            label: "Delivered heat rate",
                            value:
                              result.delivered_heat_kw !== null
                                ? `${result.delivered_heat_kw.toFixed(0)} kWth`
                                : "Not available",
                            missing: result.delivered_heat_kw === null,
                          },
                          {
                            label: "Heat pump electricity",
                            value:
                              result.heat_pump_electricity_kw !== null
                                ? `${result.heat_pump_electricity_kw.toFixed(1)} kW`
                                : "No heat pump in this configuration",
                            missing: result.heat_pump_electricity_kw === null,
                          },
                        ]}
                      />
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardContent className="p-4 sm:p-5">
                    <PanelTitle>Distribution losses</PanelTitle>
                    <div className="mt-2">
                      <KeyValueList
                        dense
                        items={[
                          {
                            label: "Network length",
                            value:
                              result.network_length_m !== null
                                ? `${(result.network_length_m / 1000).toFixed(2)} km`
                                : "Not available",
                            missing: result.network_length_m === null,
                          },
                          {
                            label: "Loss fraction",
                            value:
                              result.network_loss_fraction !== null
                                ? `${(result.network_loss_fraction * 100).toFixed(1)}%`
                                : "Not available",
                            missing: result.network_loss_fraction === null,
                          },
                          {
                            label: "Network loss",
                            value:
                              result.network_heat_loss_kw !== null
                                ? `${result.network_heat_loss_kw.toFixed(1)} kWth`
                                : "Not available",
                            missing: result.network_heat_loss_kw === null,
                          },
                          {
                            label: "Demand matched",
                            value:
                              result.demand_matched_kw !== null
                                ? `${result.demand_matched_kw.toFixed(0)} kWth`
                                : "Not available",
                            missing: result.demand_matched_kw === null,
                          },
                        ]}
                      />
                    </div>
                    {result.network_loss_fraction !== null &&
                      result.network_loss_fraction > 0.2 && (
                        <p className="mt-2 rounded border border-priority-medium/40 bg-priority-medium/5 p-2 text-[12px] leading-relaxed text-priority-medium">
                          <TriangleAlert className="mr-1 inline h-3 w-3" aria-hidden />
                          More than a fifth of the extracted heat is lost before it
                          reaches a customer. At this rate, halving the run length
                          is worth more than any plausible improvement in the well.
                        </p>
                      )}
                  </CardContent>
                </Card>
              </div>

              {/* Cost structure */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <PieChart className="h-4 w-4" aria-hidden />
                    Cost structure
                  </CardTitle>
                  <CardDescription>
                    Where the levelised cost comes from, using the engine&apos;s
                    own lifetime totals. All components are estimates derived
                    from documented unit rates; the split is what matters, not the
                    precision of the total.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {result.capex_gbp !== null && result.opex_gbp_per_year !== null && result.capex_gbp > 0 ? (
                    <LifetimeCostBars
                      capex={result.capex_gbp}
                      opexPerYear={result.opex_gbp_per_year}
                      lifetimeYears={25}
                    />
                  ) : (
                    <p className="text-xs italic text-muted-foreground">
                      Cost inputs are unavailable for this well, so no structure can
                      be shown. Check the calculation trace for which input is
                      missing.
                    </p>
                  )}

                  <div className="mt-4 border-t pt-3">
                    <SectionTitle>How to read these figures</SectionTitle>
                    <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted-foreground">
                      <li className="flex gap-1.5">
                        <Calculator className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                        <span>
                          CAPEX is built from a per-metre recompletion rate scaled
                          by depth, plus a boreheat-exchanger allowance and the
                          network length. It does not include land, consents,
                          connection or offtake negotiation.
                        </span>
                      </li>
                      <li className="flex gap-1.5">
                        <Banknote className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                        <span>
                          LCOH divides the discounted lifetime cost by discounted
                          lifetime heat delivered, so it is directly comparable
                          between wells with different duty cycles.
                        </span>
                      </li>
                      <li className="flex gap-1.5">
                        <TrendingUp className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                        <span>
                          NPV and IRR both depend on the heat price and discount
                          rate, which are assumptions. Use the scenario panel below
                          to see how much that matters rather than treating a
                          single number as a return.
                        </span>
                      </li>
                    </ul>
                  </div>
                </CardContent>
              </Card>

              <ScenarioPanel wellId={result.well_id} />

              <EvidenceDisclaimer />
            </>
          )}
        </div>
      </div>
    </>
  );
}

/** Horizontal breakdown of lifetime cost into capex and opex components. */
function LifetimeCostBars({
  capex,
  opexPerYear,
  lifetimeYears,
}: {
  capex: number;
  opexPerYear: number;
  lifetimeYears: number;
}) {
  const opexTotal = opexPerYear * lifetimeYears;
  const total = capex + opexTotal;
  const rows = [
    { label: "Capital (CAPEX)", value: capex, colour: "hsl(var(--score-40))" },
    {
      label: `Operating, ${lifetimeYears} years (undiscounted)`,
      value: opexTotal,
      colour: "hsl(var(--score-80))",
    },
  ];

  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.label}>
          <div className="flex items-baseline justify-between text-xs">
            <span>{row.label}</span>
            <span className="tabular">
              {fmtGBP(row.value)}{" "}
              <span className="text-muted-foreground">
                ({((row.value / total) * 100).toFixed(0)}%)
              </span>
            </span>
          </div>
          <div className="mt-0.5 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full"
              style={{
                width: `${(row.value / total) * 100}%`,
                backgroundColor: row.colour,
              }}
            />
          </div>
        </div>
      ))}
      <p className="pt-1 text-[12px] leading-relaxed text-muted-foreground">
        Lifetime totals are shown undiscounted for readability. The engine&apos;s
        LCOH and NPV use discounted cash flows; the exact discounting is
        recorded in the calculation trace on the well record.
      </p>
    </div>
  );
}