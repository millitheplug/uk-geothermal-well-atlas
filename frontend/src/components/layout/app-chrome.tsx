/**
 * The application chrome.
 *
 * Lives in the root layout so the map, the tables and the dashboards all share
 * one sidebar and one session gate. Two behaviours are worth calling out:
 *
 * - `/sign-in` renders bare, with no sidebar. An unauthenticated user has no
 *   access to anything else anyway, and a nav rail full of dead links is
 *   noise.
 * - While the session is being resolved nothing is rendered but a boot screen.
 *   Rendering the shell first and then swapping in a signed-in user produces a
 *   visible flash and, worse, fires authenticated requests with no token.
 */

"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { LogOut, Thermometer } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AppSidebar } from "@/components/layout/app-shell";
import { useApp } from "@/components/providers/app-provider";
import { cn } from "@/lib/utils";

const BARE_ROUTES = ["/sign-in"];

export function AppChrome({ children }: { children: React.ReactNode }) {
  const { user, loading, isMock, health, signOut } = useApp();
  const pathname = usePathname();
  const router = useRouter();

  const bare = BARE_ROUTES.some((route) => pathname?.startsWith(route));

  React.useEffect(() => {
    if (loading || user || bare) return;
    router.replace("/sign-in");
  }, [loading, user, bare, router]);

  if (bare) return <>{children}</>;

  if (loading || !user) return <BootScreen />;

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      <AppSidebar isMock={isMock} className="hidden md:flex" />
      <div className="flex min-w-0 flex-1 flex-col">
        <SessionBar
          email={user.email}
          role={user.role}
          isMock={isMock}
          dialect={health?.spatial_dialect ?? null}
          environment={health?.environment ?? null}
          onSignOut={() => {
            signOut();
            router.replace("/sign-in");
          }}
        />
        {children}
      </div>
    </div>
  );
}

/** Thin top strip: who you are, which backend you are on, sign out. */
function SessionBar({
  email,
  role,
  isMock,
  dialect,
  environment,
  onSignOut,
}: {
  email: string;
  role: string;
  isMock: boolean;
  dialect: string | null;
  environment: string | null;
  onSignOut: () => void;
}) {
  return (
    <div className="flex shrink-0 items-center justify-between gap-3 border-b bg-card/70 px-3 py-1.5 text-[11px]">
      <div className="flex min-w-0 items-center gap-2">
        <Thermometer className="h-3.5 w-3.5 text-primary md:hidden" aria-hidden />
        <span className="truncate text-muted-foreground">{email}</span>
        <span className="rounded bg-muted px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider">
          {role}
        </span>
        {isMock && (
          <span className="rounded bg-destructive px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-destructive-foreground">
            Synthetic data
          </span>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2 text-[10px] text-muted-foreground">
        {environment && <span className="hidden sm:inline">{environment}</span>}
        {dialect && (
          <span
            className="hidden rounded border border-border px-1.5 py-0.5 font-mono sm:inline"
            title="Spatial backend in use. PostGIS means earth-distance queries; haversine means a SQLite fallback with the same results to within rounding."
          >
            {dialect}
          </span>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger className="rounded px-1.5 py-0.5 text-[10px] hover:bg-muted">
            Account
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{email}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onSignOut}>
              <LogOut aria-hidden />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

function BootScreen() {
  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-3 bg-background">
      <div className="flex h-10 w-10 items-center justify-center rounded bg-primary text-primary-foreground">
        <Thermometer className="h-5 w-5" aria-hidden />
      </div>
      <p className="text-sm font-medium">UK Geothermal Well Atlas</p>
      <p className="text-xs text-muted-foreground">
        Checking the session and backend…
      </p>
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