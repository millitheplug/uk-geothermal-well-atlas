"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowRight,
  CircleHelp,
  Flame,
  Thermometer,
  TriangleAlert,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import {
  Caveats,
  EmptyState,
  ErrorState,
  Loading,
  Notice,
  SectionTitle,
  StatGrid,
  StatTile,
} from "@/components/common/feedback";
import {
  BreakdownBars,
  ScoreHistogram,
  type BreakdownItem,
} from "@/components/charts/charts";
import { EpistemicBadge, MockDataBanner } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import {
  RISK_LABELS,
  WELL_STATUS_LABELS,
  humanise,
} from "@/lib/domain";
import type { RiskCategory } from "@/types/api";

/**
 * National dashboard.
 *
 * The most important number on this page is the count of wells with *no*
 * temperature measurement, so it is given the same visual weight as the
 * headline figures rather than being hidden in a caveat. Any national total
 * derived from temperature data inherits that gap, and every panel that uses
 * one says so.
 */
export function DashboardView() {
  const { data, error, loading, refresh } = useApiData(
    (signal) => api.nationalDashboard(true, signal),
    [],
  );

  if (loading && !data) {
    return (
      <>
        <PageHeader
          title="National dashboard"
          subtitle="Headline position across the onshore well inventory"
        />
        <Loading
          label="Aggregating the national picture"
          detail="The dashboard aggregates wells, temperature records, analyses and heat demand. On a large inventory this takes a moment."
        />
      </>
    );
  }

  if (error || !data) {
    return (
      <>
        <PageHeader title="National dashboard" />
        <div className="p-4">
          <ErrorState
            title="The dashboard could not be loaded"
            message={error}
            isOffline={error?.includes("Could not reach")}
            onRetry={refresh}
          />
        </div>
      </>
    );
  }

  const unmeasuredShare =
    data.total_wells > 0 ? data.wells_without_temperature / data.total_wells : null;

  const recommendationItems: BreakdownItem[] = Object.entries(
    data.recommendation_breakdown,
  ).map(([key, value]) => ({ key, label: key, value }));

  const confidenceItems: BreakdownItem[] = Object.entries(
    data.confidence_breakdown,
  ).map(([key, value]) => ({ key, label: key, value }));

  const regionItems: BreakdownItem[] = Object.entries(data.region_breakdown)
    .map(([key, value]) => ({ key, label: key, value }))
    .sort((a, b) => b.value - a.value);

  const statusItems: BreakdownItem[] = Object.entries(data.status_breakdown).map(
    ([key, value]) => ({
      key,
      label: WELL_STATUS_LABELS[key] ?? humanise(key),
      value,
    }),
  );

  const purposeItems: BreakdownItem[] = Object.entries(data.purpose_breakdown).map(
    ([key, value]) => ({ key, label: humanise(key), value }),
  );

  const riskItems: BreakdownItem[] = Object.entries(data.risk_category_totals)
    .map(([key, value]) => ({
      key,
      label: RISK_LABELS[key as RiskCategory] ?? humanise(key),
      value,
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);

  return (
    <>
      <PageHeader
        title="National dashboard"
        subtitle={`${data.total_wells.toLocaleString("en-GB")} wells in the inventory, of which ${data.wells_with_temperature.toLocaleString("en-GB")} carry a temperature record`}
        actions={
          <>
            <Button variant="outline" size="sm" asChild>
              <Link href="/candidates">
                Candidate table
                <ArrowRight aria-hidden />
              </Link>
            </Button>
            <Button size="sm" asChild>
              <Link href="/">
                Open the map
              </Link>
            </Button>
          </>
        }
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="space-y-4 p-4">
          {data.is_mock && (
            <MockDataBanner
              isMock
              what="every figure on this page"
            />
          )}

          {unmeasuredShare !== null && unmeasuredShare > 0.2 && (
            <Notice tone="warning" title="Coverage gap">
              {((unmeasuredShare * 100)).toFixed(0)}% of the inventory has no
              temperature measurement. Every aggregate on this page that depends
              on temperature is therefore a statement about the{" "}
              {data.wells_with_temperature.toLocaleString("en-GB")} measured
              wells, not about the {data.total_wells.toLocaleString("en-GB")}{" "}
              in total. The gap is a finding, not a defect in the data.
            </Notice>
          )}

          {/* Headline figures */}
          <StatGrid cols={5}>
            <StatTile
              label="Wells in inventory"
              value={data.total_wells.toLocaleString("en-GB")}
              sub={`${data.candidate_wells.toLocaleString("en-GB")} are candidates — a temperature measurement and a known well condition`}
            />
            <StatTile
              label="With a temperature record"
              value={data.wells_with_temperature.toLocaleString("en-GB")}
              sub="Measured, modelled or estimated — each labelled separately per well"
              tone={unmeasuredShare !== null && unmeasuredShare > 0.2 ? "warning" : "default"}
            />
            <StatTile
              label="With no temperature"
              value={data.wells_without_temperature.toLocaleString("en-GB")}
              sub="Thermal potential is unknown, not zero"
              tone={data.wells_without_temperature > 0 ? "warning" : "muted"}
            />
            <StatTile
              label="Estimated capacity, measured wells"
              value={
                data.total_estimated_thermal_capacity_mwt !== null
                  ? data.total_estimated_thermal_capacity_mwt.toFixed(0)
                  : "Not available"
              }
              unit={data.total_estimated_thermal_capacity_mwt !== null ? "MWth" : undefined}
              tone="muted"
              status={
                <EpistemicBadge
                  status={data.total_estimated_thermal_capacity_status}
                />
              }
              sub={
                data.total_estimated_thermal_capacity_status === "MEASURED" ||
                data.total_estimated_thermal_capacity_status === "DERIVED"
                  ? undefined
                  : "An aggregate of estimates. Not a reserve statement."
              }
            />
            <StatTile
              label="Heat demand near wells"
              value={
                data.nearby_heat_demand_opportunity_gwh !== null
                  ? data.nearby_heat_demand_opportunity_gwh.toFixed(0)
                  : "Not available"
              }
              unit={
                data.nearby_heat_demand_opportunity_gwh !== null ? "GWh/yr" : undefined
              }
              tone="muted"
              status={<EpistemicBadge status="ESTIMATE" />}
              sub="Building-level estimates within the matching radius"
            />
          </StatGrid>

          {/* Distribution and breakdowns */}
          <div className="grid gap-3 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardContent className="p-4 sm:p-5">
                <SectionTitle
                  action={
                    <span className="text-[12px] text-muted-foreground">
                      All wells, including unassessed
                    </span>
                  }
                >
                  Feasibility score distribution
                </SectionTitle>
                {data.score_histogram.length > 0 ? (
                  <div className="mt-3">
                    <ScoreHistogram data={data.score_histogram} />
                  </div>
                ) : (
                  <p className="mt-3 text-xs italic text-muted-foreground">
                    No wells have been assessed yet. Run an assessment from the
                    map or the well explorer.
                  </p>
                )}
                <p className="mt-2 text-[12px] leading-relaxed text-muted-foreground">
                  Scores are produced only by the deterministic Python scoring
                  engine. A well with no score is excluded from this
                  distribution rather than being counted as zero.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 sm:p-5">
                <SectionTitle>Recommendation</SectionTitle>
                <div className="mt-3">
                  <BreakdownBars
                    items={recommendationItems}
                    emptyLabel="No wells have been assessed yet."
                  />
                </div>
                <p className="mt-2.5 text-[12px] leading-relaxed text-muted-foreground">
                  Levels are assigned by the engine from the composite score. A
                  language model may explain a recommendation but cannot change
                  it.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 sm:p-5">
                <SectionTitle>Evidence confidence</SectionTitle>
                <div className="mt-3">
                  <BreakdownBars items={confidenceItems} />
                </div>
                <p className="mt-2.5 text-[12px] leading-relaxed text-muted-foreground">
                  Confidence describes the evidence, not the resource. A well
                  can be an excellent candidate that nobody has measured.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 sm:p-5">
                <SectionTitle>Region</SectionTitle>
                <div className="mt-3">
                  <BreakdownBars
                    items={regionItems}
                    emptyLabel="No regional attribution recorded."
                  />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 sm:p-5">
                <SectionTitle>Well status</SectionTitle>
                <div className="mt-3">
                  <BreakdownBars items={statusItems} />
                </div>
                <p className="mt-2.5 text-[12px] leading-relaxed text-muted-foreground">
                  Status drives both access and legal feasibility. A producing
                  well usually means a live licence and an operator relationship.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 sm:p-5">
                <SectionTitle>Original purpose</SectionTitle>
                <div className="mt-3">
                  <BreakdownBars items={purposeItems} />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 sm:p-5">
                <SectionTitle>Risk exposure by category</SectionTitle>
                <div className="mt-3">
                  <BreakdownBars
                    items={riskItems}
                    emptyLabel="No assessed risks recorded."
                  />
                </div>
                <p className="mt-2.5 text-[12px] leading-relaxed text-muted-foreground">
                  Exposure is the uncertainty-adjusted score summed across
                  wells, so a large number of minor unknowns outranks one
                  dramatic hazard.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 sm:p-5">
                <SectionTitle>Wells needing data</SectionTitle>
                <div className="mt-3 flex items-baseline gap-3">
                  <span className="tabular text-3xl font-semibold">
                    {data.wells_needing_more_data.toLocaleString("en-GB")}
                  </span>
                  <CircleHelp className="h-4 w-4 text-muted-foreground" aria-hidden />
                </div>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  Wells with at least one field the engineering model needs but
                  the source data does not contain. This is the work list for
                  anyone considering a data-gathering programme.
                </p>
                <Button variant="outline" size="sm" className="mt-3" asChild>
                  <Link href="/explorer">
                    Open the well explorer
                    <ArrowRight aria-hidden />
                  </Link>
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4 sm:p-5">
                <SectionTitle>What this page cannot tell you</SectionTitle>
                <ul className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
                  <li className="flex gap-1.5">
                    <Thermometer className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                    <span>
                      Per-well temperature provenance. A national count does not
                      say how many of these were measured by a stabilised bottom
                      hole survey rather than estimated from an analogue.
                    </span>
                  </li>
                  <li className="flex gap-1.5">
                    <Flame className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                    <span>
                      Whether any of this heat can actually be delivered. Thermal
                      decline, reinjection capacity and network losses all apply
                      after a well is chosen.
                    </span>
                  </li>
                  <li className="flex gap-1.5">
                    <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                    <span>
                      Commercial viability. Consent timelines, land access and
                      offtake are outside anything a desk screen can settle.
                    </span>
                  </li>
                </ul>
              </CardContent>
            </Card>
          </div>

          {data.caveats.length > 0 && (
            <Caveats items={data.caveats} title="Caveats returned by the API" />
          )}

          {Object.keys(data.recommendation_breakdown).length === 0 && (
            <EmptyState
              title="No assessments have been run"
              message="The score distribution, recommendation mix and confidence mix populate once wells have been assessed by the engineering pipeline."
              action={
                <Button size="sm" asChild>
                  <Link href="/">Open the map and run an assessment</Link>
                </Button>
              }
            />
          )}
        </div>
      </div>
    </>
  );
}