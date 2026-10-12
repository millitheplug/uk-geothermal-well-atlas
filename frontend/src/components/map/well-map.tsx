"use client";

import * as React from "react";
import type { Point } from "geojson";
import type {
  GeoJSONSource,
  Map as MaplibreMap,
  MapLayerMouseEvent,
  Popup,
  StyleSpecification,
} from "maplibre-gl";

import {
  BUILDING_SOURCE_ID,
  CLUSTER_SOURCE_ID,
  CORRIDOR_SOURCE_ID,
  UK_BOUNDS,
  UK_CENTRE,
  circleOpacityExpression,
  circleRadiusExpression,
  createMap,
  emptyFeatureCollection,
  fallbackStyle,
  hasCustomBasemapStyle,
  maplibreModule,
  type MapFeature,
  scoreColourExpression,
  toFeatureCollection,
  wellPopupHtml,
  WELL_SOURCE_ID,
} from "@/lib/basemap";
import { cn } from "@/lib/utils";

export interface WellMapProps {
  wells?: MapFeature[] | null;
  buildings?: MapFeature[] | null;
  clusters?: MapFeature[] | null;
  corridors?: MapFeature[] | null;
  /** Called with the well's UUID when a marker is clicked. */
  onSelectWell?: (wellUuid: string, feature: MapFeature) => void;
  selectedWellId?: string | null;
  showBuildings?: boolean;
  showClusters?: boolean;
  showCorridors?: boolean;
  className?: string;
  /** Fly the camera here when this changes, e.g. after a search or a jump. */
  focus?: { lon: number; lat: number; zoom?: number } | null;
}

const EMPTY = emptyFeatureCollection();

/**
 * The MapLibre GL map.
 *
 * Two decisions worth stating, because both are visible on screen:
 *
 * - **Radius encodes uncertainty.** An unassessed well is drawn larger and
 *   grey. A well nobody has measured cannot be mistaken for one that scored
 *   badly, without anyone reading a legend.
 * - **No key is required.** The renderer is MapLibre GL JS (open source) and
 *   the default style is OpenFreeMap over OpenStreetMap data. If that style
 *   host cannot be reached the map swaps to OSM raster tiles through the same
 *   GL API and says so. Layer setup and event handling are identical in every
 *   case.
 */
export function WellMap({
  wells,
  buildings,
  clusters,
  corridors,
  onSelectWell,
  selectedWellId,
  showBuildings = false,
  showClusters = false,
  showCorridors = false,
  className,
  focus,
}: WellMapProps) {
  const container = React.useRef<HTMLDivElement | null>(null);
  const map = React.useRef<MaplibreMap | null>(null);
  const popup = React.useRef<Popup | null>(null);
  const [loaded, setLoaded] = React.useState(false);
  const [failed, setFailed] = React.useState<string | null>(null);
  const [usingRasterFallback, setUsingRasterFallback] = React.useState(false);

  // Held in a ref so the click handler always sees the latest callback without
  // rebuilding the layer (and losing map state) on every parent render.
  const selectRef = React.useRef(onSelectWell);
  selectRef.current = onSelectWell;

  // True once the raster fallback style has been applied, so a failing
  // fallback reports a failure instead of retrying forever.
  const usingRasterFallbackRef = React.useRef(false);

  React.useEffect(() => {
    const element = container.current;
    if (!element || map.current) return;

    let disposed = false;

    void (async () => {
      try {
        const maplibregl = await maplibreModule();
        const instance = await createMap(element);
        if (disposed) {
          instance.remove();
          return;
        }
        map.current = instance;
        mapRefHolder.current = instance;

        instance.on("error", (event) => {
          if (disposed) return;
          const message = (event as { error?: Error }).error?.message;

          // `Style.stylesheet` is typed non-nullable, but it is null until the
          // style document parses (`_load` assigns it). Widening to the truth
          // here makes it the one reliable way to tell "the basemap itself did
          // not load" from "a tile or glyph request failed".
          const stylesheet: StyleSpecification | null =
            instance.style.stylesheet;

          if (stylesheet !== null) {
            // Tile, glyph and sprite requests fail routinely at low zoom and
            // when a host is unreachable. The map still renders — background,
            // markers, selection and popups are all ours — so this is logged,
            // not shown. Surfacing it is what previously blanked the screen
            // behind an error card the user could not act on.
            if (message) console.warn("[map] non-fatal:", message);
            return;
          }

          if (!usingRasterFallbackRef.current) {
            // The configured style could not be loaded. Swap to the raster
            // style, which needs no host beyond openstreetmap.org, and say so
            // in the badge rather than failing the map.
            usingRasterFallbackRef.current = true;
            if (!disposed) setUsingRasterFallback(true);
            instance.setStyle(fallbackStyle());
            return;
          }

          // The fallback style failed too. This is a genuine failure: no
          // basemap at all, so say so and keep the tables available.
          if (message) setFailed(message);
        });

        instance.on("load", () => {
          if (disposed) return;

          popup.current = new maplibregl.Popup({
            closeButton: false,
            closeOnClick: false,
            offset: 12,
            maxWidth: "320px",
          });

          addSourceAndLayers(instance);
          wireEvents(instance, popup.current, selectRef);

          // Attribution is not a popup. It lives in the map's attribution
          // control, which the fallback style populates from the source's own
          // attribution string, and which a well click cannot dismiss.

          instance.fitBounds(UK_BOUNDS, { padding: 48 });
          setLoaded(true);
        });
      } catch (error) {
        if (!disposed) {
          setFailed(
            error instanceof Error ? error.message : "The map failed to load",
          );
        }
      }
    })();

    return () => {
      disposed = true;
      popup.current?.remove();
      popup.current = null;
      map.current?.remove();
      map.current = null;
      mapRefHolder.current = null;
    };
  }, []);

  useSourceData(WELL_SOURCE_ID, wells, loaded);
  useSourceData(BUILDING_SOURCE_ID, buildings, loaded, showBuildings);
  useSourceData(CLUSTER_SOURCE_ID, clusters, loaded, showClusters, "-fill");
  useSourceData(CORRIDOR_SOURCE_ID, corridors, loaded, showCorridors);

  // Ease to the selected well when selection changes from elsewhere, e.g. the
  // search results list.
  React.useEffect(() => {
    if (!loaded || !map.current || !selectedWellId) return;
    const feature = (wells ?? []).find(
      (candidate) => candidate.properties?.id === selectedWellId,
    );
    if (!feature) return;
    const [lon = 0, lat = 0] = (feature.geometry as Point).coordinates;
    map.current.easeTo({
      center: [lon, lat],
      zoom: Math.max(8, map.current.getZoom()),
      duration: 600,
    });
  }, [selectedWellId, wells, loaded]);

  React.useEffect(() => {
    if (!loaded || !map.current || !focus) return;
    map.current.flyTo({
      center: [focus.lon, focus.lat],
      zoom: focus.zoom ?? 9,
      duration: 900,
      essential: true,
    });
  }, [focus, loaded]);

  const resetView = React.useCallback(() => {
    map.current?.fitBounds(UK_BOUNDS, { padding: 48, duration: 500 });
  }, []);

  return (
    <div className={cn("relative overflow-hidden bg-muted", className)}>
      <div ref={container} className="h-full w-full" />

      {!loaded && !failed && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background/70">
          <p className="text-xs text-muted-foreground">Loading basemap…</p>
        </div>
      )}

      {failed && (
        <div className="absolute inset-0 flex items-center justify-center p-6">
          <div className="max-w-sm rounded-md border border-destructive/40 bg-card p-4 text-center shadow-lg">
            <p className="text-sm font-semibold text-destructive">
              The map could not be loaded
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {failed}. The underlying data is unaffected and remains available
              in the explorer and candidate tables.
            </p>
          </div>
        </div>
      )}

      <div className="absolute left-2 top-2 z-10 flex flex-col items-start gap-1.5">
        <button
          type="button"
          onClick={resetView}
          className="min-h-10 rounded-md border border-border bg-card/95 px-3 text-sm font-medium shadow-sm backdrop-blur hover:bg-card md:min-h-0 md:px-2 md:py-1 md:text-xs"
        >
          Reset to UK
        </button>
        <span
          className="hidden rounded border border-border bg-card/90 px-2 py-1 text-[12px] text-muted-foreground shadow-sm backdrop-blur md:inline-block"
          title={
            usingRasterFallback
              ? "The configured vector style could not be loaded, so the map fell back to OpenStreetMap raster tiles through the same GL renderer. Attribution is in the map control at the bottom right."
              : hasCustomBasemapStyle
                ? "NEXT_PUBLIC_MAP_STYLE is set, so this is that style rather than the built-in default. Attribution is in the map control at the bottom right."
                : "OpenFreeMap vector style over OpenStreetMap data — no access token and no vendor account. Attribution is in the map control at the bottom right."
          }
        >
          {usingRasterFallback
            ? "OpenStreetMap raster fallback"
            : hasCustomBasemapStyle
              ? "Custom vector style"
              : "OpenFreeMap vector basemap"}
        </span>
      </div>

      <MapLegend />
    </div>
  );
}

/** Ordered score ramp, plus the grey "not assessed" swatch. */
function MapLegend({ className }: { className?: string }) {
  const bands = [
    { label: "80–100", colour: "hsl(var(--score-100))" },
    { label: "60–80", colour: "hsl(var(--score-80))" },
    { label: "40–60", colour: "hsl(var(--score-60))" },
    { label: "20–40", colour: "hsl(var(--score-40))" },
    { label: "0–20", colour: "hsl(var(--score-20))" },
  ];

  return (
    <>
      {/* Phone: the whole ramp on one line, so it never fights the attribution. */}
      <div
        className={cn(
          "absolute bottom-12 left-2 z-10 flex items-center gap-2 rounded-md border border-border bg-card/95 px-2.5 py-1.5 text-[12px] text-muted-foreground shadow-sm backdrop-blur md:hidden",
          className,
        )}
        role="img"
        aria-label="Feasibility score legend: dark blue is low, green is high, grey is not assessed"
      >
        <span className="font-medium text-foreground">Score</span>
        <span className="tabular">0</span>
        <span className="flex overflow-hidden rounded-sm" aria-hidden>
          {[...bands].reverse().map((band) => (
            <span
              key={band.label}
              className="h-3 w-5"
              style={{ backgroundColor: band.colour }}
            />
          ))}
        </span>
        <span className="tabular">100</span>
        <span className="flex items-center gap-1">
          <span
            className="h-3 w-3 rounded-sm border border-dashed border-muted-foreground/60 bg-muted"
            aria-hidden
          />
          n/a
        </span>
      </div>

    <div
      className={cn(
        "absolute bottom-3 left-3 z-10 hidden rounded border border-border bg-card/92 p-2 shadow-sm backdrop-blur md:block",
        className,
      )}
    >
      <div className="text-[11px] font-semibold text-muted-foreground">
        Feasibility score
      </div>
      <div className="mt-1 space-y-0.5">
        {bands.map((band) => (
          <div key={band.label} className="flex items-center gap-1.5">
            <span
              className="h-2 w-4 rounded-sm"
              style={{ backgroundColor: band.colour }}
              aria-hidden
            />
            <span className="tabular text-[12px] text-muted-foreground">
              {band.label}
            </span>
          </div>
        ))}
        <div className="flex items-center gap-1.5">
          <span
            className="h-2 w-4 rounded-sm border border-dashed border-muted-foreground/60 bg-muted"
            aria-hidden
          />
          <span className="text-[12px] text-muted-foreground">Not assessed</span>
        </div>
      </div>
      <p className="mt-1.5 max-w-[9rem] text-[11px] leading-tight text-muted-foreground">
        Marker radius grows as evidence thins.
      </p>
    </div>
    </>
  );
}

/** Push a feature list into a named source and toggle its layer. */
function useSourceData(
  sourceId: string,
  features: MapFeature[] | null | undefined,
  loaded: boolean,
  visible = true,
  layerId = sourceId,
): void {
  React.useEffect(() => {
    const map = mapRefHolder.current;
    if (!loaded || !map) return;

    const source = map.getSource(sourceId) as GeoJSONSource | undefined;
    source?.setData(toFeatureCollection(features ?? []));

    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
    }
  }, [sourceId, layerId, features, visible, loaded]);
}

/**
 * Module-level handle to the live map.
 *
 * The data-pushing effect needs the instance but must not re-run the creation
 * effect, and threading it through `useState` would trigger a second render
 * every time the map was created. A ref-like module variable with an explicit
 * lifetime, set and cleared by the creation effect, keeps the dependency arrays
 * honest.
 */
const mapRefHolder: { current: MaplibreMap | null } = { current: null };

function addSourceAndLayers(map: MaplibreMap): void {
  map.addSource(WELL_SOURCE_ID, { type: "geojson", data: EMPTY });

  // A soft halo underneath the marker gives a 2,000-point national map enough
  // presence to be legible at zoom 5 without inflating the marker itself.
  map.addLayer({
    id: `${WELL_SOURCE_ID}-halo`,
    type: "circle",
    source: WELL_SOURCE_ID,
    paint: {
      "circle-radius": circleRadiusExpression(),
      "circle-color": scoreColourExpression(),
      "circle-opacity": 0.25,
      "circle-stroke-width": 0,
    },
  });

  map.addLayer({
    id: WELL_SOURCE_ID,
    type: "circle",
    source: WELL_SOURCE_ID,
    paint: {
      "circle-radius": circleRadiusExpression(),
      "circle-color": scoreColourExpression(),
      "circle-opacity": circleOpacityExpression(),
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1,
    },
  });

  map.addSource(BUILDING_SOURCE_ID, { type: "geojson", data: EMPTY });
  map.addLayer({
    id: BUILDING_SOURCE_ID,
    type: "circle",
    source: BUILDING_SOURCE_ID,
    layout: { visibility: "none" },
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 1.5, 12, 6],
      "circle-color": "#f97316",
      "circle-opacity": 0.5,
      "circle-stroke-width": 0,
    },
  });

  map.addSource(CLUSTER_SOURCE_ID, { type: "geojson", data: EMPTY });
  map.addLayer({
    id: `${CLUSTER_SOURCE_ID}-fill`,
    type: "circle",
    source: CLUSTER_SOURCE_ID,
    layout: { visibility: "none" },
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 8, 12, 26],
      "circle-color": "#f59e0b",
      "circle-opacity": 0.12,
      "circle-stroke-color": "#f59e0b",
      "circle-stroke-width": 1,
      "circle-stroke-opacity": 0.5,
    },
  });

  map.addSource(CORRIDOR_SOURCE_ID, { type: "geojson", data: EMPTY });
  map.addLayer({
    id: CORRIDOR_SOURCE_ID,
    type: "line",
    source: CORRIDOR_SOURCE_ID,
    layout: { visibility: "none", "line-cap": "round" },
    paint: {
      "line-color": "#0891b2",
      "line-width": ["interpolate", ["linear"], ["zoom"], 5, 1, 12, 3],
      "line-opacity": 0.7,
      // Dashed on purpose: a corridor is a straight-line indicative distance,
      // not a routed pipeline alignment, and must not be read as one.
      "line-dasharray": [3, 2],
    },
  });
}

function wireEvents(
  map: MaplibreMap,
  popup: Popup,
  selectRef: React.MutableRefObject<
    ((wellUuid: string, feature: MapFeature) => void) | undefined
  >,
): void {
  map.on("click", WELL_SOURCE_ID, (event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    if (!feature) return;

    const id = feature.properties?.id;
    if (typeof id !== "string") return;

    const point = feature.geometry as Point;
    popup
      .setLngLat([point.coordinates[0] ?? 0, point.coordinates[1] ?? 0])
      .setHTML(wellPopupHtml(feature))
      .addTo(map);

    selectRef.current?.(id, feature as MapFeature);
  });

  map.on("mouseenter", WELL_SOURCE_ID, () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", WELL_SOURCE_ID, () => {
    map.getCanvas().style.cursor = "";
  });
}