/**
 * The application chrome.
 *
 * Lives in the root layout so the map, the tables and the dashboards all share
 * one navigation and one session gate. Two behaviours are worth calling out:
 *
 * - `/sign-in` renders bare, with no navigation. An unauthenticated user has no
 *   access to anything else anyway, and a nav rail full of dead links is
 *   noise.
 * - While the session is being resolved nothing is rendered but a boot screen.
 *   Rendering the shell first and then swapping in a signed-in user produces a
 *   visible flash and, worse, fires authenticated requests with no token.
 *
 * Layout: a rail from the `lg` breakpoint up; below it a slim top bar and a
 * bottom tab bar. The heights use `dvh` so a phone browser's collapsing
 * toolbar never hides the bottom of the page.
 */

"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { ChevronsUpDown, LogOut } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AppSidebar,
  BrandMark,
  MobileMenuSheet,
  MobileTabBar,
  NAV_ITEMS,
  SETTINGS_ITEM,
  SyntheticBadge,
  isActivePath,
} from "@/components/layout/app-shell";
import { useApp } from "@/components/providers/app-provider";
import { cn } from "@/lib/utils";

const BARE_ROUTES = ["/sign-in"];

export function AppChrome({ children }: { children: React.ReactNode }) {
  const { user, loading, isMock, health, signOut } = useApp();
  const pathname = usePathname();
  const router = useRouter();
  const [sheetOpen, setSheetOpen] = React.useState(false);

  const bare = BARE_ROUTES.some((route) => pathname?.startsWith(route));

  React.useEffect(() => {
    if (loading || user || bare) return;
    router.replace("/sign-in");
  }, [loading, user, bare, router]);

  if (bare) return <>{children}</>;

  if (loading || !user) return <BootScreen />;

  const handleSignOut = () => {
    signOut();
    router.replace("/sign-in");
  };

  const account = (
    <AccountMenu
      email={user.email}
      role={user.role}
      dialect={health?.spatial_dialect ?? null}
      environment={health?.environment ?? null}
      onSignOut={handleSignOut}
    />
  );

  // The tab bar highlights "More" when the current page lives in the sheet.
  const moreActive =
    !!pathname &&
    [...NAV_ITEMS.slice(4), SETTINGS_ITEM].some((item) =>
      isActivePath(pathname, item.href),
    );

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-background">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-accent-foreground"
      >
        Skip to content
      </a>

      <AppSidebar isMock={isMock} className="hidden lg:flex" footer={account} />

      <div className="flex min-w-0 flex-1 flex-col">
        <MobileTopBar isMock={isMock} className="lg:hidden" />
        <main id="main" className="flex min-h-0 min-w-0 flex-1 flex-col">
          {children}
        </main>
        <MobileTabBar
          className="lg:hidden"
          moreActive={moreActive}
          onMore={() => setSheetOpen(true)}
        />
      </div>

      <MobileMenuSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        footer={
          <SheetAccount
            email={user.email}
            role={user.role}
            environment={health?.environment ?? null}
            dialect={health?.spatial_dialect ?? null}
            onSignOut={handleSignOut}
          />
        }
      />
    </div>
  );
}

function initialsOf(email: string): string {
  const local = email.split("@")[0] ?? "";
  return (local.slice(0, 2) || "?").toUpperCase();
}

/** Account button and menu. Opens upward from the rail footer. */
function AccountMenu({
  email,
  role,
  dialect,
  environment,
  onSignOut,
}: {
  email: string;
  role: string;
  dialect: string | null;
  environment: string | null;
  onSignOut: () => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-rail-active/60 data-[state=open]:bg-rail-active">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-rail-active text-xs font-semibold text-white ring-1 ring-rail-border">
          {initialsOf(email)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-white">
            {email}
          </span>
          <span className="block truncate text-xs capitalize text-rail-muted">
            {role}
          </span>
        </span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-rail-muted" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-64">
        <DropdownMenuLabel className="truncate">{email}</DropdownMenuLabel>
        {(environment || dialect) && (
          <div className="space-y-0.5 px-2 pb-1.5 text-xs text-muted-foreground">
            {environment && <p>Environment: {environment}</p>}
            {dialect && (
              <p
                title="Spatial backend in use. PostGIS means earth-distance queries; haversine means a SQLite fallback with the same results to within rounding."
              >
                Spatial backend: <span className="font-mono">{dialect}</span>
              </p>
            )}
          </div>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onSignOut}>
          <LogOut aria-hidden />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Account block inside the phone "More" sheet. */
function SheetAccount({
  email,
  role,
  environment,
  dialect,
  onSignOut,
}: {
  email: string;
  role: string;
  environment: string | null;
  dialect: string | null;
  onSignOut: () => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
        {initialsOf(email)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{email}</p>
        <p className="truncate text-xs capitalize text-muted-foreground">
          {role}
          {environment ? ` · ${environment}` : ""}
          {dialect ? ` · ${dialect}` : ""}
        </p>
      </div>
      <button
        type="button"
        onClick={onSignOut}
        className="inline-flex h-10 shrink-0 items-center gap-2 rounded-md border border-input px-3 text-sm font-medium hover:bg-muted"
      >
        <LogOut className="h-4 w-4" aria-hidden />
        Sign out
      </button>
    </div>
  );
}

/** Slim top bar shown below the `lg` breakpoint. */
function MobileTopBar({
  isMock,
  className,
}: {
  isMock: boolean;
  className?: string;
}) {
  // On the phone the account lives in the "More" sheet, so the bar carries only
  // the brand and, when it applies, the synthetic-data marker.
  return (
    <div
      className={cn(
        "pt-safe flex shrink-0 items-center gap-3 border-b border-rail-border bg-rail px-4 py-2.5 text-rail-foreground",
        className,
      )}
    >
      <BrandMark className="h-7 w-7" />
      <span className="font-display text-xl">Well Atlas</span>
      {isMock && <SyntheticBadge className="ml-auto" />}
    </div>
  );
}

function BootScreen() {
  return (
    <div className="flex h-dvh w-full flex-col items-center justify-center gap-4 bg-rail text-rail-foreground">
      <BrandMark className="h-12 w-12" />
      <p className="font-display text-3xl">Well Atlas</p>
      <p className="text-sm text-rail-muted">Checking the session and backend…</p>
    </div>
  );
}

/** Full-height scroll container used by every page body. */
export function PageScroll({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-h-0 flex-1 overflow-auto", className)}>{children}</div>
  );
}
