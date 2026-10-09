/**
 * Domain presentation helpers.
 *
 * The single most important function here is `epistonicLabel`. Every figure the
 * platform shows carries a provenance status, and this module is the only place
 * that decides how it reads. Keeping it in one module means a status can never
 * be rendered as "Measured" in one view and "Estimated" in another - which is
 * exactly the failure the evidence discipline exists to prevent.
 */

import type {
  ConfidenceBand,
  EpistemicStatus,
  Recommendation,
  RiskCategory,
} from "@/types/api";

/** Presentation metadata for each of the six (seven) epistemic labels. */
export const EPISTEMIC_META: Record<
  EpistemicStatus,
  {
    label: string;
    short: string;
    /** Tailwind classes. Colour is reinforcement; the label does the work. */
    className: string;
    description: string;
    /** Whether a figure with this status may be shown in a headline total. */
    aggregateSafe: boolean;
  }
> = {
  FACT: {
    label: "Fact",
    short: "FACT",
    className: "bg-epistemic-fact/10 text-epistemic-fact border-epistemic-fact/30",
    description:
      "Stated directly in a cited source document, such as an operator licence or a regulator record.",
    aggregateSafe: true,
  },
  MEASURED: {
    label: "Measured",
    short: "MEAS",
    className:
      "bg-epistemic-measured/10 text-epistemic-measured border-epistemic-measured/30",
    description:
      "An instrument reading recorded in a well log, temperature survey or pressure measurement.",
    aggregateSafe: true,
  },
  DERIVED: {
    label: "Derived",
    short: "DERIV",
    className: "bg-epistemic-derived/10 text-epistemic-derived border-epistemic-derived/30",
    description:
      "Computed from measured or documented values by a transparent formula. The calculation is reproducible.",
    aggregateSafe: true,
  },
  MODELLED: {
    label: "Modelled",
    short: "MODEL",
    className: "bg-epistemic-modelled/10 text-epistemic-modelled border-epistemic-modelled/30",
    description:
      "Output of a published simulation or correlation model rather than a direct reading.",
    aggregateSafe: true,
  },
  ESTIMATE: {
    label: "Estimate",
    short: "EST",
    className: "bg-epistemic-estimate/10 text-epistemic-estimate border-epistemic-estimate/30",
    description:
      "A third-party or analyst estimate. The method is documented but the value was not observed.",
    aggregateSafe: false,
  },
  ASSUMPTION: {
    label: "Assumption",
    short: "ASSUM",
    className:
      "bg-epistemic-assumption/10 text-epistemic-assumption border-epistemic-assumption/30",
    description:
      "A choice made without observation: a default parameter, a scenario input, or an analyst judgement.",
    aggregateSafe: false,
  },
  UNKNOWN: {
    label: "Unknown",
    short: "UNK",
    className: "bg-epistemic-unknown/10 text-epistemic-unknown border-epistemic-unknown/30",
    description:
      "No defensible value is available. Never silently replaced with a zero or a regional average.",
    aggregateSafe: false,
  },
};

export const EPISTEMIC_ORDER: EpistemicStatus[] = [
  "FACT",
  "MEASURED",
  "DERIVED",
  "MODELLED",
  "ESTIMATE",
  "ASSUMPTION",
  "UNKNOWN",
];

export const RECOMMENDATION_META: Record<
  Recommendation,
  { className: string; tone: string; priority: 0 | 1 | 2 | 3 }
> = {
  "HIGH PRIORITY": {
    className: "bg-priority-high/10 text-priority-high border-priority-high/30",
    tone: "Justify detailed due diligence and a site visit.",
    priority: 0,
  },
  "MEDIUM PRIORITY": {
    className: "bg-priority-medium/10 text-priority-medium border-priority-medium/30",
    tone: "Worth targeted desktop work before committing to fieldwork.",
    priority: 1,
  },
  "LOW PRIORITY": {
    className: "bg-priority-low/10 text-priority-low border-priority-low/30",
    tone: "Retain on a watch list and revisit if the data improves.",
    priority: 2,
  },
  "DO NOT PURSUE": {
    className: "bg-priority-none/10 text-priority-none border-priority-none/30",
    tone: "Budget is better spent elsewhere.",
    priority: 3,
  },
};

export const CONFIDENCE_META: Record<
  ConfidenceBand,
  { label: string; className: string; description: string }
> = {
  high: {
    label: "High confidence",
    className: "text-priority-high",
    description:
      "Measured by a direct instrument reading, corroborated across sources, and recent.",
  },
  medium: {
    label: "Medium confidence",
    className: "text-priority-medium",
    description:
      "A real measurement, but with gaps in corroboration, recency or method quality.",
  },
  low: {
    label: "Low confidence",
    className: "text-priority-low",
    description:
      "The value rests on an estimate, an indirect method, or data that has aged.",
  },
  very_low: {
    label: "Very low confidence",
    className: "text-destructive",
    description:
      "Sources disagree, the measurement is an analogue, or key fields are missing.",
  },
  unknown: {
    label: "Not established",
    className: "text-muted-foreground",
    description: "No defensible evidence base exists for this well.",
  },
};

export const RISK_LABELS: Record<RiskCategory, string> = {
  well_integrity: "Well integrity",
  temperature_uncertainty: "Temperature uncertainty",
  thermal_decline: "Thermal decline",
  corrosion: "Corrosion",
  scaling: "Scaling",
  groundwater: "Groundwater",
  network_distance: "Network distance",
  heat_demand_uncertainty: "Heat demand uncertainty",
  capex: "CAPEX",
  electricity_price: "Electricity price",
  heat_price: "Heat price",
  regulation: "Regulation",
  planning: "Planning",
  land_access: "Land access",
  customer_connection: "Customer connection",
  construction: "Construction",
  operations: "Operations",
};

export const WELL_STATUS_LABELS: Record<string, string> = {
  producing: "Producing",
  non_producing: "Non-producing",
  suspended: "Suspended",
  plugged_abandoned: "Plugged & abandoned",
  abandoned: "Abandoned",
  drilling: "Drilling",
  completed: "Completed",
  exploration: "Exploration",
  unknown: "Unknown status",
};

export const CONFIGURATION_LABELS: Record<string, string> = {
  closed_loop: "Closed loop",
  open_loop: "Open loop",
  closed_loop_plus_heat_pump: "Closed loop + heat pump",
  open_loop_plus_heat_pump: "Open loop + heat pump",
};

export const CONFIGURATION_DESCRIPTIONS: Record<string, string> = {
  closed_loop:
    "Doublet within the existing borehole. No water is extracted, so no abstraction or discharge consent is needed. Limited by annular capacity and thermal recovery over repeated cycles.",
  open_loop:
    "Water is abstracted and reinjected after heat recovery. Lower pumping demand, but requires an abstraction licence and a reinjection well.",
  closed_loop_plus_heat_pump:
    "Closed loop with a heat pump lifting the extracted heat to network flow temperature. Usually the lowest regulatory burden for a repurposed well.",
  open_loop_plus_heat_pump:
    "Open loop plus a heat pump. Applicable when the water is too cool or the temperature swing too small for useful direct heat.",
};

/**
 * Format a figure with its unit, or state that it is unknown.
 *
 * Returning "Not available" rather than a dash or a zero is deliberate: a
 * reader scanning a table must be able to tell "we do not know" from "it is
 * zero", and those two lead to opposite decisions.
 */
export function formatWithUnit(
  value: number | null | undefined,
  unit: string,
  decimals = 0,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "Not available";
  }
  return `${value.toLocaleString("en-GB", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })} ${unit}`;
}

/** Format a currency figure, or state that it is unavailable. */
export function formatGBP(
  value: number | null | undefined,
  decimals = 0,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "Not available";
  }
  if (Math.abs(value) >= 1_000_000) {
    return `£${(value / 1_000_000).toFixed(decimals > 0 ? decimals : 1)}m`;
  }
  if (Math.abs(value) >= 1_000) {
    return `£${(value / 1_000).toFixed(0)}k`;
  }
  return `£${value.toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
}

export function formatDistance(metres: number | null | undefined): string {
  if (metres === null || metres === undefined || Number.isNaN(metres)) {
    return "Not available";
  }
  if (metres < 1000) return `${Math.round(metres)} m`;
  return `${(metres / 1000).toFixed(2)} km`;
}

export function formatTemperature(celsius: number | null | undefined): string {
  if (celsius === null || celsius === undefined || Number.isNaN(celsius)) {
    return "Not available";
  }
  return `${celsius.toFixed(1)} °C`;
}

export function formatPower(kw: number | null | undefined): string {
  if (kw === null || kw === undefined || Number.isNaN(kw)) return "Not available";
  if (Math.abs(kw) >= 1000) return `${(kw / 1000).toFixed(2)} MW`;
  return `${Math.round(kw)} kW`;
}

export function formatEnergy(kwh: number | null | undefined): string {
  if (kwh === null || kwh === undefined || Number.isNaN(kwh)) return "Not available";
  if (Math.abs(kwh) >= 1_000_000) return `${(kwh / 1_000_000).toFixed(2)} GWh`;
  if (Math.abs(kwh) >= 1000) return `${(kwh / 1000).toFixed(1)} MWh`;
  return `${Math.round(kwh)} kWh`;
}

/**
 * Colour for a feasibility score on a 0-100 scale.
 *
 * Returns a CSS custom property reference rather than a hex value, so the ramp
 * follows the theme. The bands are deliberately coarse: distinguishing six
 * shades of teal on a national map is not possible, and pretending otherwise
 * would imply a precision the score does not have.
 */
export function scoreBand(score: number | null | undefined): {
  label: string;
  className: string;
  band: 0 | 20 | 40 | 60 | 80 | 100 | null;
} {
  if (score === null || score === undefined || Number.isNaN(score)) {
    return {
      label: "Not assessed",
      className: "bg-muted text-muted-foreground",
      band: null,
    };
  }
  if (score >= 80) {
    return { label: "80-100", className: "bg-score-100 text-white", band: 100 };
  }
  if (score >= 60) {
    return { label: "60-80", className: "bg-score-80 text-white", band: 80 };
  }
  if (score >= 40) {
    return { label: "40-60", className: "bg-score-60 text-white", band: 60 };
  }
  if (score >= 20) {
    return { label: "20-40", className: "bg-score-40 text-white", band: 40 };
  }
  return { label: "0-20", className: "bg-score-20 text-white", band: 20 };
}

/** Heatmap colour for a score, as a MapLibre paint expression value. */
export function scoreColourExpression(): unknown {
  // An ordered ramp rather than discrete bands, so panning the map shows gradation.
  // Colourblind-safe: blue -> teal -> green, monotonic in lightness at both ends.
  return [
    "interpolate",
    ["linear"],
    ["coalesce", ["get", "score"], -1],
    -1,
    "#94a3b8",
    0,
    "#4338a8",
    25,
    "#3b4fa8",
    45,
    "#2a7f9e",
    65,
    "#2a9d8f",
    85,
    "#66bb6a",
    100,
    "#a5d844",
  ];
}

/** Confidence band for a 0-1 confidence score. Mirrors the backend mapping. */
export function confidenceBand(score: number | null | undefined): ConfidenceBand {
  if (score === null || score === undefined || Number.isNaN(score)) return "unknown";
  if (score >= 0.75) return "high";
  if (score >= 0.55) return "medium";
  if (score >= 0.35) return "low";
  if (score > 0) return "very_low";
  return "unknown";
}

/**
 * Human-readable label for a measurement method.
 *
 * The method is always shown next to a temperature, because the method is what
 * determines how much the number can be trusted.
 */
export const MEASUREMENT_METHOD_LABELS: Record<string, string> = {
  static_bht: "Static bottom-hole survey",
  "static bottom hole temperature": "Static bottom-hole survey",
  circulation_test: "Circulation test",
  "thermal recovery test": "Thermal recovery test",
  max_dynamic: "Maximum dynamic temperature",
  dynamic: "Dynamic temperature",
  production_log: "Production log",
  dts: "DTS logging",
  dts_reprocessed: "Reprocessed DTS",
  gamma: "Gamma-derived estimate",
  regional_estimate: "Regional estimate",
  estimate: "Estimate",
  analogue: "Analogue well",
  "analogous well": "Analogue well",
  extrapolated: "Depth extrapolation",
  modelled: "Model output",
  petrophysical_model: "Petrophysical model",
  basin_model: "Basin model",
  unknown: "Unknown method",
};

/** Whether a method warrants calling the resulting temperature "measured". */
export function isDirectMeasurement(method: string | null | undefined): boolean {
  if (!method) return false;
  const key = method.toLowerCase();
  return [
    "static_bht",
    "static bottom hole temperature",
    "circulation_test",
    "thermal recovery test",
    "max_dynamic",
    "dynamic",
    "production_log",
    "dts",
    "dts_reprocessed",
  ].includes(key);
}

export const STAGE_ORDER = [
  "data_validation",
  "geology",
  "temperature",
  "well_integrity",
  "heat_demand",
  "engineering",
  "economics",
  "risk",
  "final_assessment",
] as const;

export const STAGE_LABELS: Record<string, string> = {
  data_validation: "Data validation",
  geology: "Geology",
  temperature: "Temperature",
  well_integrity: "Well integrity",
  heat_demand: "Heat demand",
  engineering: "Engineering",
  economics: "Economics",
  risk: "Risk",
  final_assessment: "Final assessment",
};

/** Title-cases a snake_case enum for display. */
export function humanise(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
