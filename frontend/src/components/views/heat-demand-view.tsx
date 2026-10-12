/**
 * Heat demand view.
 *
 * Demand is the side of the assessment that decides whether a well matters. A
 * 90 °C well two kilometres from nothing is not a heating opportunity, and a
 * 55 °C well inside a dense housing estate might be. This page exists to make
 * that distance explicit, and it is careful never to present a straight-line
 * corridor as a route.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import {
  Building2,
  Droplets,
  Flame,
  Route,
  TriangleAlert,
} from "lucide-react";

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
import { BreakdownBars, type BreakdownItem } from "@/components/charts/charts";
import { WellMap } from "@/components/map/well-map";
import { Badge, EpistemicBadge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import type { MapFeature } from "@/lib/basemap";
import { humanise } from "@/lib/domain";
import type { HeatCluster } from "@/types/api";
import { wellKey } from "@/lib/utils";

export function HeatDemandView() {
  const summary = useApiData((signal) => api.demandSummary(signal), []);
  const clusters = useApiData<HeatCluster[]>(
    (signal) => api.heatClusters({ min_demand_kwh: 50_000 }, signal),
    [],
  );
  const corridors = useApiData(
    (signal) => api.corridors({ limit_wells: 60, max_distance_m: 5000 }, signal),
    [],
  );

  const typeItems: BreakdownItem[] = React.useMemo(() => {
    if (!summary.data) return [];
    return Object.entries(summary.data.by_building_type)
      .map(([key, value]) => ({
        key,
        label: humanise(key),
        value: Math.round(value.demand_kwh / 1000),
      }))
      .sort((a, b) => b.value - a.value);
  }, [summary.data]);

  const fuelItems: BreakdownItem[] = React.useMemo(() => {
    if (!summary.data) return [];
    return Object.entries(summary.data.by_fuel)
      .map(([key, value]) => ({
        key,
        label: humanise(key),
        value: Math.round(value.demand_kwh / 1000),
      }))
      .sort((a, b) => b.value - a.value);
  }, [summary.data]);

  const clusterFeatures: MapFeature[] = React.useMemo(
    () =>
      (clusters.data ?? []).map((cluster) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [cluster.centroid_longitude, cluster.centroid_latitude],
        },
        properties: {
          cluster_id: cluster.cluster_id,
          buildings: cluster.building_count,
          demand_kwh: cluster.total_annual_demand_kwh,
          nearest_well: cluster.nearest_well_id,
        },
      })),
    [clusters.data],
  );

  const corridorFeatures: MapFeature[] = React.useMemo(
    () =>
      (corridors.data?.corridors ?? []).map((corridor) => ({
        type: "Feature",
        geometry: corridor.geometry,
        properties: {
          well_id: corridor.well_id,
          well_name: corridor.well_name,
          distance_m: corridor.distance_m,
        },
      })),
    [corridors.data],
  );

  return (
    <>
      <PageHeader
        title="Heat demand"
        subtitle="Where the heat would have to go, and how far it is from the wells"
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="space-y-4 p-4">
          <Notice tone="warning" title="Demand here is modelled, not metered">
            Building heat demand is derived from floor area and building type
            using standard UK factors. It is a screening estimate for comparing
            locations, not a substitute for a heat audit. A single large
            industrial site can hold more demand than a thousand houses, and this
            data will not show you which.
          </Notice>

          {summary.loading && !summary.data && <Loading label="Aggregating demand" />}
          {summary.error && (
            <ErrorState message={summary.error} onRetry={summary.refresh} />
          )}

          {summary.data && (
            <>
              <StatGrid cols={3}>
                <StatTile
                  label="Buildings in the demand dataset"
                  value={summary.data.totals.buildings.toLocaleString("en-GB")}
                  status={<EpistemicBadge status="FACT" />}
                  sub="Counted directly from the building dataset"
                />
                <StatTile
                  label="Modelled annual demand"
                  value={summary.data.totals.annual_demand_gwh.toFixed(1)}
                  unit="GWh/yr"
                  status={<EpistemicBadge status="ESTIMATE" />}
                  tone="muted"
                  sub="Floor area × type factor. Not metered consumption."
                />
                <StatTile
                  label="Coincident peak demand"
                  value={Math.round(summary.data.totals.peak_demand_kw).toLocaleString("en-GB")}
                  unit="kW"
                  status={<EpistemicBadge status="ESTIMATE" />}
                  tone="muted"
                  sub="Peak across all buildings simultaneously, which overstates a real network's peak because demand is not coincident."
                />
              </StatGrid>

              {summary.data.caveat && (
                <p className="rounded-md border bg-muted/40 p-2.5 text-xs leading-relaxed text-muted-foreground">
                  {summary.data.caveat}
                </p>
              )}

              <div className="grid gap-3 lg:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Building2 className="h-4 w-4" aria-hidden />
                      Demand by building type
                    </CardTitle>
                    <CardDescription>
                      Megawatt-hours per year across the modelled building set.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <BreakdownBars items={typeItems} emptyLabel="No buildings loaded." />
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Droplets className="h-4 w-4" aria-hidden />
                      Demand by incumbent fuel
                    </CardTitle>
                    <CardDescription>
                      Where heat is currently bought. Gas-dominated districts are
                      the least attractive conversion targets: the incumbent is
                      already cheap and the decarbonisation case is weakest.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <BreakdownBars items={fuelItems} emptyLabel="No buildings loaded." />
                  </CardContent>
                </Card>
              </div>
            </>
          )}

          {/* Map */}
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Flame className="h-4 w-4" aria-hidden />
                Demand clusters and indicative corridors
              </CardTitle>
              <CardDescription>
                Amber circles are aggregated demand clusters, sized by building
                count. Dashed teal lines join each well to its nearest demand
                centroid.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {corridors.data && (
                <Notice tone="danger" title="Corridors are straight lines, not routes">
                  {corridors.data.caveat} The total straight-line length of{" "}
                  {corridors.data.total_straight_line_length_km.toFixed(0)} km is
                  a lower bound on any real network, and a routing exercise would
                  not change that figure enough to matter for screening.
                </Notice>
              )}

              <WellMap
                wells={[]}
                clusters={clusterFeatures}
                corridors={corridorFeatures}
                showClusters
                showCorridors
                className="h-[26rem] w-full rounded-md"
              />
            </CardContent>
          </Card>

          {/* Clusters */}
          <Card>
            <CardHeader>
              <CardTitle>Demand clusters</CardTitle>
              <CardDescription>
                Spatial aggregation of buildings into cells. Clustering is a
                convenience for reading the map, not a district heating scheme.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {clusters.loading && !clusters.data && (
                <Loading label="Clustering buildings" compact />
              )}
              {clusters.data && clusters.data.length === 0 && (
                <EmptyState
                  title="No clusters above the demand threshold"
                  message="Lower the minimum demand, or ingest a building dataset with more coverage."
                />
              )}
              {clusters.data && clusters.data.length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Cluster</TableHead>
                      <TableHead className="text-right">Buildings</TableHead>
                      <TableHead className="text-right">Annual demand</TableHead>
                      <TableHead className="text-right">Peak</TableHead>
                      <TableHead>Dominant type</TableHead>
                      <TableHead>Nearest well</TableHead>
                      <TableHead className="text-right">Distance</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {clusters.data.slice(0, 40).map((cluster) => (
                      <TableRow key={cluster.cluster_id}>
                        <TableCell>
                          <span className="font-mono text-[12px]">
                            {cluster.cluster_id}
                          </span>
                          {!cluster.is_clustered_with_postgis && (
                            <Badge variant="muted" className="ml-1.5 text-[11px]">
                              grid fallback
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {cluster.building_count.toLocaleString("en-GB")}
                        </TableCell>
                        <TableCell className="text-right">
                          {(cluster.total_annual_demand_kwh / 1000).toFixed(0)} MWh
                          <span className="ml-1">
                            <EpistemicBadge status="ESTIMATE" />
                          </span>
                        </TableCell>
                        <TableCell className="text-right">
                          {Math.round(cluster.total_peak_demand_kw).toLocaleString("en-GB")} kW
                        </TableCell>
                        <TableCell>
                          {cluster.dominant_building_type
                            ? humanise(cluster.dominant_building_type)
                            : <span className="italic text-muted-foreground">Mixed</span>}
                        </TableCell>
                        <TableCell>
                          {cluster.nearest_well_id ? (
                            <Link
                              href={`/wells/${cluster.nearest_well_uuid ?? cluster.nearest_well_id}`}
                              className="text-primary hover:underline"
                            >
                              {cluster.nearest_well_id}
                            </Link>
                          ) : (
                            <span className="text-xs italic text-muted-foreground">
                              None within range
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {cluster.nearest_well_distance_m !== null
                            ? `${Math.round(cluster.nearest_well_distance_m).toLocaleString("en-GB")} m`
                            : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Corridors */}
          {corridors.data && corridors.data.corridors.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Route className="h-4 w-4" aria-hidden />
                  Nearest demand for each well
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Well</TableHead>
                      <TableHead className="text-right">Straight-line distance</TableHead>
                      <TableHead className="text-right">Target demand</TableHead>
                      <TableHead>Note</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {corridors.data.corridors.slice(0, 40).map((corridor) => (
                      <TableRow key={corridor.well_id}>
                        <TableCell>
                          <Link
                            href={`/wells/${wellKey(corridor)}`}
                            className="font-medium hover:text-primary hover:underline"
                          >
                            {corridor.well_name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right">
                          {(corridor.distance_m / 1000).toFixed(2)} km
                        </TableCell>
                        <TableCell className="text-right">
                          {corridor.target_demand_kwh !== null
                            ? `${(corridor.target_demand_kwh / 1000).toFixed(0)} MWh`
                            : "Not available"}
                        </TableCell>
                        <TableCell className="text-[12px] text-muted-foreground">
                          {corridor.indicative && (
                            <TriangleAlert
                              className="mr-1 inline h-3 w-3 text-priority-medium"
                              aria-hidden
                            />
                          )}
                          {corridor.note}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <SectionTitle className="mt-3">
                  How this feeds the score
                </SectionTitle>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  The demand component of the feasibility score uses both the
                  proximity of matched demand and the distance the network would
                  have to cover, because a well 4 km from a district loses most of
                  its output to distribution loss before it arrives. The network
                  component scores that separately, so a long run is visible as
                  its own weakness rather than being hidden inside the demand
                  score.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}