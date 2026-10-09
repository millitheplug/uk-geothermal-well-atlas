import { describe, expect, it } from "vitest";

import {
  UK_BOUNDS,
  UK_CENTRE,
  circleOpacityExpression,
  circleRadiusExpression,
  scoreColourExpression,
  wellPopupHtml,
} from "./basemap";

/**
 * The style spec is the authority on whether a paint expression is *valid*,
 * and validity is not a type-level concern: MapLibre parses these at runtime
 * and silently drops the layer if one fails. `case` requires at least three
 * arguments (condition, output, fallback), so an expression that only compiles
 * can still cost you every marker on the map.
 */
const spec = await import("@maplibre/maplibre-gl-style-spec");

const circleSpec = spec.v8.paint_circle;

const feature = (properties: Record<string, unknown>) => ({
  type: "Point" as const,
  properties,
  geometry: { type: "Point" as const, coordinates: [0, 0] as [number, number] },
});

const globals = { zoom: 6 };

function evaluate(
  expression: unknown,
  property: "circle-opacity" | "circle-color" | "circle-radius",
  properties: Record<string, unknown>,
) {
  const result = spec.createExpression(expression, circleSpec[property]);
  if (result.result !== "success") {
    throw new Error(
      `expression did not parse: ${result.value
        .map((error) => error.message)
        .join("; ")}`,
    );
  }
  return result.value.evaluate(globals, feature(properties));
}

function parseErrors(
  expression: unknown,
  property: "circle-opacity" | "circle-color" | "circle-radius",
): string[] {
  const result = spec.createExpression(expression, circleSpec[property]);
  return result.result === "success"
    ? []
    : result.value.map((error) => error.message);
}

describe("paint expressions parse against the style spec", () => {
  // Each of these failed to parse before the `case` expressions were given a
  // fallback branch. A parse failure here means MapLibre drops the layer, so
  // the map would load with no wells on it and nothing in the console to
  // explain why.
  it("circle-opacity parses", () => {
    expect(parseErrors(circleOpacityExpression(), "circle-opacity")).toEqual([]);
  });

  it("circle-color parses", () => {
    expect(parseErrors(scoreColourExpression(), "circle-color")).toEqual([]);
  });

  it("circle-radius parses", () => {
    expect(parseErrors(circleRadiusExpression(), "circle-radius")).toEqual([]);
  });
});

describe("circleOpacityExpression", () => {
  const opacity = (properties: Record<string, unknown>) =>
    evaluate(circleOpacityExpression(), "circle-opacity", properties) as number;

  it("draws well-evidenced markers at full opacity", () => {
    expect(opacity({ confidence: 0.8 })).toBe(1);
    expect(opacity({ confidence: 1 })).toBe(1);
  });

  it("softens markers the platform cannot vouch for", () => {
    expect(opacity({ confidence: 0.2 })).toBe(0.9);
    expect(opacity({ confidence: 0.44 })).toBe(0.9);
  });

  it("treats an absent confidence as unevidenced rather than as measured", () => {
    // `coalesce` sends null to 0, which lands in the soft branch. If this
    // inverted, an unassessed well would render as more solid than a measured
    // one — the exact failure this platform exists to avoid.
    expect(opacity({})).toBe(0.9);
    expect(opacity({ confidence: null })).toBe(0.9);
  });

  it("splits exactly at the 0.45 threshold", () => {
    expect(opacity({ confidence: 0.45 })).toBe(1);
  });
});

describe("scoreColourExpression", () => {
  const colour = (properties: Record<string, unknown>) =>
    evaluate(scoreColourExpression(), "circle-color", properties);

  const rgb = (value: unknown) => {
    const parsed = value as { r: number; g: number; b: number };
    return [parsed.r, parsed.g, parsed.b];
  };

  it("renders unassessed wells grey, never as a score band", () => {
    const unassessed = rgb(colour({ score: -1 }));
    expect(unassessed).toEqual(rgb(colour({ score: null })));
    // #94a3b8
    expect(unassessed).toEqual([148 / 255, 163 / 255, 184 / 255]);
  });

  it("keeps the ramp ordered so panning shows gradation", () => {
    const lightness = (score: number) => {
      const [r, g, b] = rgb(colour({ score }));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };

    const scores = [10, 50, 75, 95];
    const steps = scores.map(lightness);
    for (let i = 1; i < steps.length; i += 1) {
      expect(steps[i]).toBeGreaterThan(steps[i - 1] as number);
    }
  });

  it("gives scores in different bands different colours", () => {
    expect(rgb(colour({ score: 10 }))).not.toEqual(rgb(colour({ score: 95 })));
  });
});

describe("circleRadiusExpression", () => {
  const radius = (properties: Record<string, unknown>) =>
    evaluate(circleRadiusExpression(), "circle-radius", properties) as number;

  it("draws an unassessed well larger than an assessed one", () => {
    // Radius is the channel documented as carrying uncertainty, so an
    // unassessed well must be visually distinct without reading a legend.
    expect(radius({ score: -1 })).toBeGreaterThan(radius({ score: 50 }));
    expect(radius({ score: -1 })).toBeGreaterThan(radius({ score: 95 }));
  });
});

describe("UK framing", () => {
  it("uses [lng, lat] ordering, not [lat, lng]", () => {
    // Written the other way round the camera fits the Indian Ocean instead,
    // and no amount of correct well data fixes that.
    const [[west, south], [east, north]] = UK_BOUNDS;
    expect(west).toBeLessThan(east);
    expect(south).toBeLessThan(north);
    expect(west).toBeLessThan(0);
    expect(east).toBeGreaterThan(0);
    expect(south).toBeGreaterThan(49);
    expect(north).toBeLessThan(62);
  });

  it("centres within the bounds", () => {
    const [[west, south], [east, north]] = UK_BOUNDS;
    const [lng, lat] = UK_CENTRE;
    expect(lng).toBeGreaterThanOrEqual(west);
    expect(lng).toBeLessThanOrEqual(east);
    expect(lat).toBeGreaterThanOrEqual(south);
    expect(lat).toBeLessThanOrEqual(north);
  });
});

describe("wellPopupHtml", () => {
  it("escapes property values before interpolating them", () => {
    const html = wellPopupHtml({
      properties: { name: '<img src=x onerror="alert(1)">', well_id: "UK-1" },
    });
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  it("says 'No measurement' rather than showing a number it does not have", () => {
    const html = wellPopupHtml({
      properties: { temperature_c: null, score: null, depth_m: null },
    });
    expect(html).toContain("No measurement");
    expect(html).toContain("Not assessed");
    expect(html).toContain("Not recorded");
  });

  it("shows the epistemic status beside the temperature", () => {
    const html = wellPopupHtml({
      properties: { temperature_c: 88.4, temperature_status: "modelled" },
    });
    expect(html).toContain("88.4 °C");
    expect(html).toContain("modelled");
  });

  it("omits the priority row when there is no recommendation", () => {
    expect(wellPopupHtml({ properties: { recommendation: null } })).not.toContain(
      "Priority",
    );
    expect(
      wellPopupHtml({ properties: { recommendation: "monitor" } }),
    ).toContain("monitor");
  });
});
