/**
 * The well detail panel shown when a map marker is clicked.
 *
 * Structured to answer, in order: is this well worth pursuing, why, and what
 * next. Every figure carries its provenance label and any gap is shown as a gap
 * rather than omitted - a reader should be able to see what the platform does
 * not know about a well at the same time as what it does.
 */

"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FlaskConical,
  MapPin,
  Ruler,
  Thermometer,
  TriangleAlert,
} from "lucide-react";

import { Badge, EpistemicBadge, EvidenceDisclaimer, MockDataBanner } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/primitives";
import {
  CONFIGURATION_LABELS,
  MEASUREMENT_METHOD_LABELS,
  RECOMMENDATION_META,
  WELL_STATUS_LABELS,
  confidenceBand,
  formatDistance,
  formatEnergy,
  formatGBP,
  formatPower,
  formatTemperature,
  humanise,
} from "@/lib/domain";
import { fmtDepth } from "@/lib/utils";
import type { AnalysisResult, WellDetail } from "@/types/api";

export function WellPanel({
  well,
  analysis,
  onClose,
  onRunAssessment,
  isRunning,
}: {
  well: WellDetail;
  analysis: AnalysisResult | null;
  onClose: () => void;
  onRunAssessment: () => void;
  isRunning: boolean;
}) {
  const [showProvenance, setShowProvenance] = useState(false);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">{well.well_name}</h2>
            <p className="truncate font-mono text-xs text-muted-foreground">
              {well.well_id}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="shrink-0 text-xs"
          >
            Close
          </Button>
        </div>

        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <Badge variant="secondary" className="text-[12px]">
            {WELL_STATUS_LABELS[well.status] ?? humanise(well.status)}
          </Badge>
          {well.original_purpose && (
            <Badge variant="outline" className="text-[12px]">
              {humanise(well.original_purpose)}
            </Badge>
          )}
          {well.region && (
            <Badge variant="outline" className="text-[12px]">
              <MapPin className="mr-0.5 h-2.5 w-2.5" aria-hidden />
              {well.region}
            </Badge>
          )}
          {well.is_mock && (
            <Badge className="mock-badge border-destructive bg-destructive/10 text-destructive">
              synthetic
            </Badge>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        {well.is_mock && (
          <MockDataBanner isMock what="figures for this well" />
        )}

        {/* Score summary when analysed */}
        {analysis ? (
          <ScoreSummary analysis={analysis} />
        ) : (
          <div className="rounded-md border border-dashed p-3 text-center">
            <p className="text-xs text-muted-foreground">
              This well has not been assessed yet. A feasibility score requires
              running the deterministic engineering model, which takes a few
              seconds.
            </p>
          </div>
        )}

        {/* Well characteristics */}
        <section>
          <SectionHeading icon={Ruler} title="Well characteristics" />
          <dl className="space-y-1.5 text-xs">
            <Row label="Operator" value={well.operator ?? "Not recorded"} />
            <Row label="Licence" value={well.licence ?? "Not recorded"} />
            <Row
              label="Drilled"
              value={well.drilling_year ? String(well.drilling_year) : "Not recorded"}
            />
            <Row
              label="Total depth"
              value={
                <span className="flex items-center gap-1.5">
                  {fmtDepth(well.total_depth_m)}
                  {well.tvd_m && (
                    <span className="text-muted-foreground">
                      (TVD {fmtDepth(well.tvd_m)})
                    </span>
                  )}
                </span>
              }
            />
            <Row
              label="Deviation"
              value={
                well.max_deviation_deg !== null
                  ? `${well.max_deviation_deg}°`
                  : well.is_deviated
                    ? "Deviated (angle not recorded)"
                    : "Vertical or not recorded"
              }
            />
            <Row label="Formation" value={well.formation ?? "Not recorded"} />
            <Row
              label="Casing"
              value={
                well.casing_string ? (
                  <span className="text-xs">{well.casing_string}</span>
                ) : (
                  <span className="italic text-muted-foreground">
                    No casing record
                  </span>
                )
              }
            />
          </dl>
        </section>

        {/* Temperature */}
        <section>
          <SectionHeading icon={Thermometer} title="Temperature" />
          {well.temperature_c !== null ? (
            <>
              <div className="flex items-baseline gap-2">
                <span className="tabular text-2xl font-semibold">
                  {formatTemperature(well.temperature_c)}
                </span>
                <EpistemicBadge status={well.temperature_status} expanded />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Recorded at {fmtDepth(well.temperature_depth_m)}. Confidence{" "}
                {well.temperature_confidence.replace("_", " ")}.
              </p>
              {well.temperature_variability_c !== null &&
                well.temperature_variability_c > 8 && (
                  <p className="mt-1.5 rounded border border-priority-low/30 bg-priority-low/10 p-2 text-xs text-priority-low">
                    Sources span {well.temperature_variability_c.toFixed(1)} K on
                    this well, which indicates the temperature is not yet
                    established to the precision the engineering model needs.
                  </p>
                )}

              {well.temperatures.length > 0 && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs font-medium text-primary">
                    {well.temperatures.length} temperature record
                    {well.temperatures.length === 1 ? "" : "s"}
                  </summary>
                  <div className="mt-1.5 space-y-1.5">
                    {well.temperatures.map((t) => (
                      <div
                        key={t.id}
                        className="flex items-center justify-between gap-2 rounded border px-2 py-1.5 text-xs"
                      >
                        <div>
                          <div className="tabular font-medium">
                            {t.temperature_c.toFixed(1)} °C at {fmtDepth(t.depth_m)}
                          </div>
                          <div className="text-muted-foreground">
                            {MEASUREMENT_METHOD_LABELS[t.measurement_method] ??
                              humanise(t.measurement_method)}
                            {t.is_final_stabilised
                              ? ""
                              : " · not thermally stabilised"}
                          </div>
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <EpistemicBadge status={t.status} />
                          {!t.is_final_stabilised && (
                            <span className="text-[11px] text-destructive">
                              overstates
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </>
          ) : (
            <div className="rounded border border-epistemic-unknown/40 bg-epistemic-unknown/5 p-2.5">
              <div className="flex items-center gap-2">
                <TriangleAlert className="h-3.5 w-3.5 text-epistemic-unknown" />
                <span className="text-xs font-medium">No temperature measurement</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Thermal potential is <strong>unknown</strong>, not zero. Every
                downstream figure depends on this, so it gates the whole
                assessment.
              </p>
            </div>
          )}
        </section>

        {/* Integrity */}
        <section>
          <SectionHeading icon={Ruler} title="Well integrity" />
          {well.integrity ? (
            <div className="space-y-1.5 text-xs">
              <Row
                label="Status"
                value={
                  <span className="flex items-center gap-1.5">
                    {humanise(well.integrity.status)}
                    <EpistemicBadge status={well.integrity.status_status} />
                  </span>
                }
              />
              {well.integrity.requires_reequipment && (
                <Row label="Reequipment" value="Required" />
              )}
              {well.integrity.corrosion_evidence && (
                <Row label="Corrosion" value={well.integrity.corrosion_evidence} />
              )}
              {well.integrity.last_integrity_check_date && (
                <Row
                  label="Last checked"
                  value={well.integrity.last_integrity_check_date}
                />
              )}
            </div>
          ) : (
            <div className="rounded border border-priority-medium/40 bg-priority-medium/5 p-2.5 text-xs">
              <p>
                <strong>Not assessed.</strong> Integrity carries a 20% score
                weight, second only to thermal, and cannot be established from
                desk study.
              </p>
            </div>
          )}
        </section>

        {/* Engineering and economics */}
        {analysis && (
          <>
            <Separator />
            <section>
              <SectionHeading icon={FlaskConical} title="Geothermal configuration" />
              <p className="text-xs">
                {CONFIGURATION_LABELS[analysis.configuration] ??
                  humanise(analysis.configuration)}
              </p>
            </section>

            <section>
              <SectionHeading icon={Thermometer} title="Thermal output" />
              <div className="space-y-1.5 text-xs">
                <Row
                  label="Wellhead output"
                  value={
                    <span className="flex items-center gap-1.5">
                      {formatPower(analysis.thermal_output_kw)}
                      <EpistemicBadge
                        status={analysis.thermal_output_status}
                        expanded
                      />
                    </span>
                  }
                />
                {analysis.thermal_output_low_kw !== null && (
                  <Row
                    label="Uncertainty band"
                    value={`${formatPower(analysis.thermal_output_low_kw)} to ${formatPower(
                      analysis.thermal_output_high_kw,
                    )}`}
                  />
                )}
                {analysis.heat_pump_cop && (
                  <Row
                    label="Heat pump COP"
                    value={`${analysis.heat_pump_cop.toFixed(1)} (estimate)`}
                  />
                )}
                <Row label="Annual heat" value={formatEnergy(analysis.annual_heat_kwh)} />
                {analysis.network_loss_fraction !== null && (
                  <Row
                    label="Distribution loss"
                    value={`${(analysis.network_loss_fraction * 100).toFixed(1)}% over ${fmtDepth(
                      analysis.network_length_m,
                    )}`}
                  />
                )}
              </div>
              {analysis.thermal_output_status !== "MEASURED" && (
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Output scales linearly with flow rate, and no flow test has
                  been performed on this well. The figure is an estimate.
                </p>
              )}
            </section>

            <section>
              <SectionHeading icon={Ruler} title="Heat demand & network" />
              <div className="space-y-1.5 text-xs">
                <Row
                  label="Nearest demand"
                  value={formatDistance(analysis.nearest_building_distance_m)}
                />
                <Row
                  label="Annual heat delivered"
                  value={formatEnergy(analysis.annual_heat_kwh)}
                />
                <Row label="Capital cost" value={formatGBP(analysis.capex_gbp)} />
                <Row
                  label="LCOH"
                  value={
                    analysis.lcoh_p_per_kwh !== null
                      ? `${analysis.lcoh_p_per_kwh.toFixed(1)} p/kWh`
                      : "Not available"
                  }
                />
                <Row
                  label="NPV"
                  value={formatGBP(analysis.npv_gbp)}
                />
                <Row
                  label="IRR"
                  value={
                    analysis.irr_pct !== null
                      ? `${analysis.irr_pct.toFixed(1)}%`
                      : "No valid IRR"
                  }
                />
              </div>
            </section>

            {analysis.data_gaps.length > 0 && (
              <section>
                <SectionHeading icon={TriangleAlert} title="Data gaps" />
                <ul className="space-y-1 text-xs">
                  {analysis.data_gaps.map((gap, index) => (
                    <li key={index} className="flex gap-1.5">
                      <span aria-hidden>·</span>
                      <span>{gap}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}

        {/* Provenance */}
        <section>
          <button
            type="button"
            onClick={() => setShowProvenance((v) => !v)}
            className="flex w-full items-center justify-between rounded px-1 py-1 text-xs font-medium text-primary hover:bg-muted"
          >
            Data provenance
            {showProvenance ? (
              <ChevronUp className="h-3 w-3" aria-hidden />
            ) : (
              <ChevronDown className="h-3 w-3" aria-hidden />
            )}
          </button>
          {showProvenance && (
            <dl className="mt-1.5 space-y-1 text-xs">
              <Row label="Source adapter" value={<code>{well.source}</code>} />
              <Row label="Dataset version" value={well.dataset_version ?? "Not recorded"} />
              {well.source_url && (
                <Row
                  label="Source URL"
                  value={
                    <a
                      href={well.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                      Open source <ExternalLink className="h-2.5 w-2.5" aria-hidden />
                    </a>
                  }
                />
              )}
              <Row
                label="Data completeness"
                value={
                  well.data_completeness !== null
                    ? `${Math.round(well.data_completeness * 100)}%`
                    : "Not assessed"
                }
              />
              {well.analysed_at && (
                <Row
                  label="Last assessed"
                  value={new Date(well.analysed_at).toLocaleString("en-GB")}
                />
              )}
            </dl>
          )}
        </section>

        <EvidenceDisclaimer />
      </div>

      {/* Actions */}
      <div className="flex gap-2 border-t p-3">
        <Button
          onClick={onRunAssessment}
          disabled={isRunning}
          className="flex-1"
          size="sm"
        >
          {isRunning
            ? "Assessing…"
            : analysis
              ? "Re-run assessment"
              : "Run feasibility assessment"}
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link href={`/wells/${well.id}`}>
            Full record
            <ArrowRight className="ml-1.5 h-3 w-3" aria-hidden />
          </Link>
        </Button>
      </div>
    </div>
  );
}

function ScoreSummary({ analysis }: { analysis: AnalysisResult }) {
  const meta = RECOMMENDATION_META[analysis.recommendation];
  const band = confidenceBand(analysis.confidence_score);

  return (
    <div className="space-y-2.5 rounded-md border p-3">
      <div className="flex items-baseline justify-between">
        <div>
          <div className="text-[12px] font-semibold text-muted-foreground">
            Feasibility
          </div>
          <div className="tabular text-2xl font-semibold">
            {Math.round(analysis.feasibility_score)}
            <span className="text-sm font-normal text-muted-foreground">/100</span>
          </div>
        </div>
        <Badge className={meta.className}>{analysis.recommendation}</Badge>
      </div>

      <div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Evidence confidence</span>
          <span className="tabular font-medium">
            {Math.round(analysis.confidence_score * 100)}% ({band})
          </span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary"
            style={{ width: `${analysis.confidence_score * 100}%` }}
          />
        </div>
      </div>

      <div className="rounded border border-primary/30 bg-primary/5 p-2">
        <div className="text-[12px] font-semibold text-primary">
          Next action
        </div>
        <p className="mt-0.5 text-xs leading-relaxed">{analysis.next_action}</p>
      </div>
    </div>
  );
}

function SectionHeading({
  icon: Icon,
  title,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
}) {
  return (
    <div className="mb-1.5 flex items-center gap-1.5 border-b pb-1">
      <Icon className="h-3 w-3 text-muted-foreground" aria-hidden />
      <h3 className="text-[12px] font-semibold text-muted-foreground">
        {title}
      </h3>
    </div>
  );
}

function Row({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  const isMissing = typeof value === "string" && value.includes("Not ");
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd
        className={`min-w-0 text-right ${isMissing ? "italic text-muted-foreground" : ""}`}
      >
        {value}
      </dd>
    </div>
  );
}
