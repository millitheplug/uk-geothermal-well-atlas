/**
 * Routes that render without a session.
 *
 * Both are authentication screens, and the second one is here for a reason
 * easy to lose. `AppChrome` wraps the root layout, so its guard sees every
 * page: a visitor who has not registered yet has no account and therefore no
 * session, and a sign-up route left off this list is bounced straight back to
 * sign-in by the very mechanism meant to protect the rest of the application.
 * The form would then be reachable only by people who already have a login.
 */

export const PUBLIC_AUTH_ROUTES = ["/sign-in", "/sign-up"] as const;

/** True when `pathname` is one of the screens a stranger may open. */
export function isPublicAuthRoute(pathname: string | null | undefined): boolean {
  return PUBLIC_AUTH_ROUTES.some((route) => pathname?.startsWith(route) ?? false);
}
