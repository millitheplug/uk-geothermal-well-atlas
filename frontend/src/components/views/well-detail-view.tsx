/**
 * Full well record and assessment.
 *
 * Structured so a reader can answer three questions in order: what is this
 * borehole, what has the engine concluded about it, and what would need to be
 * true for that conclusion to change. Everything that could change it - the
 * trace, the evidence, the overrides - is on the same page rather than behind
 * a menu.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  ChevronRight,
  ExternalLink,
  Flame,
  Play,
  Ruler,
  TriangleAlert,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import {
  ErrorState,
  KeyValueList,
  Loading,
  Notice,
  SectionTitle,
} from "@/components/common/feedback";
import {
  Badge,
  EpistemicBadge,
  MockDataBanner,
} from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/primitives";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AssessmentProgress,
  FeasibilityHeadline,
  KeyFiguresGrid,
} from "@/components/analysis/assessment-panels";
import {
  AssuranceFooter,
  ConfidencePanel,
  DecisionStrip,
  RiskPanel,
  ScoreBreakdown,
} from "@/components/analysis/explain-panels";
import {
  AgentPanel,
  EvidencePanel,
  RegulatoryPanel,
  TracePanel,
  ValidationPanel,
} from "@/components/analysis/provenance-panels";
import { ScenarioPanel, WhatIfPanel } from "@/components/analysis/whatif-panel";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import {
  CONFIDENCE_META,
  CONFIGURATION_DESCRIPTIONS,
  CONFIGURATION_LABELS,
  MEASUREMENT_METHOD_LABELS,
  WELL_STATUS_LABELS,
  humanise,
  isDirectMeasurement,
} from "@/lib/domain";
import { fmtDate, fmtDepth, fmtGBP } from "@/lib/utils";
import type {
  AnalysisProgress as ProgressType,
  AnalysisResult,
  WellDetail,
} from "@/types/api";

export function WellDetailView() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const wellId = params?.id;

  const [analysis, setAnalysis] = React.useState<AnalysisResult | null>(null);
  const [progress, setProgress] = React.useState<ProgressType | null>(null);
  const [running, setRunning] = React.useState(false);
  const [runError, setRunError] = React.useState<string | null>(null);
  const [includeAi, setIncludeAi] = React.useState(true);

  const well = useApiData<WellDetail>(
    (signal) => api.getWell(wellId!, signal),
    [wellId],
    { skip: !wellId },
  );

  const demand = useApiData(
    (signal) => api.getWellDemand(wellId!, { radius_m: 2000, limit: 100 }, signal),
    [wellId],
    { skip: !wellId },
  );

  const run = async () => {
    if (!wellId) return;
    setRunning(true);
    setRunError(null);
    setProgress(null);
    try {
      const result = await api.runAnalysis(wellId, {}, includeAi);
      setAnalysis(result);
    } catch (caught) {
      setRunError(
        caught instanceof Error
          ? caught.message
          : "The assessment could not be completed.",
      );
    } finally {
      setRunning(false);
    }
  };

  // Load the most recent stored analysis so the page is useful on arrival
  // rather than presenting an empty shell that the user has to fill in.
  React.useEffect(() => {
    if (!wellId || analysis) return;
    let cancelled = false;
    api
      .listAnalyses({ well_id: wellId, limit: 1 })
      .then((results) => {
        if (cancelled) return;
        if (results.length > 0) setAnalysis(results[0] ?? null);
      })
      .catch(() => {
        // No stored analysis is the normal case, not an error.
      });
    return () => {
      cancelled = true;
    };
  }, [wellId, analysis]);

  if (well.loading && !well.data) {
    return (
      <>
        <PageHeader title="Loading well…" />
        <Loading label="Fetching the well record" />
      </>
    );
  }

  if (well.error || !well.data) {
    return (
      <>
        <PageHeader title="Well record" />
        <div className="p-4">
          <ErrorState
            title="This well could not be loaded"
            message={well.error}
            isOffline={well.error?.includes("Could not reach")}
            onRetry={well.refresh}
            hint={
              well.error?.includes("404") ||
              well.error?.includes("not visible")
                ? "Wells are national reference data but are only reachable once they are referenced by a project or analysis belonging to your organisation."
                : undefined
            }
          />
          <Button variant="outline" size="sm" className="mt-3" asChild>
            <Link href="/explorer">
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
              Back to the explorer
            </Link>
          </Button>
        </div>
      </>
    );
  }

  const record = well.data;

  return (
    <>
      <PageHeader
        title={record.well_name}
        subtitle={`${record.well_id} · ${record.region ?? "region not recorded"} · ${WELL_STATUS_LABELS[record.status] ?? humanise(record.status)}`}
        actions={
          <>
            <Button variant="outline" size="sm" asChild>
              <Link href="/explorer">
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
                Explorer
              </Link>
            </Button>
            <Button
              size="sm"
              onClick={() => void run()}
              disabled={running}
              loading={running}
            >
              {!running && <Play className="h-3.5 w-3.5" aria-hidden />}
              {running
                ? "Assessing…"
                : analysis
                  ? "Re-run assessment"
                  : "Run assessment"}
            </Button>
          </>
        }
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="space-y-4 p-4">
          {record.is_mock && <MockDataBanner isMock what="every figure on this page" />}

          {/* Identity strip */}
          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            <Badge variant="secondary">
              {WELL_STATUS_LABELS[record.status] ?? humanise(record.status)}
            </Badge>
            {record.original_purpose && (
              <Badge variant="outline">Originally {humanise(record.original_purpose)}</Badge>
            )}
            {record.formation && <Badge variant="outline">{record.formation}</Badge>}
            {record.basin && <Badge variant="outline">{record.basin}</Badge>}
            {record.is_deviated && <Badge variant="outline">Deviated</Badge>}
            {record.has_wellhead === false && (
              <Badge variant="outline">No wellhead recorded</Badge>
            )}
            <span className="ml-auto font-mono text-[10px] text-muted-foreground">
              {record.source}
              {record.dataset_version ? ` · v${record.dataset_version}` : ""}
            </span>
          </div>

          {runError && (
            <Notice tone="danger" title="The assessment failed">
              {runError}
            </Notice>
          )}

          {progress && !running && (
            <Card>
              <CardContent className="p-4">
                <AssessmentProgress
                  stage={progress.stage}
                  completedStages={progress.completed_stages}
                  percentComplete={progress.percent_complete}
                  stageMessages={progress.stage_messages}
                  errorMessage={progress.error_message}
                />
              </CardContent>
            </Card>
          )}

          {/* ---- Record ---- */}
          <div className="grid gap-3 lg:grid-cols-3">
            <Card>
              <CardContent className="p-4">
                <SectionTitle>Borehole</SectionTitle>
                <div className="mt-2">
                  <KeyValueList
                    dense
                    items={[
                      {
                        label: "Operator",
                        value: record.operator ?? "Not recorded",
                        missing: !record.operator,
                      },
                      {
                        label: "Licence",
                        value: record.licence ?? "Not recorded",
                        missing: !record.licence,
                      },
                      {
                        label: "Commissioned",
                        value: record.commissioned_date
                          ? fmtDate(record.commissioned_date)
                          : "Not recorded",
                        missing: !record.commissioned_date,
                      },
                      {
                        label: "P&A date",
                        value: record.plugged_and_abandoned_date
                          ? fmtDate(record.plugged_and_abandoned_date)
                          : record.status === "plugged_abandoned"
                            ? "Recorded, date unknown"
                            : "Not abandoned",
                        missing: !record.plugged_and_abandoned_date,
                      },
                      {
                        label: "Total depth (MD)",
                        value: fmtDepth(record.md_m),
                        missing: record.md_m === null,
                      },
                      {
                        label: "Total depth (TVD)",
                        value: fmtDepth(record.tvd_m ?? record.total_depth_m),
                        missing: record.tvd_m === null,
                      },
                      {
                        label: "Max deviation",
                        value:
                          record.max_deviation_deg !== null
                            ? `${record.max_deviation_deg.toFixed(1)}°`
                            : "Not recorded",
                        missing: record.max_deviation_deg === null,
                      },
                      {
                        label: "Casing",
                        value: record.casing_string ?? "No casing record",
                        missing: !record.casing_string,
                      },
                      {
                        label: "Completion",
                        value: record.completion_type
                          ? humanise(record.completion_type)
                          : "Not recorded",
                        missing: !record.completion_type,
                      },
                      {
                        label: "Loggable",
                        value:
                          record.loggable === null
                            ? "Unknown"
                            : record.loggable
                              ? "Yes"
                              : "No",
                        missing: record.loggable === null,
                      },
                    ]}
                  />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <SectionTitle>Temperature record</SectionTitle>
                {record.temperature_c !== null ? (
                  <div className="mt-2">
                    <div className="flex items-baseline gap-2">
                      <span className="tabular text-3xl font-semibold">
                        {record.temperature_c.toFixed(1)}
                      </span>
                      <span className="text-sm text-muted-foreground">°C</span>
                      <EpistemicBadge status={record.temperature_status} expanded />
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      At {fmtDepth(record.temperature_depth_m)} via{" "}
                      {MEASUREMENT_METHOD_LABELS[record.temperature_source ?? ""] ??
                        humanise(record.temperature_source ?? "unknown method")}
                      {isDirectMeasurement(record.temperature_source)
                        ? ""
                        : " — an indirect method, so this is not a direct measurement"}
                      .
                    </p>
                    <p className="mt-1 text-[11px]">
                      Confidence:{" "}
                      <span
                        className={CONFIDENCE_META[record.temperature_confidence].className}
                      >
                        {CONFIDENCE_META[record.temperature_confidence].label}
                      </span>
                    </p>
                    {record.temperature_variability_c !== null &&
                      record.temperature_variability_c > 5 && (
                        <p className="mt-2 rounded border border-priority-medium/40 bg-priority-medium/5 p-2 text-[10px] leading-relaxed text-priority-medium">
                          Sources for this well span{" "}
                          {record.temperature_variability_c.toFixed(1)} K. The
                          engine has taken the deepest stabilised reading and
                          downgraded confidence, but a spread this wide means the
                          temperature is not established to the precision the
                          engineering model needs.
                        </p>
                      )}
                  </div>
                ) : (
                  <div className="mt-2 rounded border border-epistemic-unknown/40 bg-epistemic-unknown/5 p-2.5">
                    <p className="flex items-center gap-1.5 text-xs font-medium">
                      <TriangleAlert
                        className="h-3.5 w-3.5 text-epistemic-unknown"
                        aria-hidden
                      />
                      Unknown
                    </p>
                    <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                      No temperature measurement exists for this well. Thermal
                      potential is unknown, not zero, and it gates the whole
                      assessment: the thermal component carries 25% of the score.
                    </p>
                  </div>
                )}

                {record.temperatures.length > 0 && (
                  <div className="mt-3">
                    <SectionTitle>
                      All readings ({record.temperatures.length})
                    </SectionTitle>
                    <ul className="mt-1.5 space-y-1">
                      {record.temperatures.map((reading) => (
                        <li
                          key={reading.id}
                          className="flex items-start justify-between gap-2 border-b pb-1 text-[11px] last:border-0"
                        >
                          <div className="min-w-0">
                            <span className="tabular font-medium">
                              {reading.temperature_c.toFixed(1)} °C at{" "}
                              {fmtDepth(reading.depth_m)}
                            </span>
                            <span className="block text-[10px] text-muted-foreground">
                              {MEASUREMENT_METHOD_LABELS[reading.measurement_method] ??
                                humanise(reading.measurement_method)}
                              {reading.geothermal_gradient_c_per_km !== null &&
                                ` · ${reading.geothermal_gradient_c_per_km.toFixed(1)} °C/km`}
                              {reading.measured_at &&
                                ` · ${fmtDate(reading.measured_at)}`}
                            </span>
                          </div>
                          <span className="flex shrink-0 flex-col items-end gap-0.5">
                            <EpistemicBadge status={reading.status} />
                            {!reading.is_final_stabilised && (
                              <span className="text-[9px] text-destructive">
                                not stabilised
                              </span>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <SectionTitle>Integrity</SectionTitle>
                {record.integrity ? (
                  <div className="mt-2">
                    <KeyValueList
                      dense
                      items={[
                        {
                          label: "Status",
                          value: (
                            <span className="inline-flex items-center gap-1.5">
                              {humanise(record.integrity.status)}
                              <EpistemicBadge status={record.integrity.status_status} />
                            </span>
                          ),
                        },
                        {
                          label: "Confidence",
                          value:
                            CONFIDENCE_META[record.integrity.confidence]?.label ??
                            record.integrity.confidence,
                        },
                        {
                          label: "Re-equipment",
                          value:
                            record.integrity.requires_reequipment === null
                              ? "Unknown"
                              : record.integrity.requires_reequipment
                                ? "Required"
                                : "Not indicated",
                          missing: record.integrity.requires_reequipment === null,
                        },
                        {
                          label: "Recompletion CAPEX",
                          value:
                            record.integrity.estimated_recompletion_capex_gbp !== null
                              ? fmtGBP(
                                  record.integrity.estimated_recompletion_capex_gbp,
                                )
                              : "Not available",
                          missing:
                            record.integrity.estimated_recompletion_capex_gbp ===
                            null,
                        },
                        {
                          label: "Gas hazard",
                          value:
                            record.integrity.gas_hazard === null
                              ? "Unknown"
                              : record.integrity.gas_hazard
                                ? "Indicated"
                                : "Not indicated",
                          missing: record.integrity.gas_hazard === null,
                        },
                        {
                          label: "Last check",
                          value: record.integrity.last_integrity_check_date
                            ? fmtDate(record.integrity.last_integrity_check_date)
                            : "No check recorded",
                          missing: !record.integrity.last_integrity_check_date,
                        },
                        ...(record.integrity.corrosion_evidence
                          ? [
                              {
                                label: "Corrosion",
                                value: record.integrity.corrosion_evidence,
                              },
                            ]
                          : []),
                        ...(record.integrity.scaling_evidence
                          ? [
                              {
                                label: "Scaling",
                                value: record.integrity.scaling_evidence,
                              },
                            ]
                          : []),
                      ]}
                    />
                    {record.integrity.unknown_reasons && (
                      <p className="mt-2 rounded border border-epistemic-unknown/40 bg-epistemic-unknown/5 p-2 text-[10px] leading-relaxed text-muted-foreground">
                        {record.integrity.unknown_reasons}
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                    Integrity carries 20% of the score, second only to thermal, and
                    cannot be established from desk study. Without it the engine
                    records a data gap rather than guessing a condition.
                  </p>
                )}

                {record.bottomhole_pressure_bar !== null && (
                  <div className="mt-3 border-t pt-2">
                    <div className="text-[10px] text-muted-foreground">
                      Bottom-hole pressure
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <span className="tabular text-sm font-medium">
                        {record.bottomhole_pressure_bar.toFixed(1)} bar
                      </span>
                      <EpistemicBadge status={record.pressure_status} />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Demand */}
          <Card>
            <CardContent className="p-4">
              <SectionTitle>Matched heat demand (2,000 m radius)</SectionTitle>
              {demand.loading && !demand.data && (
                <Loading label="Matching demand" compact />
              )}
              {demand.data && (
                <div className="mt-2 grid gap-4 md:grid-cols-[auto_1fr]">
                  <div className="flex gap-5">
                    <div>
                      <div className="tabular text-2xl font-semibold">
                        {demand.data.total_annual_demand_kwh.toLocaleString("en-GB")}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                        kWh/yr nearby
                        <span className="ml-1">
                          <EpistemicBadge status="ESTIMATE" />
                        </span>
                      </div>
                    </div>
                    <div>
                      <div className="tabular text-2xl font-semibold">
                        {demand.data.building_count.toLocaleString("en-GB")}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                        buildings
                      </div>
                    </div>
                    <div>
                      <div className="tabular text-2xl font-semibold">
                        {demand.data.nearest_building_distance_m !== null
                          ? Math.round(demand.data.nearest_building_distance_m)
                          : "—"}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                        m to nearest
                        <span className="ml-1">
                          <EpistemicBadge status="MEASURED" />
                        </span>
                      </div>
                    </div>
                  </div>

                  <div>
                    {demand.data.notes.length > 0 && (
                      <ul className="space-y-0.5 text-[11px] leading-relaxed text-muted-foreground">
                        {demand.data.notes.map((note, index) => (
                          <li key={index}>· {note}</li>
                        ))}
                      </ul>
                    )}
                    <p className="mt-2 text-[10px] text-muted-foreground">
                      Distances computed with{" "}
                      <code className="font-mono">{demand.data.spatial_dialect}</code>.
                      Building demand is modelled from floor area and type, not
                      metered.
                    </p>
                  </div>
                </div>
              )}

              {demand.data && demand.data.buildings.length > 0 && (
                <details className="mt-3">
                  <summary className="cursor-pointer text-[11px] font-medium text-primary">
                    Show the {demand.data.buildings.length} nearest buildings
                  </summary>
                  <ul className="mt-2 max-h-64 space-y-1 overflow-auto text-[11px]">
                    {demand.data.buildings.map((building) => (
                      <li
                        key={building.id}
                        className="flex items-baseline justify-between gap-3 border-b pb-1 last:border-0"
                      >
                        <span className="min-w-0">
                          <span className="block truncate">
                            {humanise(building.building_type)}
                            {building.postcode ? ` · ${building.postcode}` : ""}
                          </span>
                          <span className="block text-[10px] text-muted-foreground">
                            {building.current_fuel
                              ? humanise(building.current_fuel)
                              : "Fuel unknown"}
                            {building.required_supply_temperature_c !== null &&
                              ` · needs ${building.required_supply_temperature_c.toFixed(0)} °C`}
                          </span>
                        </span>
                        <span className="shrink-0 text-right tabular">
                          {Math.round(building.distance_m)} m
                          <span className="block text-[10px] text-muted-foreground">
                            {building.annual_heat_demand_kwh !== null
                              ? `${(building.annual_heat_demand_kwh / 1000).toFixed(0)} MWh/yr`
                              : "Demand unknown"}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </CardContent>
          </Card>

          <Separator />

          {/* ---- Assessment ---- */}
          {analysis ? (
            <Assessment
              analysis={analysis}
              wellId={record.id}
              onResult={setAnalysis}
              includeAi={includeAi}
              onIncludeAiChange={setIncludeAi}
              runError={runError}
            />
          ) : (
            <Card>
              <CardContent className="p-6 text-center">
                <Ruler className="mx-auto h-6 w-6 text-muted-foreground" aria-hidden />
                <p className="mt-2 text-sm font-medium">
                  This well has not been assessed
                </p>
                <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
                  A feasibility score exists only after the deterministic
                  engineering pipeline has run: thermal, integrity, demand,
                  network, economics, risk, then the weighted composite. It takes
                  a few seconds and nothing is inferred from the record alone.
                </p>
                <Button
                  className="mt-3"
                  onClick={() => void run()}
                  disabled={running}
                  loading={running}
                >
                  Run the assessment
                </Button>
              </CardContent>
            </Card>
          )}

          {/* ---- Provenance ---- */}
          <Card>
            <CardContent className="p-4">
              <SectionTitle>Record provenance</SectionTitle>
              <div className="mt-2 grid gap-x-8 gap-y-2 md:grid-cols-2">
                <KeyValueList
                  dense
                  items={[
                    { label: "Source adapter", value: <code>{record.source}</code> },
                    {
                      label: "Dataset version",
                      value: record.dataset_version ?? "Not recorded",
                      missing: !record.dataset_version,
                    },
                    {
                      label: "Data completeness",
                      value:
                        record.data_completeness !== null
                          ? `${Math.round(record.data_completeness * 100)}%`
                          : "Not assessed",
                      missing: record.data_completeness === null,
                    },
                    {
                      label: "Last assessed",
                      value: record.analysed_at
                        ? new Date(record.analysed_at).toLocaleString("en-GB")
                        : "Never",
                      missing: !record.analysed_at,
                    },
                  ]}
                />
                <KeyValueList
                  dense
                  items={[
                    {
                      label: "Source URL",
                      value: record.source_url ? (
                        <a
                          href={record.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-primary hover:underline"
                        >
                          Open
                          <ExternalLink className="h-2.5 w-2.5" aria-hidden />
                        </a>
                      ) : (
                        "Not recorded"
                      ),
                      missing: !record.source_url,
                    },
                    {
                      label: "Analysis version",
                      value: record.analysis_version ?? "Not recorded",
                      missing: !record.analysis_version,
                    },
                  ]}
                />
              </div>

              {record.known_data_gaps &&
                Object.keys(record.known_data_gaps).length > 0 && (
                  <div className="mt-3 border-t pt-2">
                    <SectionTitle>Known gaps in this record</SectionTitle>
                    <ul className="mt-1.5 space-y-0.5 text-[11px] text-muted-foreground">
                      {Object.entries(record.known_data_gaps).map(([field, note]) => (
                        <li key={field} className="flex gap-1.5">
                          <span aria-hidden>·</span>
                          <span>
                            <code className="font-mono">{field}</code>: {note}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

              {record.logs.length > 0 && (
                <div className="mt-3 border-t pt-2">
                  <SectionTitle>Well logs ({record.logs.length})</SectionTitle>
                  <ul className="mt-1.5 space-y-1 text-[11px]">
                    {record.logs.map((log) => (
                      <li key={log.id} className="flex items-baseline justify-between gap-2">
                        <span>
                          {humanise(log.log_type)}
                          {log.top_depth_m !== null &&
                            ` · ${fmtDepth(log.top_depth_m)}–${fmtDepth(log.bottom_depth_m)}`}
                        </span>
                        <span className="shrink-0 text-[10px] text-muted-foreground">
                          {log.has_temperature_curve ? "Temperature curve" : "No curve"}
                          {log.is_public_domain ? " · public" : " · restricted"}
                          {log.storage_uri && (
                            <a
                              href={log.storage_uri}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="ml-1 text-primary hover:underline"
                            >
                              file
                            </a>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>

          {analysis && <AssuranceFooter />}

          <div className="flex justify-end pb-2">
            <Button
              variant="ghost"
              size="xs"
              onClick={() => router.push("/explorer")}
            >
              Back to the explorer
              <ChevronRight className="h-3 w-3" aria-hidden />
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}

function Assessment({
  analysis,
  wellId,
  onResult,
  includeAi,
  onIncludeAiChange,
  runError,
}: {
  analysis: AnalysisResult;
  wellId: string;
  onResult: (result: AnalysisResult) => void;
  includeAi: boolean;
  onIncludeAiChange: (value: boolean) => void;
  runError: string | null;
}) {
  void runError;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-5">
          <FeasibilityHeadline result={analysis} />
        </CardContent>
      </Card>

      <DecisionStrip result={analysis} />

      <Card>
        <CardContent className="p-4">
          <KeyFiguresGrid result={analysis} />
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <Flame className="h-3.5 w-3.5" aria-hidden />
          Configuration:{" "}
          <strong className="text-foreground">
            {CONFIGURATION_LABELS[analysis.configuration] ??
              humanise(analysis.configuration)}
          </strong>
          {analysis.configuration !== analysis.recommended_configuration && (
            <span className="text-priority-medium">
              (engine recommends{" "}
              {CONFIGURATION_LABELS[analysis.recommended_configuration]})
            </span>
          )}
        </span>
        <span className="font-mono text-[10px]">
          pipeline {analysis.pipeline_version}
        </span>
        <label className="ml-auto flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={includeAi}
            onChange={(event) => onIncludeAiChange(event.target.checked)}
            className="h-3.5 w-3.5 rounded border-input"
          />
          Include agent interpretation on re-run
        </label>
      </div>

      <p className="rounded-md border bg-muted/40 p-2.5 text-[11px] leading-relaxed text-muted-foreground">
        {CONFIGURATION_DESCRIPTIONS[analysis.configuration]}
      </p>

      <Tabs defaultValue="score">
        <TabsList>
          <TabsTrigger value="score">Score</TabsTrigger>
          <TabsTrigger value="risk">Risk</TabsTrigger>
          <TabsTrigger value="trace">Trace ({analysis.calculation_trace.length})</TabsTrigger>
          <TabsTrigger value="evidence">
            Evidence ({analysis.evidence.length + analysis.claims.length})
          </TabsTrigger>
          <TabsTrigger value="consent">Consent</TabsTrigger>
          <TabsTrigger value="agents">Agents</TabsTrigger>
          <TabsTrigger value="whatif">What-if</TabsTrigger>
        </TabsList>

        <TabsContent value="score" className="space-y-3">
          <ScoreBreakdown result={analysis} />
          <ConfidencePanel
            detail={analysis.confidence_detail}
            score={analysis.confidence_score}
          />
          <ValidationPanel actions={analysis.validation_actions} />
        </TabsContent>

        <TabsContent value="risk">
          <RiskPanel risk={analysis.risk} />
        </TabsContent>

        <TabsContent value="trace">
          <TracePanel trace={analysis.calculation_trace} />
        </TabsContent>

        <TabsContent value="evidence" className="space-y-3">
          <EvidencePanel evidence={analysis.evidence} claims={analysis.claims} />
        </TabsContent>

        <TabsContent value="consent" className="space-y-3">
          <RegulatoryPanel
            requirements={analysis.regulatory_requirements}
            configuration={analysis.configuration}
          />
        </TabsContent>

        <TabsContent value="agents">
          <AgentPanel
            outputs={analysis.agent_outputs}
            executiveSummary={analysis.executive_summary}
            reportMarkdown={analysis.report_markdown}
          />
        </TabsContent>

        <TabsContent value="whatif" className="space-y-3">
          <Notice tone="info" title="Nothing here is saved">
            Overrides are applied to a fresh engine run and discarded when you
            navigate away. A figure produced by an assumed flow rate must never
            be able to persist as though it came from a measurement.
          </Notice>
          <WhatIfPanel
            wellId={wellId}
            configuration={analysis.configuration}
            baseline={analysis}
            onResult={onResult}
          />
          <ScenarioPanel wellId={wellId} />
        </TabsContent>
      </Tabs>

      {analysis.data_gaps.length > 0 && (
        <Card className="border-priority-medium/40">
          <CardContent className="p-4">
            <SectionTitle>What is missing</SectionTitle>
            <ul className="mt-1.5 space-y-0.5 text-[11px] leading-relaxed text-muted-foreground">
              {analysis.data_gaps.map((gap, index) => (
                <li key={index} className="flex gap-1.5">
                  <span aria-hidden>·</span>
                  <span>{gap}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}