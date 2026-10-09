/**
 * MapLibre GL JS integration with open-source basemaps.
 *
 * MapLibre GL JS is the BSD-3-Clause open-source fork of Mapbox GL JS. It
 * needs no access token and no vendor account: the renderer makes no
 * authenticated calls to anyone, which is what makes the map usable in an
 * evaluation environment where no credentials have been provisioned.
 *
 * The default basemap is OpenFreeMap's "liberty" style over OpenStreetMap
 * data, served with permissive CORS. If that host cannot be reached the map
 * falls back to an OSM raster style rendered through the same GL API, and the
 * UI says which of the two is on screen — the difference is never hidden.
 *
 * `NEXT_PUBLIC_MAP_STYLE` overrides the default with any style URL MapLibre
 * can load over HTTPS. `mapbox://…` values are rejected outright: that scheme
 * requires Mapbox authentication, which this platform does not use, and
 * MapLibre cannot resolve it. Layers, event handling and popups are identical
 * in every case, so switching basemap is purely a style choice and not a
 * second code path that can drift.
 */

import type {
  ExpressionSpecification,
  Map as MaplibreMap,
  StyleSpecification,
} from "maplibre-gl";
import type {
  Feature,
  FeatureCollection,
  GeoJsonProperties,
  Geometry,
} from "geojson";

/**
 * Any GeoJSON feature the platform puts on the map.
 *
 * A single permissive type at the boundary, with the specific geometry checked
 * at the call site where it is known. The renderer's `setData` accepts any
 * geometry, so a stricter union here would only push casts into the layer
 * setup.
 */
export type MapFeature = Feature<Geometry, GeoJsonProperties>;

/** Default style: OpenFreeMap "liberty" over OpenStreetMap data. No key required. */
export const OPENFREEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

const configuredStyle = (process.env.NEXT_PUBLIC_MAP_STYLE ?? "").trim();

/**
 * The operator's style only counts if MapLibre can actually load it.
 *
 * `mapbox://…` needs a Mapbox token and MapLibre has no code path for that
 * scheme, so accepting it here would produce a map that silently never loads.
 */
export const hasCustomBasemapStyle =
  configuredStyle.length > 0 && !configuredStyle.startsWith("mapbox://");

/** Style URL handed to the renderer: the operator's choice, else the open default. */
export const BASEMAP_STYLE = hasCustomBasemapStyle
  ? configuredStyle
  : OPENFREEMAP_STYLE_URL;

/**
 * Bounding box for Great Britain, the platform's operational area.
 *
 * GeoJSON and this renderer both take `[lng, lat]`, so the box runs
 * west→east, south→north. Written the other way round the camera fits a
 * patch of the Indian Ocean instead, and no amount of correct data fixes
 * that.
 */
export const UK_BOUNDS: [[number, number], [number, number]] = [
  [-8.5, 49.5],
  [2.5, 61.5],
];

/** `[lng, lat]`, matching `UK_BOUNDS`. */
export const UK_CENTRE: [number, number] = [-2.5, 54.5];

/**
 * Raster style over OpenStreetMap, used when the configured style is
 * unreachable.
 *
 * Attribution is mandatory under the OSM tile usage policy, so it is set here
 * and not left to the map component.
 */
export function fallbackStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    },
    layers: [
      {
        id: "background",
        type: "background",
        paint: { "background-color": "#f8fafc" },
      },
      {
        id: "osm",
        type: "raster",
        source: "osm",
        paint: { "raster-opacity": 0.85 },
      },
    ],
  };
}

/**
 * The maplibre-gl module, loaded once and cached.
 *
 * Consumers that need `Popup` await this rather than importing maplibre-gl
 * directly, so there is exactly one dynamic import of the library in the
 * codebase — the GL renderer never lands in the initial page bundle.
 *
 * The package ships a UMD bundle, so depending on the bundler's CommonJS
 * interop the exports arrive either on the namespace itself or on
 * `.default`. Both are accepted here, once, rather than guessed at by every
 * caller.
 */
type MaplibreModule = typeof import("maplibre-gl");

let cachedModule: MaplibreModule | null = null;

export async function maplibreModule(): Promise<MaplibreModule> {
  if (!cachedModule) {
    const mod = (await import("maplibre-gl")) as MaplibreModule & {
      default?: MaplibreModule;
    };
    cachedModule = mod.default ?? mod;
  }
  return cachedModule;
}

export async function createMap(
  container: HTMLElement,
  options: { interactive?: boolean } = {},
): Promise<MaplibreMap> {
  const maplibregl = await maplibreModule();

  const map = new maplibregl.Map({
    container,
    style: BASEMAP_STYLE,
    center: UK_CENTRE,
    zoom: 5.2,
    minZoom: 4,
    maxZoom: 16,
    bounds: UK_BOUNDS,
    fitBoundsOptions: { padding: 48 },
    interactive: options.interactive ?? true,
    // Always expanded, and deliberately so: each source carries its own
    // attribution string, and a licence condition hidden behind a collapsed
    // toggle is not a licence condition anyone should rely on. The extra
    // credits name the renderer and the data, both of which are open source.
    attributionControl: {
      compact: false,
      customAttribution: [
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        '<a href="https://maplibre.org/" target="_blank">MapLibre</a>',
      ],
    },
  });

  return map;
}

/**
 * Colour expression for well markers, by feasibility score.
 *
 * An ordered, colourblind-safe ramp. Wells with no score render grey rather
 * than as zero: they are unassessed, and colouring them the same as a genuinely
 * poor well would misrepresent both.
 */
export function scoreColourExpression(): ExpressionSpecification {
  return [
    "case",
    ["==", ["coalesce", ["get", "score"], -1], -1],
    "#94a3b8",
    ["<", ["get", "score"], 20],
    "#4338a8",
    ["<", ["get", "score"], 40],
    "#3b4fa8",
    ["<", ["get", "score"], 60],
    "#2a7f9e",
    ["<", ["get", "score"], 80],
    "#2a9d8f",
    "#66bb6a",
  ];
}

export function circleRadiusExpression(): ExpressionSpecification {
  // Radius encodes uncertainty as well as score: a well nobody has measured is
  // drawn larger and hollow, so "promising but unevidenced" is visible on the
  // map without reading a single label.
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    4,
    ["case", ["==", ["coalesce", ["get", "score"], -1], -1], 5, 4.5],
    8,
    ["case", ["==", ["coalesce", ["get", "score"], -1], -1], 8, 7],
    12,
    ["case", ["==", ["coalesce", ["get", "score"], -1], -1], 13, 11],
  ];
}

export function circleOpacityExpression(): ExpressionSpecification {
  // Confidence is 0–1 (`fmtConfidence` scales it by 100), so 0.45 splits the
  // map into markers the platform can vouch for and markers it cannot. The
  // latter are drawn a touch soft rather than at full solidity.
  //
  // `coalesce` sends a missing confidence to 0, which takes the same soft
  // branch: an unassessed well must not default to looking *better* evidenced
  // than a measured one. The else branch is 1, the paint property's own
  // default, so the only value chosen here is the 0.9 above.
  return [
    "case",
    ["<", ["coalesce", ["get", "confidence"], 0], 0.45],
    0.9,
    1,
  ];
}

export const WELL_SOURCE_ID = "wells";
export const BUILDING_SOURCE_ID = "buildings";
export const CLUSTER_SOURCE_ID = "heat-clusters";
export const CORRIDOR_SOURCE_ID = "corridors";
export const DENSITY_SOURCE_ID = "density";

export function emptyFeatureCollection(): FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

export function toFeatureCollection(features: MapFeature[]): FeatureCollection {
  return { type: "FeatureCollection", features };
}

/**
 * Popup content for a well marker.
 *
 * Every line carries its provenance label. A popup that showed only "88 °C"
 * would invite exactly the assumption this platform exists to prevent.
 */
export function wellPopupHtml(feature: {
  properties?: GeoJsonProperties | null;
}): string {
  const p = feature.properties ?? {};

  const escape = (value: unknown): string =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (char) =>
        (
          {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
          } as Record<string, string>
        )[char] ?? char,
    );

  const temperature =
    p.temperature_c === null || p.temperature_c === undefined
      ? `<span style="color:#64748b">No measurement</span>`
      : `${Number(p.temperature_c).toFixed(1)} °C <span style="opacity:.6;font-size:10px">${escape(p.temperature_status)}</span>`;

  const depth =
    p.depth_m === null || p.depth_m === undefined
      ? "Not recorded"
      : `${Number(p.depth_m).toFixed(0)} m`;

  const score =
    p.score === null || p.score === undefined
      ? "Not assessed"
      : `${Number(p.score).toFixed(0)}/100`;

  const recommendation = p.recommendation ? escape(p.recommendation) : "";

  return `
    <div style="min-width:200px;font-family:system-ui,sans-serif">
      <div style="font-weight:600;margin-bottom:4px">${escape(p.name)}</div>
      <div style="font-size:11px;opacity:.7;margin-bottom:6px">${escape(p.well_id)} · ${escape(p.status)}</div>
      <table style="font-size:11px;border-spacing:0">
        <tr><td style="padding-right:8px;opacity:.7">Score</td><td style="text-align:right;font-weight:600">${score}</td></tr>
        <tr><td style="padding-right:8px;opacity:.7">Temperature</td><td style="text-align:right">${temperature}</td></tr>
        <tr><td style="padding-right:8px;opacity:.7">Depth</td><td style="text-align:right">${depth}</td></tr>
        ${p.recommendation ? `<tr><td style="padding-right:8px;opacity:.7">Priority</td><td style="text-align:right">${recommendation}</td></tr>` : ""}
      </table>
    </div>
  `;
}
