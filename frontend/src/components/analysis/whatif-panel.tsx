/**
 * What-if and scenario panels.
 *
 * Two things these panels deliberately do not do:
 *
 * 1. They never persist. A what-if recalculation is discarded on reload, so a
 *    figure produced by an assumed flow rate cannot later be mistaken for one
 *    derived from measured data.
 * 2. They never let the user set the score. Inputs change; the engine
 *    recomputes. There is no control anywhere in this interface labelled
 *    "score".
 */

"use client";

import * as React from "react";
import { Calculator, Play, RefreshCw } from "lucide-react";

import { Badge, EpistemicBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SectionTitle } from "@/components/common/feedback";
import { ScenarioCostChart } from "@/components/charts/charts";
import { api } from "@/lib/api";
import { CONFIGURATION_LABELS, humanise } from "@/lib/domain";
import { cn } from "@/lib/utils";
import type {
  AnalysisResult,
  EngineeringInputs,
  GeothermalConfiguration,
  ScenarioComparison,
  ScenarioDefinition,
} from "@/types/api";

interface SliderSpec {
  key: keyof EngineeringInputs;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  help: string;
  decimals?: number;
}

const SLIDERS: SliderSpec[] = [
  {
    key: "flow_rate_lps",
    label: "Flow rate",
    unit: "L/s",
    min: 5,
    max: 80,
    step: 1,
    decimals: 0,
    help: "The single largest driver of thermal output. Assumed, not measured, until a flow test exists.",
  },
  {
    key: "source_temperature_c",
    label: "Source temperature",
    unit: "°C",
    min: 30,
    max: 160,
    step: 1,
    decimals: 0,
    help: "Overrides the well's own temperature record. Only do this to test a range, not to replace the record.",
  },
  {
    key: "heat_pump_cop",
    label: "Heat pump COP",
    unit: "",
    min: 1.5,
    max: 6,
    step: 0.1,
    decimals: 1,
    help: "Coefficient of performance. The engine will reject a COP that is impossible for the temperature lift.",
  },
  {
    key: "heat_price_p_per_kwh",
    label: "Heat price",
    unit: "p/kWh",
    min: 1,
    max: 30,
    step: 0.5,
    decimals: 1,
    help: "Delivered heat price. This is an assumption about a market, not an observation.",
  },
  {
    key: "electricity_price_p_per_kwh",
    label: "Electricity price",
    unit: "p/kWh",
    min: 5,
    max: 60,
    step: 0.5,
    decimals: 1,
    help: "Parasitic load and pumping cost driver.",
  },
  {
    key: "discount_rate",
    label: "Discount rate",
    unit: "",
    min: 0.01,
    max: 0.2,
    step: 0.005,
    decimals: 3,
    help: "Real discount rate applied to the cash flow.",
  },
  {
    key: "project_lifetime_years",
    label: "Project lifetime",
    unit: "years",
    min: 5,
    max: 40,
    step: 1,
    decimals: 0,
    help: "Horizon over which the NPV and IRR are evaluated.",
  },
  {
    key: "target_supply_temperature_c",
    label: "Network supply temperature",
    unit: "°C",
    min: 40,
    max: 95,
    step: 1,
    decimals: 0,
    help: "Flow temperature the network must deliver. Sets the required lift and, with it, the achievable temperature swing.",
  },
  {
    key: "utilisation_factor",
    label: "Utilisation factor",
    unit: "",
    min: 0.2,
    max: 1,
    step: 0.05,
    decimals: 2,
    help: "Fraction of installed capacity actually used. Heat demand is seasonal, so this is rarely 1.",
  },
  {
    key: "network_length_m",
    label: "Network length",
    unit: "m",
    min: 0,
    max: 15_000,
    step: 100,
    decimals: 0,
    help: "Distribution pipe run. Loss scales roughly with length, so this compounds with distance.",
  },
];

export function WhatIfPanel({
  wellId,
  configuration,
  baseline,
  onResult,
}: {
  wellId: string;
  configuration: GeothermalConfiguration;
  baseline: AnalysisResult | null;
  onResult: (result: AnalysisResult) => void;
}) {
  const [values, setValues] = React.useState<Record<string, number>>({});
  const [config, setConfig] =
    React.useState<GeothermalConfiguration>(configuration);
  const [result, setResult] = React.useState<AnalysisResult | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    setValues({});
    setResult(null);
  }, [wellId, configuration]);

  const overrides = React.useMemo<EngineeringInputs>(() => {
    const inputs: EngineeringInputs = {};
    for (const spec of SLIDERS) {
      const value = values[spec.key as string];
      if (typeof value === "number") {
        (inputs as Record<string, number>)[spec.key as string] = value;
      }
    }
    return inputs;
  }, [values]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const computed = await api.whatIf(wellId, overrides, config);
      setResult(computed);
      onResult(computed);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "The recalculation failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const changed = Object.keys(values).length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Calculator className="h-4 w-4" aria-hidden />
          What-if recalculation
        </CardTitle>
        <CardDescription>
          Change an input and re-run the deterministic engine. Nothing here is
          saved, and every override is marked as an assumption in the trace.
          Disabling an override falls back to the well&apos;s own recorded value.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-56">
            <div className="mb-1 text-[12px] font-semibold text-muted-foreground">
              Configuration
            </div>
            <Select
              value={config}
              onValueChange={(value) => setConfig(value as GeothermalConfiguration)}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(CONFIGURATION_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value} className="text-xs">
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Button size="sm" onClick={() => void run()} disabled={busy} loading={busy}>
            <Play className="h-3.5 w-3.5" aria-hidden />
            Recalculate
          </Button>

          {changed > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setValues({});
                setResult(null);
                onResult(baseline!);
              }}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              Reset {changed} override{changed === 1 ? "" : "s"}
            </Button>
          )}
        </div>

        <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {SLIDERS.map((spec) => {
            const current = values[spec.key as string];
            const overriding = typeof current === "number";
            return (
              <div key={spec.key as string}>
                <div className="flex items-baseline justify-between text-xs">
                  <label className="font-medium">{spec.label}</label>
                  <span className="tabular">
                    {overriding ? (
                      <span className="font-semibold text-primary">
                        {current.toFixed(spec.decimals ?? 2)} {spec.unit}
                      </span>
                    ) : (
                      <span className="text-[12px] text-muted-foreground">
                        engine default
                      </span>
                    )}
                  </span>
                </div>
                <Slider
                  value={[overriding ? current : defaultFor(spec)]}
                  min={spec.min}
                  max={spec.max}
                  step={spec.step}
                  onValueChange={([next]) =>
                    setValues((current_) => {
                      const fallback = defaultFor(spec);
                      const key = spec.key as string;
                      if (next === undefined || next === fallback) {
                        const copy: Record<string, number> = { ...current_ };
                        delete copy[key];
                        return copy;
                      }
                      return { ...current_, [key]: next };
                    })
                  }
                  className="mt-1.5"
                  aria-label={spec.label}
                />
                <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">
                  {spec.help}
                </p>
              </div>
            );
          })}
        </div>

        {error && (
          <p
            role="alert"
            className="rounded border border-destructive/40 bg-destructive/10 px-2.5 py-2 text-xs text-destructive"
          >
            {error}
          </p>
        )}

        {result && baseline && <Comparison baseline={baseline} candidate={result} />}
      </CardContent>
    </Card>
  );
}

function defaultFor(spec: SliderSpec): number {
  // A representative mid-range value. Moving the slider to this value clears
  // the override, so the user can always get back to the engine's own choice.
  return Number(((spec.min + spec.max) / 2).toFixed(3));
}

function Comparison({
  baseline,
  candidate,
}: {
  baseline: AnalysisResult;
  candidate: AnalysisResult;
}) {
  const rows = [
    {
      label: "Feasibility score",
      base: baseline.feasibility_score,
      next: candidate.feasibility_score,
      format: (value: number) => Math.round(value).toString(),
      unit: "/100",
    },
    {
      label: "Thermal output",
      base: baseline.thermal_output_kw,
      next: candidate.thermal_output_kw,
      format: (value: number) => value.toFixed(0),
      unit: "kWth",
      status: candidate.thermal_output_status,
    },
    {
      label: "Delivered heat",
      base: baseline.delivered_heat_kw,
      next: candidate.delivered_heat_kw,
      format: (value: number) => value.toFixed(0),
      unit: "kWth",
    },
    {
      label: "CAPEX",
      base: baseline.capex_gbp,
      next: candidate.capex_gbp,
      format: (value: number) => `£${Math.round(value / 1000)}k`,
      unit: "",
      status: "ESTIMATE" as const,
    },
    {
      label: "LCOH",
      base: baseline.lcoh_p_per_kwh,
      next: candidate.lcoh_p_per_kwh,
      format: (value: number) => value.toFixed(1),
      unit: "p/kWh",
      status: "DERIVED" as const,
    },
    {
      label: "NPV",
      base: baseline.npv_gbp,
      next: candidate.npv_gbp,
      format: (value: number) =>
        `£${(Math.abs(value) / 1_000_000).toFixed(2)}m`,
      unit: "",
      status: "DERIVED" as const,
    },
    {
      label: "IRR",
      base: baseline.irr_pct,
      next: candidate.irr_pct,
      format: (value: number) => value.toFixed(1),
      unit: "%",
      status: "DERIVED" as const,
    },
    {
      label: "Payback",
      base: baseline.payback_years,
      next: candidate.payback_years,
      format: (value: number) => value.toFixed(1),
      unit: "years",
      status: "DERIVED" as const,
    },
  ];

  return (
    <div className="rounded-md border bg-muted/40 p-3">
      <SectionTitle>Baseline against your assumptions</SectionTitle>
      <table className="mt-2 w-full text-xs">
        <thead>
          <tr className="text-left text-[12px] text-muted-foreground">
            <th className="pb-1 font-semibold">Figure</th>
            <th className="pb-1 text-right font-semibold">Baseline</th>
            <th className="pb-1 text-right font-semibold">With overrides</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const changed =
              row.base !== null && row.next !== null && row.base !== row.next;
            return (
              <tr key={row.label} className="border-t">
                <td className="py-1.5">
                  <span className="flex items-center gap-1.5">
                    {row.label}
                    {row.status && <EpistemicBadge status={row.status} />}
                  </span>
                </td>
                <td className="py-1.5 text-right tabular text-muted-foreground">
                  {row.base === null || row.base === undefined
                    ? "Not available"
                    : `${row.format(row.base)} ${row.unit}`}
                </td>
                <td
                  className={cn(
                    "py-1.5 text-right tabular font-medium",
                    changed && "text-primary",
                  )}
                >
                  {row.next === null || row.next === undefined
                    ? "Not available"
                    : `${row.format(row.next)} ${row.unit}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {candidate.recommendation !== baseline.recommendation && (
        <p className="mt-2 rounded border border-primary/30 bg-primary/5 p-2 text-xs">
          The recommendation moves from{" "}
          <strong>{baseline.recommendation}</strong> to{" "}
          <strong>{candidate.recommendation}</strong> under these assumptions.
          That is the engine recomputing, not an agent revising its opinion.
        </p>
      )}

      <p className="mt-2 text-[12px] leading-relaxed text-muted-foreground">
        The baseline column is the engine&apos;s own result for this well with no
        overrides. Every figure in the third column inherits the status of its
        most uncertain input; overriding a flow rate does not make the output a
        measurement.
      </p>
    </div>
  );
}

const DEFAULT_SCENARIOS: ScenarioDefinition[] = [
  {
    name: "conservative",
    label: "Conservative",
    description:
      "Low flow, high network loss, weak heat price. The case a sceptic would put.",
    probability_weight: 0.25,
    inputs: {
      flow_rate_lps: 12,
      utilisation_factor: 0.5,
      heat_price_p_per_kwh: 12,
      electricity_price_p_per_kwh: 22,
      discount_rate: 0.1,
    },
  },
  {
    name: "central",
    label: "Central",
    description: "The engine's documented defaults, with a plausible duty cycle.",
    probability_weight: 0.5,
    inputs: {
      flow_rate_lps: 25,
      utilisation_factor: 0.7,
      heat_price_p_per_kwh: 18,
      electricity_price_p_per_kwh: 15,
      discount_rate: 0.07,
    },
  },
  {
    name: "optimistic",
    label: "Optimistic",
    description:
      "Good flow test, short network, firm offtake at a good price. Assumes everything works.",
    probability_weight: 0.25,
    inputs: {
      flow_rate_lps: 40,
      utilisation_factor: 0.85,
      heat_price_p_per_kwh: 24,
      electricity_price_p_per_kwh: 11,
      discount_rate: 0.05,
    },
  },
];

export function ScenarioPanel({ wellId }: { wellId: string }) {
  const [scenarios, setScenarios] = React.useState<ScenarioDefinition[]>(
    DEFAULT_SCENARIOS,
  );
  const [comparison, setComparison] = React.useState<ScenarioComparison | null>(
    null,
  );
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    setComparison(null);
  }, [wellId]);

  const update = (
    index: number,
    key: keyof EngineeringInputs,
    value: number,
  ) => {
    setScenarios((current) =>
      current.map((scenario, position) =>
        position === index
          ? { ...scenario, inputs: { ...scenario.inputs, [key]: value } }
          : scenario,
      ),
    );
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setComparison(await api.runScenarios(wellId, scenarios));
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "The scenario run failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const weightSum = scenarios.reduce(
    (sum, scenario) => sum + (scenario.probability_weight ?? 0),
    0,
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Scenario comparison</CardTitle>
        <CardDescription>
          Run several input sets through the same deterministic engine. The
          probability weights are yours, and they are an assumption - they are
          not derived from the data and they are not a probability model.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {Math.abs(weightSum - 1) > 0.001 && (
          <p className="rounded border border-priority-medium/40 bg-priority-medium/5 px-2.5 py-1.5 text-xs text-priority-medium">
            Probability weights sum to {weightSum.toFixed(2)}, not 1. The
            expected values below are still reported, but a weighted average over
            weights that do not sum to one is not an expectation.
          </p>
        )}

        <div className="space-y-3">
          {scenarios.map((scenario, index) => (
            <div key={scenario.name} className="rounded-md border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <p className="text-xs font-medium">
                    {scenario.label ?? humanise(scenario.name)}
                  </p>
                  <p className="text-[12px] leading-relaxed text-muted-foreground">
                    {scenario.description}
                  </p>
                </div>
                <Badge variant="outline" className="text-[11px]">
                  weight {((scenario.probability_weight ?? 0) * 100).toFixed(0)}%
                </Badge>
              </div>

              <div className="mt-2 grid gap-x-5 gap-y-2 sm:grid-cols-2">
                {(
                  [
                    ["flow_rate_lps", "Flow rate", "L/s", 5, 80, 1],
                    ["heat_price_p_per_kwh", "Heat price", "p/kWh", 1, 30, 0.5],
                    ["utilisation_factor", "Utilisation", "", 0.2, 1, 0.05],
                    ["discount_rate", "Discount rate", "", 0.01, 0.2, 0.005],
                  ] as const
                ).map(([key, label, unit, min, max, step]) => {
                  const value =
                    (scenario.inputs[key] as number | undefined) ??
                    (min + max) / 2;
                  return (
                    <div key={key}>
                      <div className="flex items-baseline justify-between text-xs">
                        <span>{label}</span>
                        <span className="tabular">
                          {value.toFixed(step < 1 ? 3 : 0)} {unit}
                        </span>
                      </div>
                      <Slider
                        value={[value]}
                        min={min}
                        max={max}
                        step={step}
                        onValueChange={([next]) => {
                          if (next !== undefined) update(index, key, next);
                        }}
                        className="mt-1"
                        aria-label={`${scenario.label} ${label}`}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <Button size="sm" onClick={() => void run()} disabled={busy} loading={busy}>
          Run all scenarios
        </Button>

        {error && (
          <p
            role="alert"
            className="rounded border border-destructive/40 bg-destructive/10 px-2.5 py-2 text-xs text-destructive"
          >
            {error}
          </p>
        )}

        {comparison && (
          <div className="space-y-3 rounded-md border bg-muted/40 p-3">
            <div className="flex flex-wrap gap-4 text-xs">
              <span>
                <span className="text-muted-foreground">Expected LCOH </span>
                <span className="tabular font-medium">
                  {comparison.expected_lcoh_p_per_kwh !== null
                    ? `${comparison.expected_lcoh_p_per_kwh.toFixed(1)} p/kWh`
                    : "Not available"}
                </span>
              </span>
              <span>
                <span className="text-muted-foreground">Expected NPV </span>
                <span className="tabular font-medium">
                  {comparison.expected_npv_gbp !== null
                    ? `£${(Math.abs(comparison.expected_npv_gbp) / 1_000_000).toFixed(2)}m`
                    : "Not available"}
                </span>
              </span>
              <span>
                <span className="text-muted-foreground">LCOH spread </span>
                <span className="tabular font-medium">
                  {comparison.spread_lcoh_p_per_kwh !== null
                    ? `${comparison.spread_lcoh_p_per_kwh.toFixed(1)} p/kWh`
                    : "Not available"}
                </span>
              </span>
            </div>

            <ScenarioCostChart
              data={comparison.scenarios.map((scenario) => ({
                name: scenario.label ?? humanise(scenario.name),
                lcoh: scenario.lcoh_p_per_kwh,
              }))}
              height={160}
            />

            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[12px] text-muted-foreground">
                  <th className="pb-1 font-semibold">Scenario</th>
                  <th className="pb-1 text-right font-semibold">Output</th>
                  <th className="pb-1 text-right font-semibold">CAPEX</th>
                  <th className="pb-1 text-right font-semibold">LCOH</th>
                  <th className="pb-1 text-right font-semibold">NPV</th>
                  <th className="pb-1 text-right font-semibold">Score</th>
                  <th className="pb-1 text-right font-semibold">Recommendation</th>
                </tr>
              </thead>
              <tbody>
                {comparison.scenarios.map((scenario) => (
                  <tr key={scenario.name} className="border-t">
                    <td className="py-1.5">
                      {scenario.label ?? humanise(scenario.name)}
                    </td>
                    <td className="py-1.5 text-right tabular">
                      {scenario.thermal_output_kw !== null
                        ? `${scenario.thermal_output_kw.toFixed(0)} kW`
                        : "—"}
                    </td>
                    <td className="py-1.5 text-right tabular">
                      {scenario.capex_gbp !== null
                        ? `£${Math.round(scenario.capex_gbp / 1000)}k`
                        : "—"}
                    </td>
                    <td className="py-1.5 text-right tabular">
                      {scenario.lcoh_p_per_kwh !== null
                        ? `${scenario.lcoh_p_per_kwh.toFixed(1)}p`
                        : "—"}
                    </td>
                    <td className="py-1.5 text-right tabular">
                      {scenario.npv_gbp !== null
                        ? `£${(Math.abs(scenario.npv_gbp) / 1_000_000).toFixed(2)}m`
                        : "—"}
                    </td>
                    <td className="py-1.5 text-right tabular">
                      {scenario.feasibility_score !== null
                        ? Math.round(scenario.feasibility_score)
                        : "—"}
                    </td>
                    <td className="py-1.5 text-right">
                      {scenario.recommendation ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {comparison.notes.length > 0 && (
              <ul className="space-y-0.5 text-[12px] leading-relaxed text-muted-foreground">
                {comparison.notes.map((note, index) => (
                  <li key={index}>· {note}</li>
                ))}
              </ul>
            )}

            <p className="text-[12px] leading-relaxed text-muted-foreground">
              A wide spread is the most useful number here. It says how much of
              this assessment rests on inputs nobody has measured yet.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}