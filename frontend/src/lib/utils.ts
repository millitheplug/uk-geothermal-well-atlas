import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format a number for display, or return a dash when unavailable. */
export function fmt(
  value: number | null | undefined,
  decimals = 0,
  fallback = "—",
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return fallback;
  }
  return value.toLocaleString("en-GB", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function fmtPence(
  value: number | null | undefined,
  decimals = 1,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(decimals)}p`;
}

export function fmtGBP(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 1_000_000) {
    return `£${(value / 1_000_000).toFixed(2)}m`;
  }
  if (Math.abs(value) >= 1000) return `£${(value / 1000).toFixed(0)}k`;
  return `£${value.toFixed(0)}`;
}

export function fmtDistance(m: number | null | undefined): string {
  if (m === null || m === undefined || Number.isNaN(m)) return "—";
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(2)} km`;
}

export function fmtTemp(c: number | null | undefined): string {
  if (c === null || c === undefined || Number.isNaN(c)) return "—";
  return `${c.toFixed(1)} °C`;
}

/**
 * The key to use when linking to, assessing or filtering by a well.
 *
 * Responses report the publisher's id as `well_id`. For NSTA wells that is
 * something like "LN/10- 4Z": not a UUID, and with a slash it cannot be a URL
 * segment. Every well endpoint is keyed by the well's UUID, so use that, and
 * fall back to the publisher's id only for an older backend that does not send
 * it yet.
 */
export function wellKey(ref: {
  well_uuid?: string | null;
  well_id: string;
}): string {
  return ref.well_uuid ?? ref.well_id;
}

export function fmtDepth(m: number | null | undefined): string {
  if (m === null || m === undefined || Number.isNaN(m)) return "—";
  return `${Math.round(m).toLocaleString("en-GB")} m`;
}

export function fmtEnergy(kwh: number | null | undefined): string {
  if (kwh === null || kwh === undefined || Number.isNaN(kwh)) return "—";
  const abs = Math.abs(kwh);
  if (abs >= 1_000_000) return `${(kwh / 1_000_000).toFixed(2)} GWh`;
  if (abs >= 1000) return `${(kwh / 1000).toFixed(1)} MWh`;
  return `${Math.round(kwh)} kWh`;
}

export function fmtPower(kw: number | null | undefined): string {
  if (kw === null || kw === undefined || Number.isNaN(kw)) return "—";
  if (Math.abs(kw) >= 1000) return `${(kw / 1000).toFixed(2)} MW`;
  return `${Math.round(kw)} kW`;
}

export function fmtPercent(
  value: number | null | undefined,
  decimals = 0,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

export function fmtConfidence(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) return "—";
  return `${Math.round(score * 100)}%`;
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return fmtDate(value);
}

export function fmtMetres(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

/** Debounce a value, for filter inputs that should not fire on every keystroke. */
export function debounce<T extends (...args: never[]) => unknown>(
  fn: T,
  delayMs = 300,
): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

/** Clamp a number into a range. */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}
