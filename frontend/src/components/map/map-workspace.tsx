"use client";

import * as React from "react";
import {
  Building2,
  Filter,
  Layers,
  RefreshCw,
  Route,
  Search,
  X,
} from "lucide-react";

import { WellMap } from "@/components/map/well-map";
import { WellPanel } from "@/components/map/well-panel";
import {
  AdoptWellPanel,
  type UnadoptedWellSummary,
} from "@/components/projects/adopt-well";
import { AssessmentProgress } from "@/components/analysis/assessment-panels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge, MockDataBanner } from "@/components/ui/badge";
import { Switch } from "@/components/ui/primitives";
import { ErrorState, Loading } from "@/components/common/feedback";
import { useApiData } from "@/components/providers/app-provider";
import { api } from "@/lib/api";
import type { WellSearchParams } from "@/lib/api";
import type { MapFeature } from "@/lib/basemap";
import { humanise } from "@/lib/domain";
import { cn } from "@/lib/utils";
import type { AnalysisProgress as ProgressType, AnalysisResult, WellDetail } from "@/types/api";

/**
 * The national map workspace.
 *
 * Full-bleed map, a thin filter bar, and a slide-over panel. Clicking a marker
 * fetches the well's full record rather than trusting the map feature's summary
 * properties, so the panel can show provenance and evidence gaps rather than a
 * few denormalised columns.
 */
export function MapWorkspace() {
  const [search, setSearch] = React.useState("");
  const [status, setStatus] = React.useState<string[]>([]);
  const [minScore, setMinScore] = React.useState<string>("");
  const [minTemp, setMinTemp] = React.useState<string>("");
  const [minConfidence, setMinConfidence] = React.useState<string[]>([]);
  const [includeMock, setIncludeMock] = React.useState(true);
  const [showFilters, setShowFilters] = React.useState(false);

  const [showBuildings, setShowBuildings] = React.useState(false);
  const [showClusters, setShowClusters] = React.useState(false);
  const [showCorridors, setShowCorridors] = React.useState(false);
  // Layer toggles are always open on a wide screen; on a phone they sit behind a
  // button so they do not cover the map.
  const [layersOpen, setLayersOpen] = React.useState(false);

  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [unadopted, setUnadopted] = React.useState<UnadoptedWellSummary | null>(null);
  const [analysis, setAnalysis] = React.useState<AnalysisResult | null>(null);
  const [progress, setProgress] = React.useState<ProgressType | null>(null);
  const [running, setRunning] = React.useState(false);

  const params = React.useMemo<WellSearchParams>(
    () => ({
      search: search.trim() || undefined,
      status: status.length ? status : undefined,
      min_score: minScore ? Number(minScore) : undefined,
      min_temperature_c: minTemp ? Number(minTemp) : undefined,
      min_data_confidence: minConfidence.length ? minConfidence : undefined,
      include_mock: includeMock,
    }),
    [search, status, minScore, minTemp, minConfidence, includeMock],
  );

  const facets = useApiData((signal) => api.wellFacets(signal), []);

  const map = useApiData(
    (signal) =>
      api.wellMapFeatures({ ...params, include_claimable: true }, signal),
    [JSON.stringify(params)],
  );

  const detail = useApiData<WellDetail>(
    (signal) => api.getWell(selectedId!, signal),
    [selectedId],
    { skip: !selectedId },
  );

  const heat = useApiData(
    (signal) => api.heatClusters({}, signal),
    [],
    { skip: !showBuildings && !showClusters },
  );

  const corridors = useApiData(
    (signal) => api.corridors({ limit_wells: 40 }, signal),
    [],
    { skip: !showCorridors },
  );

  // A new selection invalidates any previous assessment; showing the old
  // analysis against the new well's numbers would be the single worst mistake
  // this interface could make.
  React.useEffect(() => {
    setAnalysis(null);
    setProgress(null);
  }, [selectedId]);

  /**
   * Resolve a clicked marker into either a detail panel or an adoption panel.
   *
   * The decision is made from the map feature's `claimable` flag rather than
   * from whether the detail request succeeds. Trying the detail request first
   * would produce a 404 for every unadopted well, and an error message is not an
   * explanation of why the record is withheld.
   */
  const selectFeature = (_wellUuid: string, feature: MapFeature) => {
    const properties = feature.properties ?? {};
    if (properties.claimable === true) {
      setUnadopted({
        id: String(properties.id),
        wellId: String(properties.well_id ?? ""),
        name: String(properties.name ?? ""),
        region: (properties.region as string | null) ?? null,
        status: (properties.status as string | null) ?? null,
        temperatureC:
          typeof properties.temperature_c === "number"
            ? properties.temperature_c
            : null,
        temperatureStatus:
          (properties.temperature_status as string | null) ?? null,
        depthM:
          typeof properties.depth_m === "number" ? properties.depth_m : null,
        claimable: true,
      });
      setSelectedId(null);
      return;
    }
    setUnadopted(null);
    setSelectedId(String(properties.id));
  };

  const runAssessment = async () => {
    if (!selectedId) return;
    setRunning(true);
    setProgress(null);
    try {
      const result = await api.runAnalysis(selectedId, {}, true);
      setAnalysis(result);
    } catch {
      setProgress({
        analysis_id: "",
        status: "failed",
        stage: "final_assessment",
        completed_stages: [],
        stage_messages: {},
        percent_complete: 0,
        error_message:
          "The assessment could not be completed. The deterministic engine may have rejected the input data; check the backend logs for the validation failure.",
      });
    } finally {
      setRunning(false);
    }
  };

  const activeFilters =
    (search ? 1 : 0) +
    status.length +
    (minScore ? 1 : 0) +
    (minTemp ? 1 : 0) +
    minConfidence.length;

  const clearAll = () => {
    setSearch("");
    setStatus([]);
    setMinScore("");
    setMinTemp("");
    setMinConfidence([]);
  };

  const buildingFeatures: MapFeature[] = React.useMemo(() => {
    if (!heat.data) return [];
    return heat.data.map((cluster) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [cluster.centroid_longitude, cluster.centroid_latitude],
      },
      properties: {
        cluster_id: cluster.cluster_id,
        buildings: cluster.building_count,
        demand_kwh: cluster.total_annual_demand_kwh,
      },
    }));
  }, [heat.data]);

  const corridorFeatures: MapFeature[] = React.useMemo(() => {
    if (!corridors.data) return [];
    return corridors.data.corridors.map((corridor) => ({
      type: "Feature",
      geometry: corridor.geometry,
      properties: {
        well_id: corridor.well_id,
        well_name: corridor.well_name,
        distance_m: corridor.distance_m,
        indicative: corridor.indicative,
      },
    }));
  }, [corridors.data]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Filter bar */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-card px-3 py-2.5 sm:px-4">
        <div className="relative min-w-[14rem] flex-1 sm:max-w-xs">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search well name, ID, operator or licence"
            className="pl-9"
            aria-label="Search wells"
          />
        </div>

        <Button
          variant={showFilters ? "default" : "outline"}
          size="sm"
          onClick={() => setShowFilters((value) => !value)}
        >
          <Filter className="h-3.5 w-3.5" aria-hidden />
          Filters
          {activeFilters > 0 && (
            <span className="ml-1 rounded bg-primary-foreground/20 px-1 text-[12px]">
              {activeFilters}
            </span>
          )}
        </Button>

        {activeFilters > 0 && (
          <Button variant="ghost" size="xs" onClick={clearAll}>
            <X className="h-3 w-3" aria-hidden />
            Clear
          </Button>
        )}

        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          {map.data && (
            <span className="tabular">
              {map.data.features.length.toLocaleString("en-GB")} wells
              {map.data.features.length >= 5000 && "+"}
            </span>
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={map.refresh}
            aria-label="Refresh map data"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </div>
      </div>

      {showFilters && (
        <div className="grid shrink-0 gap-3 border-b bg-card/50 px-3 py-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <FilterField label="Feasibility score ≥">
            <Input
              type="number"
              min={0}
              max={100}
              value={minScore}
              onChange={(event) => setMinScore(event.target.value)}
              placeholder="0"
              className="h-8 text-xs"
            />
          </FilterField>

          <FilterField label="Bottom-hole temperature ≥ (°C)">
            <Input
              type="number"
              min={0}
              value={minTemp}
              onChange={(event) => setMinTemp(event.target.value)}
              placeholder="e.g. 60"
              className="h-8 text-xs"
            />
          </FilterField>

          <FilterField label="Well status">
            <ChipGroup
              options={(facets.data?.statuses ?? []).map((value) => ({
                value,
                label: humanise(value),
              }))}
              selected={status}
              onToggle={(value) =>
                setStatus((current) =>
                  current.includes(value)
                    ? current.filter((item) => item !== value)
                    : [...current, value],
                )
              }
            />
          </FilterField>

          <FilterField label="Evidence confidence">
            <ChipGroup
              options={(facets.data?.confidence_bands ?? []).map((value) => ({
                value,
                label: value.replace(/_/g, " "),
              }))}
              selected={minConfidence}
              onToggle={(value) =>
                setMinConfidence((current) =>
                  current.includes(value)
                    ? current.filter((item) => item !== value)
                    : [...current, value],
                )
              }
            />
          </FilterField>

          <FilterField label="Dataset">
            <label className="flex items-center gap-2 text-xs">
              <Switch
                checked={includeMock}
                onCheckedChange={setIncludeMock}
                aria-label="Include synthetic development wells"
              />
              <span>
                Include synthetic wells
                <span className="block text-[12px] text-muted-foreground">
                  Off shows only wells loaded from real source adapters.
                </span>
              </span>
            </label>
          </FilterField>
        </div>
      )}

      {/* Map + panel */}
      <div className="relative flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {map.loading && !map.data && (
            <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/80">
              <Loading
                label="Loading well positions"
                detail="Fetching map features from the API. National coverage is a few thousand points."
              />
            </div>
          )}

          {map.error && (
            <div className="absolute inset-4 z-20">
              <ErrorState
                title="The map data could not be loaded"
                message={map.error}
                isOffline={map.error.includes("Could not reach")}
                hint={
                  map.error.includes("Could not reach")
                    ? "Start the backend with `uvicorn app.main:app --reload` in the backend directory, then reload."
                    : undefined
                }
                onRetry={map.refresh}
              />
            </div>
          )}

          <WellMap
            wells={map.data?.features ?? []}
            buildings={buildingFeatures}
            clusters={buildingFeatures}
            corridors={corridorFeatures}
            showBuildings={showBuildings}
            showClusters={showClusters}
            showCorridors={showCorridors}
            selectedWellId={selectedId ?? unadopted?.id ?? null}
            onSelectWell={selectFeature}
            className="h-full w-full"
          />

          {/* Layer toggles */}
          <div className="absolute right-2 top-2 z-10 flex flex-col items-end gap-1.5 sm:right-3 sm:top-3">
            <button
              type="button"
              onClick={() => setLayersOpen((value) => !value)}
              aria-expanded={layersOpen}
              aria-controls="map-layers"
              className="inline-flex min-h-10 items-center gap-2 rounded-md border border-border bg-card/95 px-3 text-sm font-medium shadow-sm backdrop-blur md:pointer-events-none md:min-h-0 md:border-0 md:bg-transparent md:px-0 md:shadow-none md:backdrop-blur-none"
            >
              <Layers className="h-4 w-4" aria-hidden />
              Layers
            </button>
            <div
              id="map-layers"
              className={cn(
                "w-60 rounded-md border border-border bg-card/95 p-3 shadow-sm backdrop-blur md:block md:w-56",
                layersOpen ? "block" : "hidden",
              )}
            >
            <div className="space-y-2.5">
              <LayerToggle
                icon={Building2}
                label="Heat demand clusters"
                checked={showClusters}
                onChange={setShowClusters}
              />
              <LayerToggle
                icon={Building2}
                label="Individual buildings"
                checked={showBuildings}
                onChange={setShowBuildings}
              />
              <LayerToggle
                icon={Route}
                label="Indicative corridors"
                checked={showCorridors}
                onChange={setShowCorridors}
              />
            </div>
            {showCorridors && corridors.data && (
              <p className="mt-2 text-xs leading-snug text-muted-foreground">
                {corridors.data.caveat}
              </p>
            )}
            </div>
          </div>

          {!includeMock && map.data && map.data.features.length > 0 && (
            <div className="absolute bottom-20 right-2 z-10 max-w-xs max-md:left-2 max-md:max-w-none md:bottom-3 md:right-3">
              <MockDataBanner
                isMock={map.data.features.some(
                  (feature) => feature.properties?.is_mock === true,
                )}
                what="wells"
                className="bg-card/92 backdrop-blur"
              />
            </div>
          )}
        </div>

        {/* Slide-over panel */}
        {unadopted && (
          <aside className="flex flex-col bg-card max-lg:absolute max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-30 max-lg:h-[72%] max-lg:rounded-t-2xl max-lg:border-t max-lg:shadow-[0_-12px_32px_-12px_rgb(0_0_0/0.35)] lg:w-[26rem] lg:shrink-0 lg:border-l xl:w-[30rem]">
            <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-border lg:hidden" aria-hidden />
            <AdoptWellPanel
              well={unadopted}
              onDismiss={() => setUnadopted(null)}
              onAdopted={(wellId) => {
                setUnadopted(null);
                setSelectedId(wellId);
                // The claimable flag is now stale, so the map has to be refetched
                // or the well will keep offering to be adopted.
                map.refresh();
              }}
            />
          </aside>
        )}

        {selectedId && (
          <aside className="flex flex-col bg-card max-lg:absolute max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-30 max-lg:h-[72%] max-lg:rounded-t-2xl max-lg:border-t max-lg:shadow-[0_-12px_32px_-12px_rgb(0_0_0/0.35)] lg:w-[26rem] lg:shrink-0 lg:border-l xl:w-[30rem]">
            <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-border lg:hidden" aria-hidden />
            {detail.loading && !detail.data && (
              <Loading label="Loading well record" className="flex-1" />
            )}

            {detail.error && (
              <div className="p-4">
                <ErrorState
                  message={detail.error}
                  onRetry={detail.refresh}
                  hint="If this well has not been added to one of your projects yet, it will not be visible to your organisation."
                />
              </div>
            )}

            {detail.data && (
              <WellPanel
                well={detail.data}
                analysis={analysis}
                isRunning={running}
                onClose={() => setSelectedId(null)}
                onRunAssessment={() => void runAssessment()}
              />
            )}

            {progress && (
              <div className="border-t p-4">
                <AssessmentProgress
                  stage={progress.stage}
                  completedStages={progress.completed_stages}
                  percentComplete={progress.percent_complete}
                  stageMessages={progress.stage_messages}
                  errorMessage={progress.error_message}
                />
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

function FilterField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="text-[12px] font-semibold text-muted-foreground">
        {label}
      </div>
      {children}
    </div>
  );
}

function ChipGroup({
  options,
  selected,
  onToggle,
}: {
  options: Array<{ value: string; label: string }>;
  selected: string[];
  onToggle: (value: string) => void;
}) {
  if (options.length === 0) {
    return (
      <p className="text-xs italic text-muted-foreground">
        Facets unavailable while offline
      </p>
    );
  }

  return (
    <div className="flex flex-wrap gap-1">
      {options.map((option) => {
        const active = selected.includes(option.value);
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onToggle(option.value)}
            className={cn(
              "rounded-full border px-2 py-0.5 text-[12px] transition-colors",
              active
                ? "border-primary bg-primary/10 font-medium text-primary"
                : "border-border text-muted-foreground hover:bg-muted",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function LayerToggle({
  icon: Icon,
  label,
  checked,
  onChange,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex min-h-8 items-center gap-2.5 text-sm">
      <Switch checked={checked} onCheckedChange={onChange} aria-label={label} />
      <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      <span className="flex-1">{label}</span>
    </label>
  );
}

/** Compact badge used in the map header for the spatial dialect. */
export function DialectBadge({ dialect }: { dialect: string }) {
  return (
    <Badge variant="muted" className="font-mono text-[11px]">
      {dialect}
    </Badge>
  );
}