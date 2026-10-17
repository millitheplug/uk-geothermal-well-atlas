/**
 * Typed API client.
 *
 * Every response is validated at the boundary before it reaches a component.
 * The alternative - trusting the shape - produces failures deep in the render
 * tree where the cause is hard to trace, and it lets a backend change silently
 * turn a confidence label into a different one.
 */

import type {
  AnalysisProgress,
  AnalysisResult,
  CandidateTable,
  Dataset,
  EngineeringInputs,
  GeoJsonFeatureCollection,
  Health,
  HeatCluster,
  NationalDashboard,
  ParameterSpec,
  Project,
  ScenarioComparison,
  ScenarioDefinition,
  TokenResponse,
  WellDemandMatch,
  WellDetail,
  WellSearchResponse,
} from "@/types/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const TOKEN_KEY = "ukgeothermal.token";

/** Body of `POST /auth/register`. */
export interface RegisterPayload {
  full_name: string;
  email: string;
  organisation: string;
  password: string;
  password_confirm: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** True when the caller needs to re-authenticate. */
  get isAuthError(): boolean {
    return this.status === 401;
  }

  /** True when the failure is a rate limit, which the UI should present as retryable. */
  get isRateLimited(): boolean {
    return this.status === 429;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

/**
 * Build a query string, dropping null and undefined values.
 *
 * Typed as `object` rather than `Record<string, unknown>` so a caller can pass a
 * named parameter interface directly without an index signature or a cast.
 *
 * `false` is preserved deliberately: `has_temperature=false` is a meaningful
 * filter, whereas dropping it would silently return everything.
 */
export function buildQuery(params: object = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(
    params as Record<string, unknown>,
  )) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      search.set(key, value.join(","));
      continue;
    }
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Set false for endpoints that are safe to call without a session. */
  authenticated?: boolean;
}

/**
 * Turn an error body into a sentence a person can act on.
 *
 * FastAPI returns `detail` as a string for errors the API raises itself and as
 * a list of `{ loc, msg }` objects for request validation. Stringifying the
 * list gives "[object Object]", so the messages are pulled out instead.
 */
function describeFailure(body: unknown, status: number): string {
  const fallback = `Request failed with status ${status}`;
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return fallback;
  }
  const detail = (body as { detail: unknown }).detail;

  // The API's own validation handler: { detail: "request validation failed",
  // errors: [{ field, message }] }. Show the specific messages, not the stub.
  const errors = (body as { errors?: unknown }).errors;
  if (Array.isArray(errors) && errors.length > 0) {
    const messages = errors
      .map((item) =>
        typeof item === "object" && item !== null && "message" in item
          ? String((item as { message: unknown }).message).replace(/^Value error, /, "")
          : "",
      )
      .filter(Boolean);
    if (messages.length) return messages.join(". ");
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        typeof item === "object" && item !== null && "msg" in item
          ? String((item as { msg: unknown }).msg).replace(/^Value error, /, "")
          : "",
      )
      .filter(Boolean);
    return messages.length ? messages.join(". ") : fallback;
  }
  return String(detail);
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, signal, authenticated = true } = options;

  const headers: Record<string, string> = {
    Accept: "application/json",
  };

  const token = getToken();
  if (authenticated && token) {
    headers.Authorization = `Bearer ${token}`;
  }

  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(
      "Could not reach the API. Check that the backend is running.",
      0,
      error,
    );
  }

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text().catch(() => undefined);
    }

    const message = describeFailure(detail, response.status);

    throw new ApiError(
      message,
      response.status,
      detail,
      response.headers.get("X-Request-ID") ?? undefined,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface WellSearchParams {
  search?: string;
  status?: string[];
  original_purpose?: string[];
  operator?: string;
  licence?: string;
  region?: string[];
  county?: string;
  formation?: string;
  min_temperature_c?: number;
  max_temperature_c?: number;
  min_depth_m?: number;
  max_depth_m?: number;
  min_score?: number;
  max_score?: number;
  min_confidence_score?: number;
  min_data_confidence?: string[];
  drilling_year_from?: number;
  drilling_year_to?: number;
  has_temperature?: boolean;
  has_integrity?: boolean;
  recommendation?: string[];
  min_nearest_demand_m?: number;
  max_nearest_demand_m?: number;
  min_annual_demand_kwh?: number;
  centre_lat?: number;
  centre_lon?: number;
  radius_m?: number;
  include_mock?: boolean;
  /**
   * Also return wells that belong to no project, so they can be adopted.
   *
   * Discovery endpoints set this; a bare search does not. The tenancy model
   * makes wells invisible until they are attached to one of your projects, so
   * without this a new organisation has nothing to look at and no way to start.
   */
  include_claimable?: boolean;
  limit?: number;
  offset?: number;
  order_by?: string;
  descending?: boolean;
}

export const api = {
  // ---- auth ------------------------------------------------------------
  async login(email: string, password: string): Promise<TokenResponse> {
    const result = await request<TokenResponse>("/auth/login", {
      method: "POST",
      body: { email, password },
      authenticated: false,
    });
    setToken(result.access_token);
    return result;
  },

  /**
   * Create an account and its own organisation. The API signs the new user in,
   * so the token is stored exactly as it is after a login.
   */
  async register(payload: RegisterPayload): Promise<TokenResponse> {
    const result = await request<TokenResponse>("/auth/register", {
      method: "POST",
      body: payload,
      authenticated: false,
    });
    setToken(result.access_token);
    return result;
  },

  logout(): void {
    setToken(null);
  },

  me(signal?: AbortSignal) {
    return request<{ id: string; email: string; full_name: string; role: string }>(
      "/auth/me",
      { signal },
    );
  },

  // ---- wells -----------------------------------------------------------
  searchWells(params: WellSearchParams = {}, signal?: AbortSignal) {
    return request<WellSearchResponse>(`/wells${buildQuery(params)}`, { signal });
  },

  wellMapFeatures(
    params: WellSearchParams = {},
    signal?: AbortSignal,
  ) {
    return request<GeoJsonFeatureCollection>(
      `/wells/map${buildQuery(params)}`,
      { signal },
    );
  },

  wellFacets(signal?: AbortSignal) {
    return request<{
      statuses: string[];
      purposes: string[];
      regions: string[];
      counties: string[];
      recommendations: string[];
      confidence_bands: string[];
      temperature_range_c: { min: number | null; max: number | null };
      depth_range_m: { min: number | null; max: number | null };
      score_range: { min: number | null; max: number | null };
      total_wells: number;
    }>("/wells/facets", { signal });
  },

  getWell(wellId: string, signal?: AbortSignal) {
    return request<WellDetail>(`/wells/${wellId}`, { signal });
  },

  getWellDemand(
    wellId: string,
    params: { radius_m?: number; limit?: number } = {},
    signal?: AbortSignal,
  ) {
    return request<WellDemandMatch>(
      `/wells/${wellId}/demand${buildQuery(params)}`,
      { signal },
    );
  },

  getWellEvidence(wellId: string, signal?: AbortSignal) {
    return request<{
      well_id: string;
      evidence: Array<Record<string, unknown>>;
      claims: Array<Record<string, unknown>>;
      counts: Record<string, number>;
    }>(`/wells/${wellId}/evidence`, { signal });
  },

  // ---- analyses --------------------------------------------------------
  runAnalysis(
    wellId: string,
    inputs: EngineeringInputs = {},
    includeAi = true,
  ) {
    return request<AnalysisResult>("/analyses", {
      method: "POST",
      body: { well_id: wellId, inputs, include_ai_agents: includeAi },
    });
  },

  listAnalyses(
    params: {
      well_id?: string;
      recommendation?: string[];
      min_score?: number;
      limit?: number;
      offset?: number;
    } = {},
    signal?: AbortSignal,
  ) {
    return request<AnalysisResult[]>(`/analyses${buildQuery(params)}`, { signal });
  },

  getAnalysis(analysisId: string, signal?: AbortSignal) {
    return request<AnalysisResult>(`/analyses/${analysisId}`, { signal });
  },

  getAnalysisProgress(analysisId: string, signal?: AbortSignal) {
    return request<AnalysisProgress>(`/analyses/${analysisId}/progress`, {
      signal,
    });
  },

  getAnalysisReport(analysisId: string) {
    return fetch(`${API_BASE}/analyses/${analysisId}/report`, {
      headers: { Authorization: `Bearer ${getToken() ?? ""}` },
    }).then(async (response) => {
      if (!response.ok) {
        throw new ApiError(
          "No report is stored for this analysis.",
          response.status,
        );
      }
      return response.text();
    });
  },

  runScenarios(wellId: string, scenarios: ScenarioDefinition[]) {
    return request<ScenarioComparison>(`/analyses/${wellId}/scenarios`, {
      method: "POST",
      body: scenarios,
    });
  },

  /** Recalculate with overridden inputs. Nothing is persisted. */
  whatIf(wellId: string, inputs: EngineeringInputs, configuration?: string) {
    return request<AnalysisResult>(
      `/analyses/what-if${buildQuery({ well_uuid: wellId, configuration })}`,
      { method: "POST", body: inputs },
    );
  },

  // ---- dashboard -------------------------------------------------------
  nationalDashboard(includeMock = true, signal?: AbortSignal) {
    return request<NationalDashboard>(
      `/dashboard/national${buildQuery({ include_mock: includeMock })}`,
      { signal },
    );
  },

  candidates(
    params: Record<string, unknown> = {},
    signal?: AbortSignal,
  ) {
    return request<CandidateTable>(`/dashboard/candidates${buildQuery(params)}`, {
      signal,
    });
  },

  pipelineSummary(signal?: AbortSignal) {
    return request<{
      stages: Array<{ stage: string; order: number }>;
      weights: Record<string, number>;
      weights_sum: number;
      recommendation_levels: string[];
      confidence_bands: string[];
      risk_categories: string[];
    }>("/dashboard/summary", { signal });
  },

  // ---- heat ------------------------------------------------------------
  heatClusters(
    params: { cell_deg?: number; min_demand_kwh?: number } = {},
    signal?: AbortSignal,
  ) {
    return request<HeatCluster[]>(`/heat/clusters${buildQuery(params)}`, {
      signal,
    });
  },

  corridors(
    params: { limit_wells?: number; max_distance_m?: number } = {},
    signal?: AbortSignal,
  ) {
    return request<{
      corridors: Array<{
        well_id: string;
        /** The key every well endpoint takes. `well_id` is the publisher's id. */
        well_uuid?: string | null;
        well_name: string;
        /**
         * A `LineString`, not an arbitrary geometry: the backend builds these as
         * two-point straight lines, and typing it precisely is what stops the
         * corridor layer from silently accepting a polygon.
         */
        geometry: { type: "LineString"; coordinates: number[][] };
        distance_m: number;
        target_demand_kwh: number | null;
        indicative: boolean;
        note: string;
      }>;
      total_straight_line_length_km: number;
      caveat: string;
    }>(`/heat/corridors${buildQuery(params)}`, { signal });
  },

  demandSummary(signal?: AbortSignal) {
    return request<{
      by_building_type: Record<string, { count: number; demand_kwh: number }>;
      by_fuel: Record<string, { count: number; demand_kwh: number }>;
      totals: { buildings: number; annual_demand_gwh: number; peak_demand_kw: number };
      caveat: string;
    }>("/heat/demand-summary", { signal });
  },

  // ---- admin -----------------------------------------------------------
  health(signal?: AbortSignal) {
    return request<Health>("/admin/health", { signal });
  },

  datasets(signal?: AbortSignal) {
    return request<{ datasets: Dataset[]; counts: Record<string, number> }>(
      "/admin/datasets",
      { signal },
    );
  },

  parameters(signal?: AbortSignal) {
    return request<{ parameters: ParameterSpec[]; count: number; note: string }>(
      "/admin/parameters",
      { signal },
    );
  },

  regulatory(configuration?: string, signal?: AbortSignal) {
    return request<{
      requirements: Array<Record<string, unknown>>;
      count: number;
      caveat: string;
    }>(`/admin/regulatory${buildQuery({ configuration })}`, { signal });
  },

  // ---- projects --------------------------------------------------------
  listProjects(signal?: AbortSignal) {
    return request<Project[]>("/projects", { signal });
  },

  createProject(payload: {
    name: string;
    description?: string;
    target_region?: string;
    well_ids?: string[];
  }) {
    return request<Project>("/projects", { method: "POST", body: payload });
  },

  addWellToProject(projectId: string, wellId: string, role = "candidate") {
    return request<void>(
      `/projects/${projectId}/wells/${wellId}${buildQuery({ role })}`,
      { method: "POST" },
    );
  },

  updateProjectStage(projectId: string, stage: string) {
    return request<{
      id: string;
      stage: string;
      previous_stage: string;
      available_stages: string[];
    }>(`/projects/${projectId}/stage${buildQuery({ stage })}`, { method: "PATCH" });
  },

  archiveProject(projectId: string) {
    return request<void>(`/projects/${projectId}/archive`, { method: "POST" });
  },

  adapters(signal?: AbortSignal) {
    return request<{
      adapters: Array<{
        name: string;
        description: string;
        is_mock: boolean;
        source_url: string | null;
        licence: string | null;
      }>;
      count: number;
    }>("/admin/adapters", { signal });
  },

  prices(signal?: AbortSignal) {
    return request<Record<string, unknown>>("/admin/prices", { signal });
  },

  heatNetworks(signal?: AbortSignal) {
    return request<{ networks: Array<Record<string, unknown>>; count: number }>(
      "/admin/heat-networks",
      { signal },
    );
  },

  demandAreas(signal?: AbortSignal) {
    return request<{ areas: Array<Record<string, unknown>>; count: number }>(
      "/admin/demand-areas",
      { signal },
    );
  },

  auditLog(signal?: AbortSignal) {
    return request<{ entries: Array<Record<string, unknown>>; count: number }>(
      "/auth/audit",
      { signal },
    );
  },
};
