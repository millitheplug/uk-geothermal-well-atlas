/**
 * Shell components: the navigation rail, the phone tab bar, the page header and
 * the page frame.
 *
 * Two layouts share one list of destinations. From the `lg` breakpoint up there
 * is a fixed rail with the destinations grouped by what the user is doing
 * (explore, analyse, manage). Below it the rail is replaced by a bottom tab bar
 * holding the four most-used pages and a "More" sheet for the rest, because a
 * hidden rail with nothing in its place leaves a phone user with no way to move
 * between pages.
 *
 * One element is non-negotiable and survives every layout: the synthetic-data
 * marker. A reviewer scrolling through nine dashboards should never have to
 * remember whether the numbers are real.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  AlertTriangle,
  BarChart3,
  Boxes,
  Droplets,
  FileText,
  FolderKanban,
  Gauge,
  LayoutDashboard,
  ListFilter,
  Map as MapIcon,
  MoreHorizontal,
  Settings,
  Thermometer,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";

export type NavGroup = "Explore" | "Analyse" | "Manage";

export interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
  group: NavGroup;
  /** Shown on the phone tab bar, where the full label does not fit. */
  tabLabel?: string;
}

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/",
    label: "National map",
    tabLabel: "Map",
    icon: MapIcon,
    group: "Explore",
    description: "Full-screen UK map, wells coloured by feasibility score",
  },
  {
    href: "/dashboard",
    label: "Dashboard",
    tabLabel: "Dashboard",
    icon: LayoutDashboard,
    group: "Explore",
    description: "National headline figures and score distribution",
  },
  {
    href: "/candidates",
    label: "Candidates",
    tabLabel: "Candidates",
    icon: ListFilter,
    group: "Explore",
    description: "Ranked candidate table across every well",
  },
  {
    href: "/explorer",
    label: "Well explorer",
    tabLabel: "Wells",
    icon: Boxes,
    group: "Explore",
    description: "Search and filter the full well inventory",
  },
  {
    href: "/thermal",
    label: "Thermal analysis",
    icon: Thermometer,
    group: "Analyse",
    description: "Temperature records and output estimation",
  },
  {
    href: "/heat-demand",
    label: "Heat demand",
    icon: Droplets,
    group: "Analyse",
    description: "Building demand, clusters and well-to-demand matching",
  },
  {
    href: "/financials",
    label: "Financials",
    icon: BarChart3,
    group: "Analyse",
    description: "CAPEX, OPEX, LCOH, NPV, IRR and scenario comparison",
  },
  {
    href: "/risk",
    label: "Risk register",
    icon: Gauge,
    group: "Analyse",
    description: "Risk exposure by category with uncertainty weighting",
  },
  {
    href: "/pipeline",
    label: "Projects",
    icon: FolderKanban,
    group: "Manage",
    description: "Project pipeline and stage tracking",
  },
  {
    href: "/data",
    label: "Data sources",
    icon: FileText,
    group: "Manage",
    description: "Datasets, adapters, provenance and evidence quality",
  },
];

export const SETTINGS_ITEM: NavItem = {
  href: "/settings",
  label: "Settings",
  icon: Settings,
  group: "Manage",
  description: "Interface and platform settings",
};

const GROUPS: NavGroup[] = ["Explore", "Analyse", "Manage"];

/** The four destinations given a permanent place on the phone tab bar. */
const TAB_ITEMS = NAV_ITEMS.slice(0, 4);

export function isActivePath(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

/**
 * The mark: a borehole with depth ticks, ending in a ring. The bore is the
 * subject of the whole product, so the mark is the bore.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 28 28"
      className={cn("h-8 w-8 shrink-0", className)}
      aria-hidden
    >
      <rect width="28" height="28" rx="6" className="fill-accent" />
      <g
        className="stroke-accent-foreground"
        fill="none"
        strokeWidth="2.4"
        strokeLinecap="round"
      >
        <path d="M14 5v9.5" />
        <circle cx="14" cy="18.6" r="4" />
        <path d="M6.5 8.5h3M6.5 12h3" strokeWidth="2" />
      </g>
    </svg>
  );
}

/** Small solid marker for synthetic data. Always capitalised: it must not be missed. */
export function SyntheticBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm bg-destructive px-1.5 py-0.5 text-[11px] font-bold uppercase leading-none tracking-wide text-destructive-foreground",
        className,
      )}
    >
      Synthetic data
    </span>
  );
}

/** Left navigation rail, shown from the `lg` breakpoint up. */
export function AppSidebar({
  isMock,
  className,
  footer,
}: {
  isMock: boolean;
  className?: string;
  /** Account area, supplied by the chrome so the shell stays free of session logic. */
  footer?: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <nav
      className={cn(
        "w-60 shrink-0 flex-col border-r border-rail-border bg-rail text-rail-foreground",
        className,
      )}
      aria-label="Primary"
    >
      <Link
        href="/"
        className="flex items-center gap-3 px-5 pb-5 pt-6 focus-visible:outline-offset-[-2px]"
      >
        <BrandMark />
        <span className="min-w-0">
          <span className="font-display block truncate text-[1.375rem]">
            Well Atlas
          </span>
          <span className="block truncate text-xs text-rail-muted">
            UK onshore screening
          </span>
        </span>
      </Link>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-3 pb-4 pt-1">
        {GROUPS.map((group) => (
          <div key={group}>
            <p className="px-3 pb-1.5 text-xs font-medium text-rail-muted">
              {group}
            </p>
            <ul className="space-y-0.5">
              {NAV_ITEMS.filter((item) => item.group === group).map((item) => {
                const active = isActivePath(pathname, item.href);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      title={item.description}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                        active
                          ? "bg-rail-active font-medium text-white before:absolute before:inset-y-1.5 before:-left-3 before:w-[3px] before:rounded-r before:bg-accent"
                          : "text-rail-foreground/75 hover:bg-rail-active/60 hover:text-white",
                      )}
                    >
                      <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
                      <span className="truncate">{item.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <div className="space-y-2 border-t border-rail-border p-3">
        {isMock && (
          <div
            role="note"
            className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/15 px-2.5 py-2"
          >
            <AlertTriangle
              className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-300"
              aria-hidden
            />
            <span className="text-xs font-medium leading-snug text-red-200">
              Synthetic data is loaded
            </span>
          </div>
        )}
        <Link
          href={SETTINGS_ITEM.href}
          aria-current={
            isActivePath(pathname, SETTINGS_ITEM.href) ? "page" : undefined
          }
          className={cn(
            "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
            isActivePath(pathname, SETTINGS_ITEM.href)
              ? "bg-rail-active font-medium text-white"
              : "text-rail-foreground/75 hover:bg-rail-active/60 hover:text-white",
          )}
        >
          <Settings className="h-[18px] w-[18px]" aria-hidden />
          Settings
        </Link>
        {footer}
      </div>
    </nav>
  );
}

/**
 * Bottom tab bar for phones and tablets.
 *
 * `onMore` opens the sheet holding everything that does not fit. The bar is a
 * flex child, not `position: fixed`, so the page area above it is always
 * exactly the space that remains and nothing scrolls underneath it.
 */
export function MobileTabBar({
  onMore,
  moreActive,
  className,
}: {
  onMore: () => void;
  moreActive: boolean;
  className?: string;
}) {
  const pathname = usePathname();

  const tabClass = (active: boolean) =>
    cn(
      "relative flex min-h-[3.5rem] flex-col items-center justify-center gap-1 px-1 text-[11px] font-medium transition-colors",
      active
        ? "text-foreground before:absolute before:inset-x-3 before:top-0 before:h-[3px] before:rounded-b before:bg-accent"
        : "text-muted-foreground active:bg-muted",
    );

  return (
    <nav
      aria-label="Primary"
      className={cn("pb-safe shrink-0 border-t bg-card", className)}
    >
      <ul className="grid grid-cols-5">
        {TAB_ITEMS.map((item) => {
          const active = isActivePath(pathname, item.href);
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={tabClass(active)}
              >
                <Icon className="h-5 w-5" aria-hidden />
                <span className="max-w-full truncate">
                  {item.tabLabel ?? item.label}
                </span>
              </Link>
            </li>
          );
        })}
        <li>
          <button
            type="button"
            onClick={onMore}
            aria-haspopup="dialog"
            className={cn(tabClass(moreActive), "w-full")}
          >
            <MoreHorizontal className="h-5 w-5" aria-hidden />
            <span>More</span>
          </button>
        </li>
      </ul>
    </nav>
  );
}

/** Bottom sheet listing every destination, with the account area beneath. */
export function MobileMenuSheet({
  open,
  onOpenChange,
  footer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  footer?: React.ReactNode;
}) {
  const pathname = usePathname();

  // Navigating from inside the sheet should dismiss it.
  React.useEffect(() => {
    onOpenChange(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-rail/60 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="pb-safe fixed inset-x-0 bottom-0 z-50 max-h-[88dvh] overflow-y-auto rounded-t-2xl border-t bg-card shadow-2xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom"
        >
          <div className="sticky top-0 z-10 flex items-center justify-between bg-card px-5 pb-2 pt-4">
            <DialogPrimitive.Title className="font-display text-2xl">
              All sections
            </DialogPrimitive.Title>
            <DialogPrimitive.Close
              className="-mr-2 flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
              aria-label="Close menu"
            >
              <X className="h-5 w-5" aria-hidden />
            </DialogPrimitive.Close>
          </div>

          <div className="space-y-5 px-3 pb-4 pt-1">
            {GROUPS.map((group) => (
              <div key={group}>
                <p className="px-3 pb-1 text-xs font-medium text-muted-foreground">
                  {group}
                </p>
                <ul>
                  {[...NAV_ITEMS, SETTINGS_ITEM]
                    .filter((item) => item.group === group)
                    .map((item) => {
                      const active = isActivePath(pathname, item.href);
                      const Icon = item.icon;
                      return (
                        <li key={item.href}>
                          <Link
                            href={item.href}
                            aria-current={active ? "page" : undefined}
                            className={cn(
                              "flex min-h-12 items-center gap-3.5 rounded-md px-3 text-base",
                              active
                                ? "bg-muted font-medium text-foreground"
                                : "text-foreground/85 active:bg-muted",
                            )}
                          >
                            <Icon
                              className={cn(
                                "h-5 w-5 shrink-0",
                                active
                                  ? "text-foreground"
                                  : "text-muted-foreground",
                              )}
                              aria-hidden
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block">{item.label}</span>
                              <span className="block truncate text-xs font-normal text-muted-foreground">
                                {item.description}
                              </span>
                            </span>
                          </Link>
                        </li>
                      );
                    })}
                </ul>
              </div>
            ))}
          </div>

          {footer && <div className="border-t px-5 py-4">{footer}</div>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/**
 * Page title block with optional actions and a second row for page-level
 * controls. The title is the one place the condensed display face is used at
 * size, so every page opens the same way.
 */
export function AppHeader({
  title,
  subtitle,
  actions,
  isMock,
  className,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  isMock?: boolean;
  className?: string;
  /** Optional second row for page-level controls. */
  children?: React.ReactNode;
}) {
  return (
    <header
      className={cn(
        "border-b bg-background px-4 pb-4 pt-5 sm:px-6 lg:px-8 lg:pb-5 lg:pt-7",
        className,
      )}
    >
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 max-w-3xl">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <h1 className="font-display text-[1.875rem] sm:text-[2.5rem]">
              {title}
            </h1>
            {isMock && <SyntheticBadge />}
          </div>
          {subtitle && (
            <p className="voice-note mt-2 text-[0.9375rem] text-muted-foreground">
              {subtitle}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        )}
      </div>
      {children && <div className="mt-4 w-full">{children}</div>}
    </header>
  );
}

/** Page frame: fills the viewport, header scrolls away, content scrolls. */
export function PageFrame({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-h-0 flex-1 overflow-auto", className)}>
      {children}
    </div>
  );
}

/** Consistent page padding. Left-aligned so it lines up with the header. */
export function PageBody({
  children,
  wide = false,
  className,
}: {
  children: React.ReactNode;
  wide?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "px-4 py-5 sm:px-6 sm:py-6 lg:px-8",
        wide ? "max-w-none" : "max-w-[88rem]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Two-column dashboard grid that collapses on narrow viewports. */
export function DashboardGrid({
  children,
  className,
  cols = 2,
}: {
  children: React.ReactNode;
  className?: string;
  cols?: 2 | 3;
}) {
  return (
    <div
      className={cn(
        "grid gap-4",
        cols === 3
          ? "grid-cols-1 md:grid-cols-2 xl:grid-cols-3"
          : "grid-cols-1 lg:grid-cols-2",
        className,
      )}
    >
      {children}
    </div>
  );
}
