/**
 * Thermal analysis view.
 *
 * The organising question is not "what is the average temperature" but "which
 * of these numbers are measurements, and how do we know". A national mean of
 * measured and modelled temperatures is close to meaningless, so this page
 * leads with the method breakdown rather than the mean.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { ArrowRight, Thermometer } from "lucide-react";

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
import { BreakdownBars, type BreakdownItem } from "@/components/charts/charts";
import { Badge, EpistemicBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import {
  CONFIDENCE_META,
  MEASUREMENT_METHOD_LABELS,
  humanise,
  isDirectMeasurement,
} from "@/lib/domain";
import { fmtDepth } from "@/lib/utils";
import type { EpistemicStatus, NationalDashboard, WellSummary } from "@/types/api";

interface ScatterPoint {
  depth: number;
  temperature: number;
  score: number;
  status: EpistemicStatus;
  direct: boolean;
  name: string;
  wellId: string;
}

const STATUS_COLOUR: Record<EpistemicStatus, string> = {
  FACT: "#15803d",
  MEASURED: "#0d9488",
  DERIVED: "#0284c7",
  MODELLED: "#7c3aed",
  ESTIMATE: "#ca8a04",
  ASSUMPTION: "#ea580c",
  UNKNOWN: "#94a3b8",
};

export function ThermalView() {
  const dashboard = useApiData<NationalDashboard>(
    (signal) => api.nationalDashboard(true, signal),
    [],
  );

  const hottest = useApiData(
    (signal) =>
      api.searchWells(
        {
          order_by: "temperature_c",
          descending: true,
          min_temperature_c: 0,
          limit: 200,
        },
        signal,
      ),
    [],
  );

  const scatter = React.useMemo<ScatterPoint[]>(() => {
    if (!hottest.data) return [];
    return hottest.data.items
      .filter(
        (well): well is WellSummary & {
          temperature_c: number;
          total_depth_m: number;
        } =>
          well.temperature_c !== null && well.total_depth_m !== null,
      )
      .map((well) => ({
        depth: well.total_depth_m,
        temperature: well.temperature_c,
        score: well.feasibility_score ?? -1,
        status: well.temperature_status,
        direct: isDirectMeasurement(well.temperature_status),
        name: well.well_name,
        wellId: well.id,
      }));
  }, [hottest.data]);

  // Group by status so the chart can legend the provenance of each point.
  const byStatus = React.useMemo(() => {
    const groups = new Map<EpistemicStatus, ScatterPoint[]>();
    for (const point of scatter) {
      const existing = groups.get(point.status) ?? [];
      existing.push(point);
      groups.set(point.status, existing);
    }
    return Array.from(groups.entries());
  }, [scatter]);

  const methodItems: BreakdownItem[] = React.useMemo(() => {
    if (!hottest.data) return [];
    const counts = new Map<EpistemicStatus, number>();
    for (const well of hottest.data.items) {
      counts.set(well.temperature_status, (counts.get(well.temperature_status) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([status, value]) => ({
        key: status,
        label: status === "MEASURED" ? "Measured" : humanise(status),
        value,
        colour: STATUS_COLOUR[status],
      }))
      .sort((a, b) => b.value - a.value);
  }, [hottest.data]);

  const measuredShare =
    methodItems.length > 0
      ? (methodItems.find((item) => item.key === "MEASURED")?.value ?? 0) /
        methodItems.reduce((sum, item) => sum + item.value, 0)
      : null;

  return (
    <>
      <PageHeader
        title="Thermal analysis"
        subtitle="Temperature records across the inventory, separated by how they were obtained"
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="space-y-4 p-4">
          {dashboard.loading && !dashboard.data && (
            <Loading label="Loading thermal aggregates" />
          )}

          {dashboard.error && (
            <ErrorState message={dashboard.error} onRetry={dashboard.refresh} />
          )}

          {dashboard.data && (
            <>
              <Notice tone="warning" title="A national temperature mean is not a resource estimate">
                The figures below summarise what has been recorded, not what
                could be produced. A mean across wells mixes stabilised bottom-hole
                surveys with regional estimates, and the two do not carry the
                same weight. Every temperature shown on this page keeps its
                provenance label, and the well explorer will filter to the ones
                that are genuinely measured.
              </Notice>

              <StatGrid cols={4}>
                <StatTile
                  label="Wells with a temperature record"
                  value={dashboard.data.wells_with_temperature.toLocaleString("en-GB")}
                  sub={`of ${dashboard.data.total_wells.toLocaleString("en-GB")} in the inventory`}
                />
                <StatTile
                  label="Wells with none"
                  value={dashboard.data.wells_without_temperature.toLocaleString("en-GB")}
                  tone={dashboard.data.wells_without_temperature > 0 ? "warning" : "muted"}
                  sub="Unknown, not zero. These wells cannot be assessed thermally."
                />
                <StatTile
                  label="Mean of recorded temperatures"
                  value={
                    dashboard.data.average_temperature_c !== null
                      ? dashboard.data.average_temperature_c.toFixed(1)
                      : "Not available"
                  }
                  unit={dashboard.data.average_temperature_c !== null ? "°C" : undefined}
                  status={<EpistemicBadge status="DERIVED" />}
                  tone="muted"
                  sub="Mixes measured and modelled readings. Read it as a description of the data, not of the subsurface."
                />
                <StatTile
                  label="Mean depth of wells with a reading"
                  value={
                    dashboard.data.average_depth_m !== null
                      ? Math.round(dashboard.data.average_depth_m).toLocaleString("en-GB")
                      : "Not available"
                  }
                  unit={dashboard.data.average_depth_m !== null ? "m" : undefined}
                  status={<EpistemicBadge status="FACT" />}
                  tone="muted"
                />
              </StatGrid>

              <div className="grid gap-3 lg:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle>Temperature against depth</CardTitle>
                    <CardDescription>
                      Each point is one well. Colour and shape both carry the
                      provenance of the reading, so the pattern can be read
                      without the legend.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {scatter.length === 0 ? (
                      <EmptyState
                        title="No temperature readings to plot"
                        message="No well in the current inventory has both a temperature and a recorded depth."
                      />
                    ) : (
                      <>
                        <ResponsiveContainer width="100%" height={280}>
                          <ScatterChart margin={{ top: 8, right: 12, bottom: 20, left: -4 }}>
                            <CartesianGrid stroke="hsl(var(--border))" />
                            <XAxis
                              type="number"
                              dataKey="depth"
                              name="Depth"
                              unit="m"
                              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                              tickLine={false}
                              axisLine={false}
                              label={{
                                value: "Total depth (m)",
                                position: "insideBottom",
                                offset: -12,
                                fontSize: 9,
                                fill: "hsl(var(--muted-foreground))",
                              }}
                            />
                            <YAxis
                              type="number"
                              dataKey="temperature"
                              name="Temperature"
                              unit="°C"
                              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                              tickLine={false}
                              axisLine={false}
                              width={44}
                            />
                            <ZAxis type="number" dataKey="score" range={[45, 130]} />
                            <Tooltip
                              cursor={{ strokeDasharray: "3 3" }}
                              content={<ThermalTooltip />}
                            />
                            {byStatus.map(([status, points]) => (
                              <Scatter
                                key={status}
                                name={humanise(status)}
                                data={points}
                                fill={STATUS_COLOUR[status]}
                                fillOpacity={0.75}
                                shape={
                                  status === "MEASURED" ? "circle" : "diamond"
                                }
                              />
                            ))}
                          </ScatterChart>
                        </ResponsiveContainer>

                        <div className="mt-2 flex flex-wrap gap-2">
                          {byStatus.map(([status, points]) => (
                            <span
                              key={status}
                              className="flex items-center gap-1.5 text-[10px]"
                            >
                              <span
                                className={`h-2.5 w-2.5 ${
                                  status === "MEASURED" ? "rounded-full" : "rotate-45"
                                }`}
                                style={{ backgroundColor: STATUS_COLOUR[status] }}
                                aria-hidden
                              />
                              {humanise(status)} ({points.length})
                            </span>
                          ))}
                        </div>
                      </>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>How the readings were obtained</CardTitle>
                    <CardDescription>
                      The 200 hottest wells, grouped by provenance. Only{" "}
                      {measuredShare !== null
                        ? `${Math.round(measuredShare * 100)}%`
                        : "0%"}{" "}
                      of these rest on a direct instrument reading.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <BreakdownBars
                      items={methodItems}
                      emptyLabel="No temperature readings in the top 200 wells."
                    />
                    <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
                      An indirect method - a regional estimate, an analogue well,
                      a depth extrapolation, or a basin model output - can be
                      entirely reasonable and still be labelled as an estimate.
                      The label describes what was observed, not how good the
                      number is.
                    </p>
                  </CardContent>
                </Card>
              </div>
            </>
          )}

          {/* Hottest wells */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Thermometer className="h-4 w-4" aria-hidden />
                Hottest wells on record
              </CardTitle>
              <CardDescription>
                Ordered by recorded temperature. A high temperature does not
                imply a high score: depth, deliverability, integrity, distance to
                demand and regulatory burden all carry independent weight.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {hottest.loading && !hottest.data && <Loading label="Loading wells" compact />}
              {hottest.data && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Well</TableHead>
                      <TableHead>Region</TableHead>
                      <TableHead className="text-right">Depth</TableHead>
                      <TableHead className="text-right">Temperature</TableHead>
                      <TableHead>Provenance</TableHead>
                      <TableHead>Method</TableHead>
                      <TableHead>Confidence</TableHead>
                      <TableHead className="text-right">Score</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {hottest.data.items.slice(0, 40).map((well) => (
                      <TableRow key={well.id}>
                        <TableCell>
                          <Link
                            href={`/wells/${well.id}`}
                            className="font-medium hover:text-primary hover:underline"
                          >
                            {well.well_name}
                          </Link>
                          <div className="font-mono text-[10px] text-muted-foreground">
                            {well.well_id}
                          </div>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {well.region ?? "Not recorded"}
                        </TableCell>
                        <TableCell className="text-right">
                          {fmtDepth(well.total_depth_m)}
                        </TableCell>
                        <TableCell className="text-right">
                          {well.temperature_c !== null ? (
                            <span className="inline-flex items-center gap-1">
                              {well.temperature_c.toFixed(1)} °C
                              <EpistemicBadge status={well.temperature_status} />
                            </span>
                          ) : (
                            <span className="text-[11px] italic text-muted-foreground">
                              Not available
                            </span>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-[9px]">
                            {humanise(well.temperature_status)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {MEASUREMENT_METHOD_LABELS[
                            well.temperature_status.toLowerCase()
                          ] ?? humanise(well.temperature_status)}
                        </TableCell>
                        <TableCell>
                          <span
                            className={`text-[11px] ${CONFIDENCE_META[well.temperature_confidence].className}`}
                          >
                            {CONFIDENCE_META[well.temperature_confidence].label}
                          </span>
                        </TableCell>
                        <TableCell className="text-right">
                          {well.feasibility_score !== null
                            ? Math.round(well.feasibility_score)
                            : <span className="text-[11px] italic text-muted-foreground">Not assessed</span>}
                        </TableCell>
                        <TableCell>
                          <Button variant="ghost" size="icon-sm" asChild>
                            <Link href={`/wells/${well.id}`} aria-label="Open well">
                              <ArrowRight className="h-3 w-3" aria-hidden />
                            </Link>
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              {hottest.data && hottest.data.total > hottest.data.items.length && (
                <Button variant="outline" size="sm" className="mt-3" asChild>
                  <Link href="/candidates">
                    See the full ranking of {hottest.data.total.toLocaleString("en-GB")} wells
                  </Link>
                </Button>
              )}
            </CardContent>
          </Card>

          {dashboard.data && dashboard.data.caveats.length > 0 && (
            <Caveats items={dashboard.data.caveats} />
          )}

          <Card>
            <CardContent className="p-4">
              <SectionTitle>Why method matters more than magnitude</SectionTitle>
              <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-muted-foreground">
                <li className="flex gap-1.5">
                  <span aria-hidden>·</span>
                  <span>
                    A stabilised bottom-hole survey is the only method that
                    supports a thermal output figure above the 40 °C range with
                    anything better than an estimate label.
                  </span>
                </li>
                <li className="flex gap-1.5">
                  <span aria-hidden>·</span>
                  <span>
                    A maximum dynamic temperature overstates the producible
                    figure, because the well cools while it flows. The engine
                    flags non-stabilised readings rather than silently averaging
                    them in.
                  </span>
                </li>
                <li className="flex gap-1.5">
                  <span aria-hidden>·</span>
                  <span>
                    A DTS log gives the shape of the temperature profile but not
                    necessarily the final stabilised value, so it is labelled
                    separately from a static survey.
                  </span>
                </li>
                <li className="flex gap-1.5">
                  <span aria-hidden>·</span>
                  <span>
                    Modelled and extrapolated temperatures exist for many UK
                    wells because no survey was run. That is a real gap in the
                    evidence, and it is shown as one.
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

function ThermalTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ScatterPoint; name: string }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0]?.payload;
  if (!point) return null;

  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-[11px] shadow-md">
      <div className="mb-1 font-medium">{point.name}</div>
      <div className="tabular">
        {point.temperature.toFixed(1)} °C at {Math.round(point.depth).toLocaleString("en-GB")} m
      </div>
      <div className="mt-0.5 text-[10px] text-muted-foreground">
        {humanise(point.status)} ·{" "}
        {point.direct ? "direct instrument reading" : "indirect method"}
      </div>
      <Link
        href={`/wells/${point.wellId}`}
        className="mt-1 inline-flex items-center gap-1 text-primary hover:underline"
      >
        Open the well record
        <ArrowRight className="h-2.5 w-2.5" aria-hidden />
      </Link>
    </div>
  );
}