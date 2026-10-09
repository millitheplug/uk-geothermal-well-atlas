"use client";

import * as React from "react";
import Link from "next/link";
import {
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Map as MapIcon,
  Search,
  X,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import {
  EmptyState,
  ErrorState,
  Loading,
  Notice,
} from "@/components/common/feedback";
import { WellMap } from "@/components/map/well-map";
import { Badge, EpistemicBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import type { WellSearchParams } from "@/lib/api";
import {
  CONFIDENCE_META,
  WELL_STATUS_LABELS,
  humanise,
  scoreBand,
} from "@/lib/domain";
import { fmtDepth } from "@/lib/utils";
import type { WellSearchResponse } from "@/types/api";

/**
 * Well explorer.
 *
 * Full inventory search: unlike the candidate ranking this shows unassessed
 * wells too, because "we have no temperature record for this borehole" is a
 * finding a user needs to find, not hide behind a score filter.
 */
export function ExplorerView() {
  const [search, setSearch] = React.useState("");
  const [status, setStatus] = React.useState<string[]>([]);
  const [region, setRegion] = React.useState<string[]>([]);
  const [purpose, setPurpose] = React.useState<string[]>([]);
  const [confidence, setConfidence] = React.useState<string[]>([]);
  const [hasTemperature, setHasTemperature] = React.useState<"any" | "yes" | "no">("any");
  const [maxDistance, setMaxDistance] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [showMap, setShowMap] = React.useState(true);
  const [includeMock, setIncludeMock] = React.useState(true);

  const pageSize = 100;

  const params = React.useMemo<WellSearchParams>(
    () => ({
      search: search.trim() || undefined,
      status: status.length ? status : undefined,
      region: region.length ? region : undefined,
      original_purpose: purpose.length ? purpose : undefined,
      min_data_confidence: confidence.length ? confidence : undefined,
      has_temperature: hasTemperature === "any" ? undefined : hasTemperature === "yes",
      max_nearest_demand_m: maxDistance ? Number(maxDistance) : undefined,
      include_mock: includeMock,
      limit: pageSize,
      offset,
      order_by: "feasibility_score",
      descending: true,
    }),
    [search, status, region, purpose, confidence, hasTemperature, maxDistance, includeMock, offset],
  );

  const facets = useApiData((signal) => api.wellFacets(signal), []);
  const wells = useApiData<WellSearchResponse>(
    (signal) => api.searchWells(params, signal),
    [JSON.stringify(params)],
  );
  const mapData = useApiData(
    (signal) =>
      api.wellMapFeatures({ ...params, include_claimable: true }, signal),
    [JSON.stringify({ ...params, offset: 0 })],
  );

  const activeCount =
    (search ? 1 : 0) +
    status.length +
    region.length +
    purpose.length +
    confidence.length +
    (hasTemperature !== "any" ? 1 : 0) +
    (maxDistance ? 1 : 0);

  const clearAll = () => {
    setSearch("");
    setStatus([]);
    setRegion([]);
    setPurpose([]);
    setConfidence([]);
    setHasTemperature("any");
    setMaxDistance("");
    setOffset(0);
  };

  return (
    <>
      <PageHeader
        title="Well explorer"
        subtitle="Search the whole inventory, including wells that have never been assessed"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowMap((value) => !value)}
          >
            {showMap ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
            {showMap ? "Hide map" : "Show map"}
          </Button>
        }
      />

      {/* Filters */}
      <div className="shrink-0 space-y-2.5 border-b bg-card/50 px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[15rem] flex-1 sm:max-w-sm">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setOffset(0);
              }}
              placeholder="Well name, ID, operator, licence or formation"
              className="h-8 pl-8 text-xs"
              aria-label="Search wells"
            />
          </div>
          {activeCount > 0 && (
            <Button variant="ghost" size="xs" onClick={clearAll}>
              <X className="h-3 w-3" aria-hidden />
              Clear {activeCount} filter{activeCount === 1 ? "" : "s"}
            </Button>
          )}
          <label className="ml-auto flex items-center gap-1.5 text-[11px]">
            <input
              type="checkbox"
              checked={includeMock}
              onChange={(event) => {
                setIncludeMock(event.target.checked);
                setOffset(0);
              }}
              className="h-3.5 w-3.5 rounded border-input"
            />
            Include synthetic wells
          </label>
        </div>

        <div className="grid gap-2 lg:grid-cols-4">
          <FacetRow
            label="Status"
            options={(facets.data?.statuses ?? []).map((value) => ({
              value,
              label: WELL_STATUS_LABELS[value] ?? humanise(value),
            }))}
            selected={status}
            onToggle={(value) => {
              setStatus(toggle(status, value));
              setOffset(0);
            }}
          />
          <FacetRow
            label="Region"
            options={(facets.data?.regions ?? []).map((value) => ({ value, label: value }))}
            selected={region}
            onToggle={(value) => {
              setRegion(toggle(region, value));
              setOffset(0);
            }}
          />
          <FacetRow
            label="Original purpose"
            options={(facets.data?.purposes ?? []).map((value) => ({
              value,
              label: humanise(value),
            }))}
            selected={purpose}
            onToggle={(value) => {
              setPurpose(toggle(purpose, value));
              setOffset(0);
            }}
          />
          <FacetRow
            label="Data confidence"
            options={(facets.data?.confidence_bands ?? []).map((value) => ({
              value,
              label: (CONFIDENCE_META as Record<string, { label: string }>)[value]?.label ?? value,
            }))}
            selected={confidence}
            onToggle={(value) => {
              setConfidence(toggle(confidence, value));
              setOffset(0);
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-3 text-[11px]">
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Temperature record</span>
            {(["any", "yes", "no"] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={hasTemperature === option}
                onClick={() => {
                  setHasTemperature(option);
                  setOffset(0);
                }}
                className={`rounded-full border px-2 py-0.5 text-[10px] ${
                  hasTemperature === option
                    ? "border-primary bg-primary/10 font-medium text-primary"
                    : "border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                {option === "any" ? "Any" : option === "yes" ? "Has one" : "None"}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Max distance to demand (m)</span>
            <Input
              type="number"
              value={maxDistance}
              onChange={(event) => {
                setMaxDistance(event.target.value);
                setOffset(0);
              }}
              className="h-7 w-24 text-xs"
            />
          </label>
        </div>
      </div>

      {/* Results */}
      <div className={showMap ? "grid min-h-0 flex-1 lg:grid-cols-[1fr_1fr]" : "flex min-h-0 flex-1 flex-col"}>
        <div className="min-h-0 overflow-auto">
          {wells.loading && !wells.data && <Loading label="Searching the inventory" />}

          {wells.error && (
            <div className="p-4">
              <ErrorState message={wells.error} onRetry={wells.refresh} />
            </div>
          )}

          {wells.data && wells.data.items.length === 0 && (
            <div className="p-4">
              <EmptyState
                title="No wells match"
                message="Clear a filter or broaden the search. Wells are national reference data; if a well you expect is missing, it may not have been ingested by any adapter yet."
              />
            </div>
          )}

          {wells.data && wells.data.items.length > 0 && (
            <ul className="divide-y">
              {wells.data.items.map((well) => {
                const band = scoreBand(well.feasibility_score);
                const active = selected === well.id;
                return (
                  <li key={well.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(well.id)}
                      className={`flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted/50 ${
                        active ? "bg-primary/5" : ""
                      }`}
                    >
                      <span
                        className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-[11px] font-semibold ${band.className}`}
                      >
                        {well.feasibility_score !== null
                          ? Math.round(well.feasibility_score)
                          : "?"}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-baseline gap-x-2">
                          <span className="truncate text-xs font-medium">
                            {well.well_name}
                          </span>
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {well.well_id}
                          </span>
                          {well.is_mock && (
                            <Badge className="mock-badge text-[9px]" variant="outline">
                              synthetic
                            </Badge>
                          )}
                        </span>
                        <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                          <span>
                            {WELL_STATUS_LABELS[well.status] ?? humanise(well.status)}
                          </span>
                          <span>{fmtDepth(well.total_depth_m)}</span>
                          <span className="inline-flex items-center gap-1">
                            {well.temperature_c !== null ? (
                              <>
                                <span className="tabular text-foreground">
                                  {well.temperature_c.toFixed(1)} °C
                                </span>
                                <EpistemicBadge status={well.temperature_status} />
                              </>
                            ) : (
                              <span className="italic text-epistemic-unknown">
                                No temperature record
                              </span>
                            )}
                          </span>
                          {well.region && <span>{well.region}</span>}
                          {well.operator && <span>{well.operator}</span>}
                        </span>
                      </span>
                      {well.recommendation && (
                        <span className="shrink-0 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {well.recommendation}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {wells.data && (
            <div className="sticky bottom-0 flex items-center justify-between gap-2 border-t bg-card px-3 py-2 text-[11px] text-muted-foreground">
              <span>
                {wells.data.offset + 1}–
                {Math.min(wells.data.offset + wells.data.items.length, wells.data.total)} of{" "}
                {wells.data.total.toLocaleString("en-GB")}
              </span>
              <span className="font-mono text-[10px]">
                {wells.data.spatial_dialect}
              </span>
              <div className="flex gap-1.5">
                <Button
                  variant="outline"
                  size="xs"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - pageSize))}
                >
                  <ChevronLeft className="h-3 w-3" aria-hidden />
                </Button>
                <Button
                  variant="outline"
                  size="xs"
                  disabled={offset + pageSize >= wells.data.total}
                  onClick={() => setOffset(offset + pageSize)}
                >
                  <ChevronRight className="h-3 w-3" aria-hidden />
                </Button>
              </div>
            </div>
          )}
        </div>

        {showMap && (
          <div className="hidden min-h-0 border-l lg:block">
            {mapData.data ? (
              <WellMap
                wells={mapData.data.features}
                selectedWellId={selected}
                onSelectWell={(id) => setSelected(id)}
                className="h-full w-full"
              />
            ) : (
              <div className="flex h-full items-center justify-center">
                <Loading label="Loading map" compact />
              </div>
            )}
          </div>
        )}
      </div>

      {selected && (
        <div className="shrink-0 border-t bg-card px-3 py-2">
          <div className="flex items-center justify-between gap-3 text-[11px]">
            <Notice tone="info">
              <span>
                Open the full record to see the temperature history, integrity
                status, matched demand and the complete calculation trace.
              </span>
            </Notice>
            <div className="flex shrink-0 gap-1.5">
              <Button variant="ghost" size="xs" onClick={() => setSelected(null)}>
                Dismiss
              </Button>
              <Button size="xs" asChild>
                <Link href={`/wells/${selected}`}>
                  <MapIcon className="h-3 w-3" aria-hidden />
                  Open full record
                </Link>
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function FacetRow({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: Array<{ value: string; label: string }>;
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 flex max-h-16 flex-wrap gap-1 overflow-y-auto">
        {options.length === 0 && (
          <span className="text-[10px] italic text-muted-foreground">
            Facets unavailable
          </span>
        )}
        {options.map((option) => {
          const active = selected.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              onClick={() => onToggle(option.value)}
              className={`rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                active
                  ? "border-primary bg-primary/10 font-medium text-primary"
                  : "border-border text-muted-foreground hover:bg-muted"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function toggle(current: string[], value: string): string[] {
  return current.includes(value)
    ? current.filter((item) => item !== value)
    : [...current, value];
}