/**
 * Shell components: the sidebar rail, the top bar and the page frame.
 *
 * The reference design is a dense, dashboard-first workspace. The layout keeps
 * that density but adds one non-negotiable element: the mock-data indicator in
 * the top bar, which is visible on every screen. A reviewer scrolling through
 * nine dashboards should never have to remember whether the numbers are real.
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
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
  Settings,
  Thermometer,
} from "lucide-react";

import { cn } from "@/lib/utils";

export interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/",
    label: "National map",
    icon: MapIcon,
    description: "Full-screen UK map, wells coloured by feasibility score",
  },
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    description: "National headline figures and score distribution",
  },
  {
    href: "/candidates",
    label: "Candidates",
    icon: ListFilter,
    description: "Ranked candidate table across every well",
  },
  {
    href: "/explorer",
    label: "Well explorer",
    icon: Boxes,
    description: "Search and filter the full well inventory",
  },
  {
    href: "/thermal",
    label: "Thermal analysis",
    icon: Thermometer,
    description: "Temperature records and output estimation",
  },
  {
    href: "/heat-demand",
    label: "Heat demand",
    icon: Droplets,
    description: "Building demand, clusters and well-to-demand matching",
  },
  {
    href: "/financials",
    label: "Financials",
    icon: BarChart3,
    description: "CAPEX, OPEX, LCOH, NPV, IRR and scenario comparison",
  },
  {
    href: "/risk",
    label: "Risk register",
    icon: Gauge,
    description: "Risk exposure by category with uncertainty weighting",
  },
  {
    href: "/pipeline",
    label: "Projects",
    icon: FolderKanban,
    description: "Project pipeline and stage tracking",
  },
  {
    href: "/data",
    label: "Data sources",
    icon: FileText,
    description: "Datasets, adapters, provenance and evidence quality",
  },
];

/** Left navigation rail. Collapses to icons on narrow viewports. */
export function AppSidebar({
  isMock,
  className,
}: {
  isMock: boolean;
  className?: string;
}) {
  const pathname = usePathname();

  return (
    <nav
      className={cn(
        "flex shrink-0 flex-col gap-1 border-r bg-card/60 p-2 lg:w-56",
        className,
      )}
      aria-label="Primary"
    >
      <Link
        href="/"
        className="mb-2 flex items-center gap-2.5 rounded-md px-2 py-2"
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-primary text-primary-foreground">
          <Thermometer className="h-4 w-4" aria-hidden />
        </div>
        <div className="min-w-0">
          <div className="truncate text-xs font-semibold leading-tight">
            Geothermal Well Atlas
          </div>
          <div className="truncate text-[10px] text-muted-foreground">
            UK onshore screening
          </div>
        </div>
      </Link>

      {NAV_ITEMS.map((item) => {
        const isActive =
          item.href === "/"
            ? pathname === "/"
            : pathname.startsWith(item.href);
        const Icon = item.icon;

        return (
          <Link
            key={item.href}
            href={item.href}
            title={item.description}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-xs transition-colors",
              isActive
                ? "bg-primary/10 font-medium text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            <span className="truncate">{item.label}</span>
          </Link>
        );
      })}

      <div className="mt-auto space-y-1 pt-3">
        {isMock && (
          <div className="flex items-start gap-1.5 rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5">
            <AlertTriangle
              className="mt-0.5 h-3 w-3 shrink-0 text-destructive"
              aria-hidden
            />
            <span className="text-[10px] font-medium leading-tight text-destructive">
              Synthetic data loaded
            </span>
          </div>
        )}
        <Link
          href="/settings"
          className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Settings className="h-4 w-4" aria-hidden />
          Settings
        </Link>
      </div>
    </nav>
  );
}

/** Top bar with title, subtitle and optional actions. */
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
        "flex flex-wrap items-center justify-between gap-3 border-b px-4 py-2.5",
        className,
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h1 className="truncate text-sm font-semibold">{title}</h1>
          {isMock && (
            <span className="rounded bg-destructive px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-destructive-foreground">
              Synthetic data
            </span>
          )}
        </div>
        {subtitle && (
          <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
      {children && (
        <div className="w-full">{children}</div>
      )}
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
  return <div className={cn("min-h-0 flex-1 overflow-auto", className)}>{children}</div>;
}

/** Consistent page padding with a max width for readability. */
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
    <div className={cn("p-4", wide ? "max-w-none" : "mx-auto max-w-7xl", className)}>
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
        "grid gap-3",
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
