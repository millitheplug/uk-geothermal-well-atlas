/**
 * Shared API types, mirroring the backend Pydantic schemas.
 *
 * The six epistemic labels are re-declared here as a union so the compiler
 * rejects any place that invents a seventh. Same for the four recommendation
 * levels and the confidence bands.
 */

import type { Feature, Geometry } from "geojson";

export type EpistemicStatus =
  | "FACT"
  | "MEASURED"
  | "DERIVED"
  | "ESTIMATE"
  | "MODELLED"
  | "ASSUMPTION"
  | "UNKNOWN";

export type Recommendation =
  | "HIGH PRIORITY"
  | "MEDIUM PRIORITY"
  | "LOW PRIORITY"
  | "DO NOT PURSUE";

export type ConfidenceBand =
  | "high"
  | "medium"
  | "low"
  | "very_low"
  | "unknown";

export type AnalysisStage =
  | "data_validation"
  | "geology"
  | "temperature"
  | "well_integrity"
  | "heat_demand"
  | "engineering"
  | "economics"
  | "risk"
  | "final_assessment";

export type WellStatus =
  | "producing"
  | "non_producing"
  | "suspended"
  | "plugged_abandoned"
  | "abandoned"
  | "drilling"
  | "completed"
  | "exploration"
  | "unknown";

export type GeothermalConfiguration =
  | "closed_loop"
  | "open_loop"
  | "closed_loop_plus_heat_pump"
  | "open_loop_plus_heat_pump";

export type RiskCategory =
  | "well_integrity"
  | "temperature_uncertainty"
  | "thermal_decline"
  | "corrosion"
  | "scaling"
  | "groundwater"
  | "network_distance"
  | "heat_demand_uncertainty"
  | "capex"
  | "electricity_price"
  | "heat_price"
  | "regulation"
  | "planning"
  | "land_access"
  | "customer_connection"
  | "construction"
  | "operations";

export type ScoreComponentName =
  | "thermal"
  | "integrity"
  | "demand"
  | "economics"
  | "network"
  | "geometry"
  | "regulatory"
  | "data_confidence";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  tenant_id: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface WellSummary {
  id: string;
  well_id: string;
  well_name: string;
  latitude: number;
  longitude: number;
  region: string | null;
  county: string | null;
  status: WellStatus;
  original_purpose: string | null;
  operator: string | null;
  drilling_year: number | null;
  total_depth_m: number | null;
  temperature_c: number | null;
  temperature_status: EpistemicStatus;
  temperature_confidence: ConfidenceBand;
  data_confidence: ConfidenceBand;
  feasibility_score: number | null;
  confidence_score: number | null;
  recommendation: Recommendation | null;
  is_mock: boolean;
}

export interface WellTemperature {
  id: string;
  measured_at: string | null;
  depth_m: number;
  temperature_c: number;
  measurement_method: string;
  status: EpistemicStatus;
  confidence: ConfidenceBand;
  is_final_stabilised: boolean;
  geothermal_gradient_c_per_km: number | null;
  source: string;
  source_url: string | null;
  note: string | null;
}

export interface WellIntegrity {
  status: string;
  status_status: EpistemicStatus;
  confidence: ConfidenceBand;
  casing_condition_score: number | null;
  wellhead_condition_score: number | null;
  access_score: number | null;
  abandonment_score: number | null;
  requires_reequipment: boolean | null;
  estimated_recompletion_capex_gbp: number | null;
  estimated_recompletion_capex_status: EpistemicStatus;
  corrosion_evidence: string | null;
  scaling_evidence: string | null;
  gas_hazard: boolean | null;
  last_integrity_check_date: string | null;
  source: string;
  source_url: string | null;
  unknown_reasons: string | null;
}

export interface WellLog {
  id: string;
  log_type: string;
  logged_at: string | null;
  top_depth_m: number | null;
  bottom_depth_m: number | null;
  storage_uri: string | null;
  has_temperature_curve: boolean;
  tool_company: string | null;
  is_public_domain: boolean;
  licence: string | null;
  source: string;
  source_url: string | null;
}

export interface WellDetail extends WellSummary {
  licence: string | null;
  commissioned_date: string | null;
  tvd_m: number | null;
  md_m: number | null;
  max_deviation_deg: number | null;
  is_deviated: boolean | null;
  formation: string | null;
  basin: string | null;
  temperature_depth_m: number | null;
  temperature_source: string | null;
  temperature_variability_c: number | null;
  bottomhole_pressure_bar: number | null;
  static_pressure_bar: number | null;
  pressure_status: EpistemicStatus;
  casing_string: string | null;
  completion_type: string | null;
  has_wellhead: boolean | null;
  loggable: boolean | null;
  plugged_and_abandoned_date: string | null;
  data_completeness: number | null;
  known_data_gaps: Record<string, string> | null;
  source: string;
  source_url: string | null;
  dataset_version: string | null;
  analysed_at: string | null;
  analysis_version: string | null;
  temperatures: WellTemperature[];
  integrity: WellIntegrity | null;
  logs: WellLog[];
}

export interface WellSearchResponse {
  items: WellSummary[];
  total: number;
  limit: number;
  offset: number;
  /** "postgis" or "haversine": which spatial backend produced the distances. */
  spatial_dialect: string;
}

export interface NearbyBuilding {
  id: string;
  building_type: string;
  latitude: number;
  longitude: number;
  postcode: string | null;
  floor_area_m2: number | null;
  annual_heat_demand_kwh: number | null;
  peak_heat_demand_kw: number | null;
  required_supply_temperature_c: number | null;
  current_fuel: string | null;
  connection_potential: string | null;
  distance_m: number;
}

export interface WellDemandMatch {
  well_id: string;
  radius_m: number;
  building_count: number;
  total_annual_demand_kwh: number;
  total_peak_demand_kw: number;
  nearest_building_distance_m: number | null;
  weighted_centre_latitude: number | null;
  weighted_centre_longitude: number | null;
  dominant_building_type: string | null;
  average_required_supply_temperature_c: number | null;
  demand_confidence: ConfidenceBand;
  notes: string[];
  spatial_dialect: string;
  buildings: NearbyBuilding[];
}

export interface CalculationTrace {
  function_name: string;
  inputs: Record<string, unknown>;
  input_units: Record<string, string>;
  formula: string;
  result: number | null;
  result_unit: string;
  status: EpistemicStatus;
  assumptions: Array<Record<string, unknown>>;
  sources: Array<Record<string, unknown>>;
  intermediate_values: Record<string, unknown>;
  warnings: string[];
  confidence: number | null;
  engine_version: string;
}

export interface ScoreComponent {
  score: number;
  weight: number;
  contribution: number;
  notes: string[];
}

export interface FeasibilityScore {
  final: number;
  confidence_score: number;
  score_version: string;
  components: Record<ScoreComponentName, ScoreComponent>;
  notes: string[];
  weights: Record<ScoreComponentName, number>;
}

export interface ConfidenceAxis {
  score: number;
  weight: number;
  contribution: number;
  notes: string[];
}

export interface ConfidenceDetail {
  score: number;
  band: ConfidenceBand;
  confidence_version: string;
  axes: Record<string, ConfidenceAxis>;
  conflicting_sources: string[];
  unknowns: string[];
}

export interface Risk {
  category: RiskCategory;
  title: string;
  description: string;
  likelihood: string;
  probability: number;
  impact: string;
  impact_value: number;
  uncertainty: number;
  risk_score: number;
  uncertainty_adjusted_score: number;
  severity: string;
  is_critical: boolean;
  evidence: string[];
  mitigation: string | null;
  addresses_data_gap: string | null;
}

export interface RiskAssessment {
  aggregate_score: number;
  risk_count: number;
  critical_count: number;
  risks: Risk[];
}

export interface ValidationAction {
  id: string;
  action_type: string;
  title: string;
  description: string | null;
  priority: "critical" | "high" | "medium" | "low";
  rationale: string | null;
  addresses_risk_ids: string[];
  addresses_data_gaps: string[];
  estimated_cost_gbp: number | null;
  estimated_duration_days: number | null;
  status: string;
}

export interface Evidence {
  id: string;
  source: string;
  source_url: string | null;
  source_title: string | null;
  source_date: string | null;
  document_type: string | null;
  reliability: number;
  relevance: number;
  quality: number;
  excerpt: string | null;
  page_reference: string | null;
  status: EpistemicStatus;
  is_mock: boolean;
}

export interface Claim {
  id: string;
  field_name: string;
  claim: string;
  value: Record<string, unknown> | null;
  status: EpistemicStatus;
  confidence: string | null;
  agent: string | null;
  is_critical: boolean;
  evidence: Evidence | null;
}

export interface RegulatoryRequirement {
  id: string;
  jurisdiction: string;
  title: string;
  description: string | null;
  authority: string | null;
  applies_to_configuration: string | null;
  is_mandatory: boolean;
  typical_lead_time_months: number | null;
  estimated_cost_gbp: number | null;
  source: string;
  source_url: string | null;
  is_mock: boolean;
}

export interface AnalysisResult {
  analysis_id: string | null;
  well_id: string;
  /** The key every well endpoint takes. `well_id` is the publisher's id. */
  well_uuid?: string | null;
  well_name: string;
  pipeline_version: string;
  configuration: GeothermalConfiguration;
  recommended_configuration: GeothermalConfiguration;

  source_temperature_c: number | null;
  temperature_status: EpistemicStatus;

  thermal_output_kw: number | null;
  thermal_output_low_kw: number | null;
  thermal_output_high_kw: number | null;
  thermal_output_status: EpistemicStatus;
  heat_pump_cop: number | null;
  heat_pump_electricity_kw: number | null;
  delivered_heat_kw: number | null;

  network_length_m: number | null;
  network_heat_loss_kw: number | null;
  network_loss_fraction: number | null;
  nearest_building_distance_m: number | null;
  demand_matched_kw: number | null;
  annual_heat_kwh: number | null;

  capex_gbp: number | null;
  opex_gbp_per_year: number | null;
  lcoh_p_per_kwh: number | null;
  npv_gbp: number | null;
  irr_pct: number | null;
  payback_years: number | null;
  break_even_heat_price_p_per_kwh: number | null;

  feasibility_score: number;
  confidence_score: number;
  confidence_band: ConfidenceBand;
  component_scores: Record<string, number>;

  recommendation: Recommendation;
  recommendation_rationale: string[];
  next_action: string;

  risk: RiskAssessment | null;
  confidence_detail: ConfidenceDetail | null;
  data_gaps: string[];
  unknowns: string[];
  warnings: string[];
  calculation_trace: CalculationTrace[];
  parameters: Record<string, unknown>;

  evidence: Evidence[];
  claims: Claim[];
  regulatory_requirements: RegulatoryRequirement[];
  validation_actions: ValidationAction[];
  agent_outputs: Record<string, unknown> | null;
  report_markdown: string | null;
  executive_summary: string | null;
}

export interface AnalysisProgress {
  analysis_id: string;
  status: "pending" | "running" | "complete" | "failed";
  stage: AnalysisStage;
  completed_stages: AnalysisStage[];
  stage_messages: Record<string, string>;
  percent_complete: number;
  error_message: string | null;
}

export interface EngineeringInputs {
  flow_rate_lps?: number;
  source_temperature_c?: number;
  return_temperature_c?: number;
  heat_pump_cop?: number;
  heat_price_p_per_kwh?: number;
  electricity_price_p_per_kwh?: number;
  operating_hours_per_year?: number;
  capacity_factor?: number;
  utilisation_factor?: number;
  discount_rate?: number;
  project_lifetime_years?: number;
  target_supply_temperature_c?: number;
  ground_temperature_c?: number;
  network_length_m?: number;
  connected_load_kw?: number;
  capex_gbp?: number;
  opex_gbp_per_year?: number;
}

export interface ScenarioDefinition {
  name: string;
  label?: string;
  description?: string;
  inputs: EngineeringInputs;
  probability_weight?: number;
}

export interface ScenarioResult {
  name: string;
  label: string | null;
  inputs: EngineeringInputs;
  overrides_applied: Record<string, boolean>;
  thermal_output_kw: number | null;
  thermal_output_low_kw: number | null;
  thermal_output_high_kw: number | null;
  thermal_output_status: EpistemicStatus;
  heat_pump_cop: number | null;
  annual_heat_kwh: number | null;
  capex_gbp: number | null;
  opex_gbp_per_year: number | null;
  lcoh_p_per_kwh: number | null;
  npv_gbp: number | null;
  irr_pct: number | null;
  payback_years: number | null;
  break_even_heat_price_p_per_kwh: number | null;
  feasibility_score: number | null;
  recommendation: Recommendation | null;
  warnings: string[];
}

export interface ScenarioComparison {
  well_id: string;
  scenarios: ScenarioResult[];
  expected_lcoh_p_per_kwh: number | null;
  expected_npv_gbp: number | null;
  spread_lcoh_p_per_kwh: number | null;
  notes: string[];
}

export interface CandidateRow {
  rank: number;
  well_id: string;
  /** The key every well endpoint takes. `well_id` is the publisher's id. */
  well_uuid?: string | null;
  well_name: string;
  latitude: number;
  longitude: number;
  region: string | null;
  status: WellStatus;
  total_depth_m: number | null;
  temperature_c: number | null;
  temperature_status: EpistemicStatus;
  temperature_confidence: ConfidenceBand;
  nearest_building_distance_m: number | null;
  annual_demand_kwh: number | null;
  thermal_output_kw: number | null;
  thermal_output_status: EpistemicStatus;
  capex_gbp: number | null;
  lcoh_p_per_kwh: number | null;
  feasibility_score: number | null;
  confidence_score: number | null;
  recommendation: Recommendation | null;
  is_mock: boolean;
}

export interface CandidateTable {
  items: CandidateRow[];
  total: number;
  limit: number;
  offset: number;
  ranking_basis: string;
  includes_mock_data: boolean;
}

export interface NationalDashboard {
  total_wells: number;
  wells_with_temperature: number;
  wells_without_temperature: number;
  candidate_wells: number;
  high_potential_wells: number;
  average_temperature_c: number | null;
  average_depth_m: number | null;
  total_estimated_thermal_capacity_mwt: number | null;
  total_estimated_thermal_capacity_status: EpistemicStatus;
  nearby_heat_demand_opportunity_gwh: number | null;
  wells_needing_more_data: number;
  recommendation_breakdown: Record<string, number>;
  confidence_breakdown: Record<string, number>;
  status_breakdown: Record<string, number>;
  purpose_breakdown: Record<string, number>;
  region_breakdown: Record<string, number>;
  score_histogram: Array<{
    range: string;
    lower: number | null;
    upper: number | null;
    count: number;
  }>;
  risk_category_totals: Record<string, number>;
  is_mock: boolean;
  caveats: string[];
}

export interface HeatCluster {
  cluster_id: string;
  building_count: number;
  total_annual_demand_kwh: number;
  total_peak_demand_kw: number;
  centroid_latitude: number;
  centroid_longitude: number;
  radius_m: number;
  dominant_building_type: string | null;
  nearest_well_id: string | null;
  /** The key every well endpoint takes. `nearest_well_id` is the publisher's id. */
  nearest_well_uuid?: string | null;
  nearest_well_distance_m: number | null;
  is_clustered_with_postgis: boolean;
}

/**
 * Map feature types.
 *
 * `Feature<Geometry, ...>` rather than a hand-rolled shape, so a corridor
 * cannot be passed where a point belongs. `properties` is a record because the
 * map payload is deliberately terse and its property names vary by layer.
 */
export interface GeoJsonFeatureCollection {
  type: "FeatureCollection";
  features: Array<Feature<Geometry, Record<string, unknown>>>;
  /** "postgis" or "haversine": which spatial backend produced the distances. */
  spatial_dialect: string;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  stage: string;
  target_region: string | null;
  target_scenario: string | null;
  created_at: string;
  updated_at: string;
}

export interface Health {
  status: string;
  version: string;
  environment: string;
  database: string;
  spatial_dialect: string;
  redis: string;
  llm: string;
  is_mock_data: boolean;
}

export interface Dataset {
  id: string;
  source: string;
  name: string;
  description: string | null;
  source_url: string | null;
  download_date: string | null;
  published_date: string | null;
  licence: string | null;
  version: string;
  reliability: string;
  quality_score: number;
  row_count: number | null;
  validation_summary: Record<string, unknown> | null;
  is_mock: boolean;
  status: string;
  last_ingested_at: string | null;
}

export interface ParameterSpec {
  key: string;
  value: unknown;
  unit: string | null;
  rationale: string;
  source: string | null;
  low: number | null;
  high: number | null;
  distribution: string | null;
}
