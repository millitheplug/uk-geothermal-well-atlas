"use client";

import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "@/lib/utils";

/**
 * Chart wrappers.
 *
 * Three rules applied to every chart here:
 *
 * - Axis and tick text is muted and small. Charts support the numbers; they do
 *   not become the page's typography.
 * - Tooltips always include the unit. A bare "42" on a hover is unreadable.
 * - Series colours come from the same ordered score ramp used on the map, so a
 *   colour means the same thing everywhere in the product.
 */

const AXIS_STYLE = {
  fontSize: 10,
  fill: "hsl(var(--muted-foreground))",
} as const;

const GRID_COLOUR = "hsl(var(--border))";

function ChartTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number | string; color?: string }>;
  label?: string | number;
  unit: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md">
      {label !== undefined && (
        <div className="mb-0.5 font-medium">{String(label)}</div>
      )}
      {payload.map((entry, index) => (
        <div key={index} className="flex items-center gap-1.5">
          {entry.color && (
            <span
              className="h-2 w-2 rounded-sm"
              style={{ backgroundColor: entry.color }}
              aria-hidden
            />
          )}
          <span className="text-muted-foreground">{entry.name}</span>
          <span className="tabular ml-auto font-medium">
            {typeof entry.value === "number"
              ? entry.value.toLocaleString("en-GB")
              : entry.value}{" "}
            {unit}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Ordered ramp used for categorical series. */
export const RAMP = [
  "hsl(var(--score-40))",
  "hsl(var(--score-60))",
  "hsl(var(--score-80))",
  "hsl(var(--score-100))",
  "hsl(var(--score-20))",
  "hsl(var(--score-0))",
];

export function ScoreHistogram({
  data,
  height = 200,
}: {
  data: Array<{ range: string; count: number; lower: number | null; upper: number | null }>;
  height?: number;
}) {
  if (data.length === 0) return null;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: -18 }}>
        <CartesianGrid stroke={GRID_COLOUR} vertical={false} />
        <XAxis dataKey="range" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
        <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip
          cursor={{ fill: "hsl(var(--muted))" }}
          content={<ChartTooltip unit="wells" />}
        />
        <Bar dataKey="count" name="Wells" radius={[3, 3, 0, 0]}>
          {data.map((entry, index) => (
            <Cell
              key={entry.range}
              fill={RAMP[index % RAMP.length]}
              fillOpacity={0.85}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export interface BreakdownItem {
  key: string;
  label: string;
  value: number;
  colour?: string;
  suffix?: string;
}

/**
 * Horizontal bar breakdown.
 *
 * Rendered as an ordered list rather than a chart library component: these are
 * categorical counts, and DOM text stays selectable, screen-reader legible and
 * printable. A chart is the wrong tool for eight bars of integers.
 */
export function BreakdownBars({
  items,
  max,
  emptyLabel = "No data",
  className,
  showShare = true,
}: {
  items: BreakdownItem[];
  max?: number;
  emptyLabel?: string;
  className?: string;
  showShare?: boolean;
}) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  const ceiling = max ?? Math.max(1, ...items.map((item) => item.value));

  if (items.length === 0) {
    return <p className="text-xs italic text-muted-foreground">{emptyLabel}</p>;
  }

  return (
    <ul className={cn("space-y-1.5", className)}>
      {items.map((item, index) => (
        <li key={item.key}>
          <div className="flex items-baseline justify-between gap-2 text-xs">
            <span className="truncate">{item.label}</span>
            <span className="tabular shrink-0 text-muted-foreground">
              {item.value.toLocaleString("en-GB")}
              {item.suffix}
              {showShare && total > 0 && (
                <span className="ml-1 opacity-70">
                  {((item.value / total) * 100).toFixed(0)}%
                </span>
              )}
            </span>
          </div>
          <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full"
              style={{
                width: `${(item.value / ceiling) * 100}%`,
                backgroundColor: item.colour ?? RAMP[index % RAMP.length],
              }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Score distribution as an ordered list of bands, coloured by the map ramp. */
export function ScoreBandBars({
  items,
  className,
}: {
  items: Array<{ label: string; value: number; colour: string }>;
  className?: string;
}) {
  const ceiling = Math.max(1, ...items.map((item) => item.value));

  return (
    <ul className={cn("space-y-1", className)}>
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-2 text-xs">
          <span className="w-16 shrink-0 text-muted-foreground">
            {item.label}
          </span>
          <span className="h-3 flex-1 overflow-hidden rounded-sm bg-muted">
            <span
              className="block h-full rounded-sm"
              style={{
                width: `${(item.value / ceiling) * 100}%`,
                backgroundColor: item.colour,
              }}
            />
          </span>
          <span className="tabular w-10 shrink-0 text-right">{item.value}</span>
        </li>
      ))}
    </ul>
  );
}

/** Cumulative project cash flow, with the payback point marked. */
export function CashflowChart({
  data,
  height = 220,
}: {
  data: Array<{ year: number; net: number; cumulative: number }>;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: -6 }}>
        <CartesianGrid stroke={GRID_COLOUR} vertical={false} />
        <XAxis
          dataKey="year"
          tick={AXIS_STYLE}
          tickLine={false}
          axisLine={false}
          label={{
            value: "Year",
            position: "insideBottomRight",
            offset: -2,
            fontSize: 9,
            fill: "hsl(var(--muted-foreground))",
          }}
        />
        <YAxis
          tick={AXIS_STYLE}
          tickLine={false}
          axisLine={false}
          tickFormatter={(value: number) =>
            Math.abs(value) >= 1_000_000
              ? `${(value / 1_000_000).toFixed(1)}m`
              : `${Math.round(value / 1000)}k`
          }
        />
        <Tooltip content={<ChartTooltip unit="GBP" />} />
        <Legend
          wrapperStyle={{ fontSize: 10, paddingTop: 4 }}
          iconType="plainline"
        />
        <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" />
        <Line
          type="monotone"
          dataKey="cumulative"
          name="Cumulative"
          stroke="hsl(var(--primary))"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Scenario comparison: LCOH per scenario, with the expected value marked. */
export function ScenarioCostChart({
  data,
  height = 220,
}: {
  data: Array<{ name: string; lcoh: number | null }>;
  height?: number;
}) {
  const values = data
    .map((entry) => entry.lcoh)
    .filter((value): value is number => typeof value === "number");

  if (values.length === 0) return null;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: -14 }}>
        <CartesianGrid stroke={GRID_COLOUR} vertical={false} />
        <XAxis dataKey="name" tick={AXIS_STYLE} tickLine={false} axisLine={false} />
        <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} />
        <Tooltip content={<ChartTooltip unit="p/kWh" />} cursor={{ fill: "hsl(var(--muted))" }} />
        <Bar dataKey="lcoh" name="LCOH" radius={[3, 3, 0, 0]}>
          {data.map((entry, index) => (
            <Cell
              key={entry.name}
              fill={RAMP[index % RAMP.length]}
              fillOpacity={0.85}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Risk exposure by category, ordered so the worst is at the top. */
export function RiskBars({
  items,
  className,
}: {
  items: Array<{ label: string; value: number; severity?: string }>;
  className?: string;
}) {
  const ceiling = Math.max(1, ...items.map((item) => item.value));
  const sorted = [...items].sort((a, b) => b.value - a.value);

  const severityColour = (severity?: string): string => {
    switch (severity) {
      case "critical":
        return "hsl(var(--destructive))";
      case "high":
        return "hsl(var(--priority-low))";
      case "medium":
        return "hsl(var(--priority-medium))";
      default:
        return "hsl(var(--primary))";
    }
  };

  return (
    <ul className={cn("space-y-1", className)}>
      {sorted.map((item) => (
        <li key={item.label} className="flex items-center gap-2 text-xs">
          <span className="w-40 shrink-0 truncate text-muted-foreground">
            {item.label}
          </span>
          <span className="h-3 flex-1 overflow-hidden rounded-sm bg-muted">
            <span
              className="block h-full rounded-sm"
              style={{
                width: `${(item.value / ceiling) * 100}%`,
                backgroundColor: severityColour(item.severity),
              }}
            />
          </span>
          <span className="tabular w-12 shrink-0 text-right">
            {item.value.toFixed(1)}
          </span>
          {item.severity && (
            <span className="w-14 shrink-0 text-right text-[12px] text-muted-foreground">
              {item.severity}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}