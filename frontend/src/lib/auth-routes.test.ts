import { describe, expect, it } from "vitest";

import { isPublicAuthRoute, PUBLIC_AUTH_ROUTES } from "./auth-routes";

/**
 * The root layout's guard decides per pathname whether to show the shell or
 * bounce the visitor to sign-in. Getting that list wrong does not fail the
 * build - it just makes a route silently unreachable, which is how the sign-up
 * screen was once bounced back for everyone without an account.
 */
describe("public auth routes", () => {
  it("lists both screens a visitor may open without an account", () => {
    expect(PUBLIC_AUTH_ROUTES).toContain("/sign-in");
    expect(PUBLIC_AUTH_ROUTES).toContain("/sign-up");
  });

  it("does not bounce the sign-up screen back to sign-in", () => {
    // A stranger has no session, so the guard would otherwise redirect them
    // the moment they arrive and the form could never be reached.
    expect(isPublicAuthRoute("/sign-up")).toBe(true);
    expect(isPublicAuthRoute("/sign-in")).toBe(true);
  });

  it("keeps the signed-in application behind the guard", () => {
    for (const path of [
      "/dashboard",
      "/wells/9b7f41e2-3c1a-4d5e-8f60-1a2b3c4d5e6f",
      "/settings",
      "/candidates",
    ]) {
      expect(isPublicAuthRoute(path)).toBe(false);
    }
  });

  it("treats an unmounted or unknown path as guarded", () => {
    expect(isPublicAuthRoute(null)).toBe(false);
    expect(isPublicAuthRoute(undefined)).toBe(false);
    expect(isPublicAuthRoute("")).toBe(false);
  });
});
