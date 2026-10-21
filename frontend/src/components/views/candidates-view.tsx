"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowRight,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  Info,
  SlidersHorizontal,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import {
  EmptyState,
  ErrorState,
  Loading,
} from "@/components/common/feedback";
import { Badge, EpistemicBadge, MockDataBanner } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import {
  CONFIDENCE_META,
  RECOMMENDATION_META,
  WELL_STATUS_LABELS,
  humanise,
  scoreBand,
} from "@/lib/domain";
import { cn, fmtDepth, fmtGBP, wellKey } from "@/lib/utils";
import type { CandidateRow, CandidateTable } from "@/types/api";

/**
 * Ranked candidate table.
 *
 * Every figure column carries its provenance badge in the header rather than
 * repeating it 200 times down the table - except temperature and output, where
 * the status differs per well and so must be per row. That is the one place
 * where a column-level label would actively mislead.
 */

const PAGE_SIZE = 50;

const COLUMNS: Array<{
  key: string;
  label: string;
  order_by?: string;
  align?: "left" | "right";
  note?: string;
}> = [
  { key: "rank", label: "#", align: "right" },
  { key: "well", label: "Well" },
  { key: "region", label: "Region" },
  { key: "status", label: "Status" },
  { key: "total_depth_m", label: "Depth", order_by: "total_depth_m", align: "right", note: "Measured" },
  { key: "temperature_c", label: "Temp", order_by: "temperature_c", align: "right", note: "Label per row" },
  { key: "thermal_output_kw", label: "Output", order_by: "thermal_output_kw", align: "right", note: "Label per row" },
  { key: "nearest_building_distance_m", label: "To demand", order_by: "nearest_building_distance_m", align: "right", note: "Derived. No match within 2 km means demand is unknown here, not zero." },
  { key: "annual_demand_kwh", label: "Demand", order_by: "annual_demand_kwh", align: "right", note: "Estimate" },
  { key: "capex_gbp", label: "CAPEX", order_by: "capex_gbp", align: "right", note: "Estimate" },
  { key: "lcoh_p_per_kwh", label: "LCOH", order_by: "lcoh_p_per_kwh", align: "right", note: "Derived" },
  { key: "feasibility_score", label: "Score", order_by: "feasibility_score", align: "right" },
  { key: "confidence_score", label: "Confidence", order_by: "confidence_score", align: "right" },
  { key: "recommendation", label: "Recommendation", order_by: "recommendation" },
];

export function CandidatesView() {
  const [offset, setOffset] = React.useState(0);
  const [orderBy, setOrderBy] = React.useState("feasibility_score");
  const [descending, setDescending] = React.useState(true);
  const [minScore, setMinScore] = React.useState("");
  const [minTemperature, setMinTemperature] = React.useState("");
  const [maxDistance, setMaxDistance] = React.useState("");
  const [recommendation, setRecommendation] = React.useState<string[]>([]);
  const [includeMock, setIncludeMock] = React.useState(true);
  // Below md the filters fold away so the results are the first thing shown.
  const [filtersOpen, setFiltersOpen] = React.useState(false);
  const activeFilters =
    [minScore, minTemperature, maxDistance].filter((value) => value !== "").length +
    recommendation.length;

  const params = React.useMemo(
    () => ({
      min_score: minScore ? Number(minScore) : undefined,
      min_temperature_c: minTemperature ? Number(minTemperature) : undefined,
      max_nearest_demand_m: maxDistance ? Number(maxDistance) : undefined,
      recommendation: recommendation.length ? recommendation : undefined,
      include_mock: includeMock,
      order_by: orderBy,
      descending,
      limit: PAGE_SIZE,
      offset,
    }),
    [minScore, minTemperature, maxDistance, recommendation, includeMock, orderBy, descending, offset],
  );

  const { data, error, loading, refresh } = useApiData<CandidateTable>(
    (signal) => api.candidates(params, signal),
    [JSON.stringify(params)],
  );

  const sortBy = (column: string) => {
    if (orderBy === column) {
      setDescending((value) => !value);
    } else {
      setOrderBy(column);
      setDescending(true);
    }
    setOffset(0);
  };

  return (
    <>
      <PageHeader
        title="Candidate ranking"
        subtitle="Every assessed well, ordered by the deterministic composite score"
        actions={
          <Button variant="outline" size="sm" onClick={exportCsv}>
            <Download className="h-3.5 w-3.5" aria-hidden />
            Export the current page
          </Button>
        }
      />

      <div className="shrink-0 border-b bg-card/60 px-4 py-2 sm:px-6 md:py-4 lg:px-8">
        <button
          type="button"
          onClick={() => setFiltersOpen((open) => !open)}
          aria-expanded={filtersOpen}
          aria-controls="candidate-filters"
          className="flex min-h-10 w-full items-center justify-between text-sm font-medium md:hidden"
        >
          <span className="inline-flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4" aria-hidden />
            Filters
            {activeFilters > 0 && (
              <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-[11px] font-semibold text-accent-foreground">
                {activeFilters}
              </span>
            )}
          </span>
          <ChevronDown
            className={cn("h-4 w-4 transition-transform", filtersOpen && "rotate-180")}
            aria-hidden
          />
        </button>
        <div
          id="candidate-filters"
          className={cn(
            "mt-3 gap-x-4 gap-y-3.5 sm:grid-cols-2 md:mt-0 lg:grid-cols-4",
            filtersOpen ? "grid" : "hidden md:grid",
          )}
        >
          <LabeledInput
            label="Min score"
            type="number"
            min={0}
            max={100}
            value={minScore}
            onChange={(value) => {
              setMinScore(value);
              setOffset(0);
            }}
            placeholder="0"
          />
          <LabeledInput
            label="Min temperature (°C)"
            type="number"
            value={minTemperature}
            onChange={(value) => {
              setMinTemperature(value);
              setOffset(0);
            }}
            placeholder="e.g. 55"
          />
          <LabeledInput
            label="Max distance to demand (m)"
            type="number"
            value={maxDistance}
            onChange={(value) => {
              setMaxDistance(value);
              setOffset(0);
            }}
            placeholder="e.g. 2000"
          />
          <div className="sm:col-span-2 lg:col-span-4">
            <div className="text-xs font-medium text-muted-foreground">
              Recommendation
            </div>
            <div className="mt-1.5 flex flex-wrap gap-2">
              {Object.keys(RECOMMENDATION_META).map((level) => {
                const active = recommendation.includes(level);
                return (
                  <button
                    key={level}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setRecommendation((current) =>
                        current.includes(level)
                          ? current.filter((item) => item !== level)
                          : [...current, level],
                      );
                      setOffset(0);
                    }}
                    className={`min-h-9 rounded-full border px-3.5 py-1 text-xs transition-colors md:min-h-0 md:py-1 ${
                      active
                        ? "border-primary bg-primary/10 font-medium text-primary"
                        : "border-border text-muted-foreground hover:bg-muted"
                    }`}
                  >
                    {level}
                  </button>
                );
              })}
            </div>
          </div>
          <label className="flex min-h-10 items-center gap-2.5 text-sm sm:col-span-2 lg:col-span-1 lg:self-end">
            <input
              type="checkbox"
              checked={includeMock}
              onChange={(event) => setIncludeMock(event.target.checked)}
              className="h-4 w-4 rounded border-input accent-primary"
            />
            Include synthetic wells
          </label>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-5 sm:px-6 lg:px-8">
        {error && (
          <ErrorState
            title="The candidate table could not be loaded"
            message={error}
            isOffline={error.includes("Could not reach")}
            onRetry={refresh}
          />
        )}

        {loading && !data && <Loading label="Building the ranking" />}

        {data && (
          <div className="space-y-3">
            {data.includes_mock_data && <MockDataBanner isMock what="this ranking" />}

            {data.items.length === 0 ? (
              <EmptyState
                title="No wells match these filters"
                message="Widen the filters, or check that assessments have been run. A well only appears in the ranking once the engineering pipeline has scored it."
              />
            ) : (
              <>
              <Card className="hidden overflow-hidden md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {COLUMNS.map((column) => (
                        <TableHead
                          key={column.key}
                          className={cn(
                            column.align === "right" && "text-right",
                            // Region is "Not recorded" for most wells, so it
                            // gives way to the figures on all but very wide screens.
                            column.key === "region" && "hidden 2xl:table-cell",
                          )}
                          title={column.note}
                        >
                          {column.order_by ? (
                            <button
                              type="button"
                              onClick={() => sortBy(column.order_by!)}
                              className={`inline-flex items-center gap-1 hover:text-foreground ${
                                column.align === "right" ? "flex-row-reverse" : ""
                              }`}
                            >
                              {column.label}
                              {orderBy === column.order_by && (
                                <span aria-hidden>
                                  {descending ? "▾" : "▴"}
                                </span>
                              )}
                            </button>
                          ) : (
                            column.label
                          )}
                        </TableHead>
                      ))}
                      <TableHead className="w-8" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.items.map((row) => (
                      <CandidateRowView key={row.well_id} row={row} />
                    ))}
                  </TableBody>
                </Table>
              </Card>
              <ul className="space-y-3 md:hidden" aria-label="Candidates">
                {data.items.map((row) => (
                  <CandidateCard key={row.well_id} row={row} />
                ))}
              </ul>
              </>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>
                Showing {data.offset + 1}–
                {Math.min(data.offset + data.items.length, data.total)} of{" "}
                {data.total.toLocaleString("en-GB")} candidates. Ranked by{" "}
                <code className="font-mono">{data.ranking_basis}</code>.
              </span>
              <div className="flex items-center gap-1.5">
                <Button
                  variant="outline"
                  size="xs"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  <ChevronLeft className="h-3 w-3" aria-hidden />
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="xs"
                  disabled={offset + PAGE_SIZE >= data.total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  Next
                  <ChevronRight className="h-3 w-3" aria-hidden />
                </Button>
              </div>
            </div>

            <div className="flex items-start gap-2 rounded-md border bg-muted/40 p-3 text-xs leading-relaxed text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              <p>
                The score column is the weighted sum produced by the Python
                scoring engine: thermal 25%, integrity 20%, demand 15%, economics
                15%, network 10%, geometry 5%, regulatory 5% and data confidence
                5%. Evidence quality counts for 5% of the score, and it can also
                pull a well down a priority level: the separate confidence rating
                gates HIGH and MEDIUM priority, so a well with a strong score on
                thin evidence stays visible as such.
              </p>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function CandidateRowView({ row }: { row: CandidateRow }) {
  const band = scoreBand(row.feasibility_score);
  const recommendation = row.recommendation
    ? RECOMMENDATION_META[row.recommendation]
    : null;
  const confidence = CONFIDENCE_META[row.temperature_confidence];

  return (
    <TableRow className={row.is_mock ? "bg-destructive/[0.03]" : undefined}>
      <TableCell className="whitespace-nowrap text-right text-muted-foreground">{row.rank}</TableCell>
      <TableCell className="min-w-[10.5rem]">
        <Link
          href={`/wells/${wellKey(row)}`}
          className="font-medium hover:text-primary hover:underline"
        >
          {row.well_name}
        </Link>
        <div className="font-mono text-[12px] text-muted-foreground">
          {row.well_id}
        </div>
      </TableCell>
      <TableCell className="hidden min-w-[7.5rem] text-muted-foreground 2xl:table-cell">
        {row.region ?? <span className="italic">Not recorded</span>}
      </TableCell>
      <TableCell>
        <span className="text-xs">
          {WELL_STATUS_LABELS[row.status] ?? humanise(row.status)}
        </span>
      </TableCell>
      <TableCell className="whitespace-nowrap text-right">{fmtDepth(row.total_depth_m)}</TableCell>
      <TableCell className="whitespace-nowrap text-right">
        <span className="inline-flex items-center gap-1">
          {row.temperature_c !== null ? (
            <>
              <span>{row.temperature_c.toFixed(1)}</span>
              <span className="text-[12px] text-muted-foreground">°C</span>
              <EpistemicBadge status={row.temperature_status} />
            </>
          ) : (
            <span className="text-xs italic text-muted-foreground">
              Not available
            </span>
          )}
        </span>
      </TableCell>
      <TableCell className="whitespace-nowrap text-right">
        <span className="inline-flex items-center gap-1">
          {row.thermal_output_kw !== null ? (
            <>
              <span>{row.thermal_output_kw.toFixed(0)}</span>
              <span className="text-[12px] text-muted-foreground">kW</span>
              <EpistemicBadge status={row.thermal_output_status} />
            </>
          ) : (
            <span className="text-xs italic text-muted-foreground">
              Not available
            </span>
          )}
        </span>
      </TableCell>
      <TableCell className="whitespace-nowrap text-right">
        {row.nearest_building_distance_m !== null ? (
          `${Math.round(row.nearest_building_distance_m).toLocaleString("en-GB")} m`
        ) : row.feasibility_score !== null ? (
          <span
            className="text-xs italic text-muted-foreground"
            title="The assessment searched for buildings within 2 km and found none. Demand near this well is unknown, not zero."
          >
            No match within 2 km
          </span>
        ) : (
          <Missing />
        )}
      </TableCell>
      <TableCell className="whitespace-nowrap text-right">
        {row.annual_demand_kwh !== null
          ? `${(row.annual_demand_kwh / 1000).toFixed(0)} MWh`
          : <Missing />}
      </TableCell>
      <TableCell className="whitespace-nowrap text-right">
        {row.capex_gbp !== null ? fmtGBP(row.capex_gbp) : <Missing />}
      </TableCell>
      <TableCell className="whitespace-nowrap text-right">
        {row.lcoh_p_per_kwh !== null
          ? `${row.lcoh_p_per_kwh.toFixed(1)}p`
          : <Missing />}
      </TableCell>
      <TableCell className="whitespace-nowrap text-right">
        {row.feasibility_score !== null ? (
          <span className="inline-flex items-center gap-1.5">
            <span
              className={`inline-flex h-5 min-w-[2.25rem] items-center justify-center rounded px-1 font-semibold text-white ${band.className}`}
            >
              {Math.round(row.feasibility_score)}
            </span>
          </span>
        ) : (
          <Missing />
        )}
      </TableCell>
      <TableCell className="whitespace-nowrap text-right">
        {row.confidence_score !== null ? (
          <span
            className="text-xs"
            title={confidence?.description}
          >
            {Math.round(row.confidence_score * 100)}%
          </span>
        ) : (
          <Missing />
        )}
      </TableCell>
      <TableCell>
        {recommendation ? (
          <Badge className={`${recommendation.className} text-[11px]`}>
            {row.recommendation}
          </Badge>
        ) : (
          <Missing />
        )}
      </TableCell>
      <TableCell>
        <Button variant="ghost" size="icon-sm" asChild>
          <Link href={`/wells/${wellKey(row)}`} aria-label={`Open ${row.well_name}`}>
            <ArrowRight className="h-3 w-3" aria-hidden />
          </Link>
        </Button>
      </TableCell>
    </TableRow>
  );
}

/**
 * One candidate as a card, shown below the `md` breakpoint where a 14-column
 * table cannot be read. It draws on the same row and the same provenance
 * badges as the table; only the arrangement differs.
 */
function CandidateCard({ row }: { row: CandidateRow }) {
  const band = scoreBand(row.feasibility_score);
  const recommendation = row.recommendation
    ? RECOMMENDATION_META[row.recommendation]
    : null;

  const facts: Array<{ label: string; value: React.ReactNode }> = [
    { label: "Depth", value: fmtDepth(row.total_depth_m) },
    {
      label: "Temperature",
      value:
        row.temperature_c !== null ? (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <span>{row.temperature_c.toFixed(1)} °C</span>
            <EpistemicBadge status={row.temperature_status} />
          </span>
        ) : (
          <Missing />
        ),
    },
    {
      label: "Thermal output",
      value:
        row.thermal_output_kw !== null ? (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <span>{row.thermal_output_kw.toFixed(0)} kW</span>
            <EpistemicBadge status={row.thermal_output_status} />
          </span>
        ) : (
          <Missing />
        ),
    },
    {
      label: "To demand",
      value:
        row.nearest_building_distance_m !== null ? (
          `${Math.round(row.nearest_building_distance_m).toLocaleString("en-GB")} m`
        ) : row.feasibility_score !== null ? (
          <span className="text-xs italic text-muted-foreground">
            No match within 2 km
          </span>
        ) : (
          <Missing />
        ),
    },
    {
      label: "CAPEX",
      value: row.capex_gbp !== null ? fmtGBP(row.capex_gbp) : <Missing />,
    },
    {
      label: "LCOH",
      value:
        row.lcoh_p_per_kwh !== null ? (
          `${row.lcoh_p_per_kwh.toFixed(1)}p`
        ) : (
          <Missing />
        ),
    },
  ];

  return (
    <li
      className={`relative rounded-lg border bg-card p-4 ${
        row.is_mock ? "border-destructive/30 bg-destructive/[0.03]" : ""
      }`}
    >
      <div className="flex items-start gap-3">
        <span className="font-display w-8 shrink-0 text-[1.75rem] text-muted-foreground">
          {row.rank}
        </span>
        <div className="min-w-0 flex-1">
          {/* Stretched link: the whole card opens the well. */}
          <Link
            href={`/wells/${wellKey(row)}`}
            className="block truncate font-semibold after:absolute after:inset-0 after:content-['']"
          >
            {row.well_name}
          </Link>
          <div className="truncate font-mono text-xs text-muted-foreground">
            {row.well_id}
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {WELL_STATUS_LABELS[row.status] ?? humanise(row.status)}
            {row.region ? ` · ${row.region}` : ""}
          </div>
        </div>
        {row.feasibility_score !== null && (
          <span
            className={`inline-flex h-8 min-w-[2.75rem] shrink-0 items-center justify-center rounded px-2 text-base font-semibold text-white ${band.className}`}
            title="Feasibility score"
          >
            {Math.round(row.feasibility_score)}
          </span>
        )}
      </div>

      <dl className="mt-3.5 grid grid-cols-2 gap-x-4 gap-y-3 border-t pt-3.5 text-sm">
        {facts.map((fact) => (
          <div key={fact.label} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{fact.label}</dt>
            <dd className="mt-0.5">{fact.value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-3.5 flex flex-wrap items-center gap-2">
        {recommendation ? (
          <Badge className={`${recommendation.className} text-[11px]`}>
            {row.recommendation}
          </Badge>
        ) : (
          <Missing />
        )}
        {row.confidence_score !== null && (
          <span className="text-xs text-muted-foreground">
            Evidence confidence {Math.round(row.confidence_score * 100)}%
          </span>
        )}
      </div>
    </li>
  );
}

function Missing() {
  return (
    <span className="text-xs italic text-muted-foreground">Not available</span>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  ...props
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <div>
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <Input
        {...props}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5"
      />
    </div>
  );
}

/** Client-side CSV export of whatever is currently on screen. */
function exportCsv(): void {
  const headers = [
    "rank",
    "well_id",
    "well_name",
    "region",
    "status",
    "total_depth_m",
    "temperature_c",
    "temperature_status",
    "thermal_output_kw",
    "nearest_building_distance_m",
    "annual_demand_kwh",
    "capex_gbp",
    "lcoh_p_per_kwh",
    "feasibility_score",
    "confidence_score",
    "recommendation",
    "is_mock",
  ];

  // Read the rendered rows back off the page. A dedicated fetch would risk the
  // export silently disagreeing with what the user is looking at if a filter
  // changed mid-flight.
  const rows = Array.from(
    document.querySelectorAll<HTMLTableRowElement>("table tbody tr"),
  );

  const lines = [headers.join(",")];

  for (const row of rows) {
    const cells = Array.from(row.querySelectorAll("td")).map((cell) =>
      (cell.textContent ?? "").replace(/[\n\r]+/g, " ").trim(),
    );
    lines.push(cells.slice(0, headers.length).map(csvCell).join(","));
  }

  const blob = new Blob([lines.join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "uk-geothermal-candidates.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function csvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}