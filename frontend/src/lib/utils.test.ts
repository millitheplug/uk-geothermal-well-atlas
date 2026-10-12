import { describe, expect, it } from "vitest";

import { wellKey } from "./utils";

/**
 * Every well endpoint is keyed by the well's UUID. The publisher's id (for NSTA
 * wells, something like "LN/10- 4Z") is neither a UUID nor a usable URL
 * segment, so links and queries built from it fail on real data.
 */
describe("wellKey", () => {
  const uuid = "9b7f41e2-3c1a-4d5e-8f60-1a2b3c4d5e6f";

  it("prefers the UUID over a publisher id containing a slash and spaces", () => {
    expect(wellKey({ well_id: "LN/10- 4Z", well_uuid: uuid })).toBe(uuid);
  });

  it("falls back to the publisher id when an older backend sends no UUID", () => {
    expect(wellKey({ well_id: "UK-MOCK-WLN-002" })).toBe("UK-MOCK-WLN-002");
    expect(wellKey({ well_id: "UK-MOCK-WLN-002", well_uuid: null })).toBe(
      "UK-MOCK-WLN-002",
    );
  });

  it("never produces a path with a slash when a UUID is available", () => {
    expect(wellKey({ well_id: "L46/16- 31", well_uuid: uuid })).not.toContain("/");
  });
});
