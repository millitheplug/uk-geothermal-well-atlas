"""Pydantic schemas: the API contract.

Two rules hold throughout this module:

* every field that carries a domain value also exposes its epistemic status
  where the status is not obvious;
* no schema invents a default for a measurement. `None` means unknown, and the
  API says so rather than returning zero.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import (
    AnalysisStage,
    AnalysisStatus,
    DataConfidence,
    EpistemicStatus,
    Recommendation,
    RiskCategory,  # noqa: F401 -- re-exported; api.v1.dashboard imports it from here.
)


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- wells
class ProvenanceBase(ORMBase):
    """Provenance block returned with every ingested entity."""

    source: str = Field(description="Adapter id that wrote this row.")
    source_url: str | None = None
    dataset_version: str | None = None
    is_mock: bool = Field(
        default=False,
        description="True when the row came from a synthetic development dataset. "
        "The frontend must watermark these.",
    )


class WellTemperatureRead(ORMBase):
    id: uuid.UUID
    measured_at: datetime | None = None
    depth_m: float
    temperature_c: float
    measurement_method: str = Field(
        description="How the number was obtained. 'static_bht' and 'circulation_test' "
        "outrank 'regional_estimate' by a wide margin in confidence scoring."
    )
    status: str = Field(description="Epistemic status: MEASURED, DERIVED, ESTIMATE, UNKNOWN.")
    confidence: str
    is_final_stabilised: bool = Field(
        description="False means the reading had not thermally equilibrated and "
        "overstates the sustained temperature."
    )
    geothermal_gradient_c_per_km: float | None = None
    source: str
    source_url: str | None = None
    note: str | None = None


class WellIntegrityRead(ORMBase):
    status: str
    status_status: str
    confidence: str
    casing_condition_score: float | None = None
    wellhead_condition_score: float | None = None
    access_score: float | None = None
    abandonment_score: float | None = None
    requires_reequipment: bool | None = None
    estimated_recompletion_capex_gbp: float | None = None
    estimated_recompletion_capex_status: str
    corrosion_evidence: str | None = None
    scaling_evidence: str | None = None
    gas_hazard: bool | None = None
    last_integrity_check_date: date | None = None
    source: str
    source_url: str | None = None
    unknown_reasons: str | None = Field(
        default=None,
        description="Why integrity is unknown. Present whenever status is UNKNOWN, "
        "so the gap is self-explaining.",
    )


class WellLogRead(ORMBase):
    id: uuid.UUID
    log_type: str
    logged_at: date | None = None
    top_depth_m: float | None = None
    bottom_depth_m: float | None = None
    storage_uri: str | None = None
    has_temperature_curve: bool = False
    tool_company: str | None = None
    is_public_domain: bool = True
    licence: str | None = None
    source: str
    source_url: str | None = None


class WellSummary(ORMBase):
    """Compact representation for map rendering and candidate tables."""

    id: uuid.UUID
    well_id: str
    well_name: str
    latitude: float
    longitude: float
    region: str | None = None
    county: str | None = None
    status: str
    original_purpose: str | None = None
    operator: str | None = None
    drilling_year: int | None = None
    total_depth_m: float | None = None
    temperature_c: float | None = None
    temperature_status: str
    temperature_confidence: str
    data_confidence: str
    feasibility_score: float | None = None
    confidence_score: float | None = None
    recommendation: str | None = None
    is_mock: bool = Field(default=False, validation_alias="source")

    @field_validator("is_mock", mode="before")
    @classmethod
    def _derive_is_mock(cls, v: Any) -> bool:
        # `source` is the adapter id; mock adapters are named `mock_*`.
        return isinstance(v, str) and v.startswith("mock_")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class WellDetail(WellSummary):
    """Full record for the well detail page and analysis input."""

    licence: str | None = None
    commissioned_date: date | None = None
    tvd_m: float | None = None
    md_m: float | None = None
    max_deviation_deg: float | None = None
    is_deviated: bool | None = None
    formation: str | None = None
    basin: str | None = None
    temperature_depth_m: float | None = None
    temperature_source: str | None = None
    temperature_variability_c: float | None = None
    bottomhole_pressure_bar: float | None = None
    static_pressure_bar: float | None = None
    pressure_status: str
    casing_string: str | None = None
    completion_type: str | None = None
    has_wellhead: bool | None = None
    loggable: bool | None = None
    plugged_and_abandoned_date: date | None = None
    data_completeness: float | None = None
    known_data_gaps: dict[str, Any] | None = None
    source: str
    source_url: str | None = None
    dataset_version: str | None = None
    analysed_at: datetime | None = None
    analysis_version: str | None = None

    temperatures: list[WellTemperatureRead] = Field(default_factory=list)
    integrity: WellIntegrityRead | None = None
    logs: list[WellLogRead] = Field(default_factory=list)


class WellSearchResponse(BaseModel):
    items: list[WellSummary]
    total: int
    limit: int
    offset: int
    spatial_dialect: str = Field(
        description="'postgis' when running on PostGIS, 'haversine' when using the "
        "SQLite development fallback."
    )


# ------------------------------------------------------- geospatial
class NearbyBuilding(ORMBase):
    id: uuid.UUID
    building_type: str
    latitude: float
    longitude: float
    postcode: str | None = None
    floor_area_m2: float | None = None
    annual_heat_demand_kwh: float | None = None
    peak_heat_dwemand_kw: float | None = Field(default=None, alias="peak_heat_demand_kw")
    required_supply_temperature_c: float | None = None
    current_fuel: str | None = None
    connection_potential: str | None = None
    distance_m: float = Field(description="Great-circle distance from the well.")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class WellDemandMatch(BaseModel):
    """Result of matching a well to nearby heat demand."""

    well_id: str
    radius_m: float
    building_count: int
    total_annual_demand_kwh: float
    total_peak_demand_kw: float
    nearest_building_distance_m: float | None = None
    weighted_centre_latitude: float | None = None
    weighted_centre_longitude: float | None = None
    dominant_building_type: str | None = None
    average_required_supply_temperature_c: float | None = None
    buildings: list[NearbyBuilding] = Field(default_factory=list)
    demand_confidence: str = Field(
        default=DataConfidence.UNKNOWN.value,
        description="Confidence in the matched demand figure, derived from source quality.",
    )
    notes: list[str] = Field(default_factory=list)


class HeatCluster(BaseModel):
    """An aggregated pocket of heat demand, from a clustering pass over buildings."""

    cluster_id: str
    building_count: int
    total_annual_demand_kwh: float
    total_peak_demand_kw: float
    centroid_latitude: float
    centroid_longitude: float
    radius_m: float
    dominant_building_type: str | None = None
    nearest_well_id: str | None = None
    # The key every well endpoint takes. `nearest_well_id` is the publisher's id
    # (for NSTA wells it contains a slash and spaces, e.g. "LN/10- 4Z"), which is
    # neither a UUID nor usable as a URL segment.
    nearest_well_uuid: uuid.UUID | None = None
    nearest_well_distance_m: float | None = None
    is_clustered_with_postgis: bool = Field(
        description="True when produced by ST_ClusterDBSCAN; false when produced by "
        "the pure-Python fallback used on SQLite."
    )


class HeatDemandSummary(BaseModel):
    area_code: str
    area_name: str | None = None
    area_type: str
    latitude: float
    longitude: float
    total_annual_demand_kwh: float
    household_count: int | None = None
    average_supply_temperature_c: float | None = None
    source: str
    is_mock: bool = False


# ------------------------------------------------------- engineering
class CalculationTraceRead(BaseModel):
    function_name: str
    inputs: dict[str, Any]
    input_units: dict[str, str]
    formula: str
    result: float | None
    result_unit: str
    status: str
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    intermediate_values: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    confidence: float | None = None
    engine_version: str


class EngineeringInputs(BaseModel):
    """User-overridable inputs for a scenario run.

    Every field is optional. Omitted fields fall back to the documented defaults
    in :mod:`app.engineering.parameters`, and the response records which were
    defaults and which were supplied.
    """

    flow_rate_lps: float | None = Field(default=None, gt=0, le=1000)
    source_temperature_c: float | None = Field(default=None, gt=0, le=400)
    return_temperature_c: float | None = Field(default=None, gt=0, le=400)
    heat_pump_cop: float | None = Field(default=None, gt=0, le=30)
    heat_price_p_per_kwh: float | None = Field(default=None, gt=0, le=500)
    electricity_price_p_per_kwh: float | None = Field(default=None, gt=0, le=500)
    operating_hours_per_year: float | None = Field(default=None, gt=0, le=8784)
    capacity_factor: float | None = Field(default=None, gt=0, le=1)
    utilisation_factor: float | None = Field(default=None, gt=0, le=1)
    discount_rate: float | None = Field(default=None, gt=-0.99, le=3)
    project_lifetime_years: int | None = Field(default=None, ge=1, le=50)
    target_supply_temperature_c: float | None = Field(default=None, gt=0, le=200)
    ground_temperature_c: float | None = Field(default=None, gt=-10, le=40)
    network_length_m: float | None = Field(default=None, gt=0, le=200_000)
    connected_load_kw: float | None = Field(default=None, gt=0, le=100_000)
    capex_gbp: float | None = Field(default=None, gt=0)
    opex_gbp_per_year: float | None = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid")


class ScenarioDefinition(BaseModel):
    name: str = Field(max_length=64, examples=["bear", "base", "bull"])
    label: str | None = None
    description: str | None = None
    inputs: EngineeringInputs = Field(default_factory=EngineeringInputs)
    probability_weight: float | None = Field(default=None, ge=0, le=1)


class ScenarioResult(BaseModel):
    name: str
    label: str | None = None
    inputs: EngineeringInputs
    overrides_applied: dict[str, bool] = Field(
        default_factory=dict,
        description="Which parameters this scenario supplied versus which came from "
        "the documented defaults.",
    )
    thermal_output_kw: float | None = None
    thermal_output_low_kw: float | None = None
    thermal_output_high_kw: float | None = None
    thermal_output_status: str
    heat_pump_cop: float | None = None
    annual_heat_kwh: float | None = None
    capex_gbp: float | None = None
    opex_gbp_per_year: float | None = None
    lcoh_p_per_kwh: float | None = None
    npv_gbp: float | None = None
    irr_pct: float | None = None
    payback_years: float | None = None
    break_even_heat_price_p_per_kwh: float | None = None
    feasibility_score: float | None = None
    recommendation: str | None = None
    warnings: list[str] = Field(default_factory=list)


# ----------------------------------------------------------- scoring
class ScoreComponentRead(BaseModel):
    score: float = Field(ge=0, le=1)
    weight: float
    contribution: float
    notes: list[str] = Field(default_factory=list)


class FeasibilityScoreRead(BaseModel):
    final: float = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=1)
    score_version: str
    components: dict[str, ScoreComponentRead]
    notes: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(
        description="The weights used, so a stored score can be re-read correctly "
        "after the weighting changes.",
    )


class ConfidenceAxisRead(BaseModel):
    score: float = Field(ge=0, le=1)
    weight: float
    contribution: float
    notes: list[str] = Field(default_factory=list)


class ConfidenceRead(BaseModel):
    score: float = Field(ge=0, le=1)
    band: str
    confidence_version: str
    axes: dict[str, ConfidenceAxisRead]
    conflicting_sources: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class RiskRead(BaseModel):
    category: str
    title: str
    description: str
    likelihood: str
    probability: float = Field(ge=0, le=1)
    impact: str
    impact_value: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=1)
    uncertainty_adjusted_score: float = Field(ge=0, le=1)
    severity: str
    is_critical: bool
    evidence: list[str] = Field(default_factory=list)
    mitigation: str | None = None
    addresses_data_gap: str | None = None


class RiskAssessmentRead(BaseModel):
    aggregate_score: float = Field(ge=0, le=1)
    risk_count: int
    critical_count: int
    risks: list[RiskRead]


class ValidationActionRead(BaseModel):
    id: uuid.UUID
    action_type: str
    title: str
    description: str | None = None
    priority: str
    rationale: str | None = None
    addresses_risk_ids: list[str] = Field(default_factory=list)
    addresses_data_gaps: list[str] = Field(default_factory=list)
    estimated_cost_gbp: float | None = None
    estimated_duration_days: float | None = None
    status: str


class EvidenceRead(BaseModel):
    id: uuid.UUID
    source: str
    source_url: str | None = None
    source_title: str | None = None
    source_date: date | None = None
    document_type: str | None = None
    reliability: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    quality: float = Field(ge=0, le=1)
    excerpt: str | None = None
    page_reference: str | None = None
    status: str
    is_mock: bool = False


class ClaimRead(BaseModel):
    id: uuid.UUID
    field_name: str
    claim: str
    value: dict[str, Any] | None = None
    status: str
    confidence: str | None = None
    agent: str | None = None
    is_critical: bool = False
    evidence: EvidenceRead | None = None


class RegulatoryRequirementRead(ORMBase):
    id: uuid.UUID
    jurisdiction: str
    title: str
    description: str | None = None
    authority: str | None = None
    applies_to_configuration: str | None = None
    is_mandatory: bool = True
    typical_lead_time_months: float | None = None
    estimated_cost_gbp: float | None = None
    source: str
    source_url: str | None = None
    is_mock: bool = False


# ---------------------------------------------------------- analyses
class AnalysisCreate(BaseModel):
    well_id: uuid.UUID
    scenario_name: str | None = Field(
        default=None,
        description="Run one named scenario instead of the full bear/base/bull set.",
    )
    inputs: EngineeringInputs = Field(default_factory=EngineeringInputs)
    include_ai_agents: bool = Field(
        default=True,
        description="Set false to run the deterministic pipeline only, skipping all "
        "LLM calls. Deterministic results are identical either way.",
    )

    model_config = ConfigDict(extra="forbid")


class AnalysisProgress(BaseModel):
    """Progress polling payload for the staged assessment UI."""

    analysis_id: uuid.UUID
    status: AnalysisStatus
    stage: AnalysisStage
    completed_stages: list[AnalysisStage] = Field(default_factory=list)
    stage_messages: dict[str, str] = Field(
        default_factory=dict,
        description="Human-readable status for each stage, including stages not yet run.",
    )
    percent_complete: int = Field(ge=0, le=100)
    error_message: str | None = None


class AnalysisResult(BaseModel):
    """The full deterministic result for one well and scenario."""

    analysis_id: uuid.UUID | None = None
    well_id: str
    # The key every well endpoint takes (see CandidateRow.well_uuid).
    well_uuid: uuid.UUID | None = None
    well_name: str
    pipeline_version: str
    configuration: str
    recommended_configuration: str

    source_temperature_c: float | None = None
    temperature_status: str

    thermal_output_kw: float | None = None
    thermal_output_low_kw: float | None = None
    thermal_output_high_kw: float | None = None
    thermal_output_status: str = Field(
        description="Provenance of the thermal output. Only MEASURED when a flow test "
        "exists; otherwise ESTIMATE."
    )
    heat_pump_cop: float | None = None
    heat_pump_electricity_kw: float | None = None
    delivered_heat_kw: float | None = None

    network_length_m: float | None = None
    network_heat_loss_kw: float | None = None
    network_loss_fraction: float | None = None
    nearest_building_distance_m: float | None = None
    demand_matched_kw: float | None = None
    annual_heat_kwh: float | None = None

    capex_gbp: float | None = None
    opex_gbp_per_year: float | None = None
    lcoh_p_per_kwh: float | None = None
    npv_gbp: float | None = None
    irr_pct: float | None = None
    payback_years: float | None = None
    break_even_heat_price_p_per_kwh: float | None = None

    feasibility_score: float
    confidence_score: float
    confidence_band: str
    component_scores: dict[str, float]

    recommendation: Recommendation
    recommendation_rationale: list[str]
    next_action: str

    risk: RiskAssessmentRead | None = None
    confidence_detail: ConfidenceRead | None = None
    data_gaps: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    calculation_trace: list[CalculationTraceRead] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)

    evidence: list[EvidenceRead] = Field(default_factory=list)
    claims: list[ClaimRead] = Field(default_factory=list)
    regulatory_requirements: list[RegulatoryRequirementRead] = Field(default_factory=list)
    validation_actions: list[ValidationActionRead] = Field(default_factory=list)
    agent_outputs: dict[str, Any] | None = None
    report_markdown: str | None = None
    executive_summary: str | None = None


class ScenarioComparison(BaseModel):
    well_id: str
    scenarios: list[ScenarioResult]
    expected_lcoh_p_per_kwh: float | None = Field(
        default=None,
        description="Probability-weighted mean LCOH across scenarios with weights set.",
    )
    expected_npv_gbp: float | None = None
    spread_lcoh_p_per_kwh: float | None = Field(
        default=None, description="Max minus min LCOH: the width of the answer.",
    )
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------- projects
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    target_region: str | None = None
    well_ids: list[uuid.UUID] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ProjectRead(ORMBase):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    stage: str
    target_region: str | None = None
    target_scenario: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectRead):
    well_count: int = 0
    analyses: list[AnalysisSummary] = Field(default_factory=list)


class AnalysisSummary(ORMBase):
    id: uuid.UUID
    well_id: uuid.UUID
    status: str
    feasibility_score: float | None = None
    confidence_score: float | None = None
    recommendation: str | None = None
    progress_stage: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


# -------------------------------------------------------- dashboard
class NationalDashboard(BaseModel):
    """Headline figures for the national view."""

    total_wells: int
    wells_with_temperature: int
    wells_without_temperature: int
    candidate_wells: int = Field(
        description="Wells meeting the minimum screen: a temperature and an integrity status.",
    )
    high_potential_wells: int = Field(
        description="HIGH or MEDIUM PRIORITY recommendations.",
    )
    average_temperature_c: float | None = Field(
        default=None,
        description="Mean of recorded temperatures. Null when no well has one, rather "
        "than zero.",
    )
    average_depth_m: float | None = None
    total_estimated_thermal_capacity_mwt: float | None = Field(
        description="Sum of estimated thermal output. Estimated, not measured.",
    )
    total_estimated_thermal_capacity_status: str = EpistemicStatus.ESTIMATE.value
    nearby_heat_demand_opportunity_gwh: float | None = Field(
        description="Heat demand within 5 km of at least one well.",
    )
    wells_needing_more_data: int = Field(
        description="Wells whose confidence band is low, very low or unknown.",
    )

    recommendation_breakdown: dict[str, int] = Field(default_factory=dict)
    confidence_breakdown: dict[str, int] = Field(default_factory=dict)
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    purpose_breakdown: dict[str, int] = Field(default_factory=dict)
    region_breakdown: dict[str, int] = Field(default_factory=dict)
    score_histogram: list[dict[str, Any]] = Field(default_factory=list)
    risk_category_totals: dict[str, int] = Field(default_factory=dict)
    is_mock: bool = Field(
        description="True when any contributing dataset is synthetic.",
    )
    caveats: list[str] = Field(default_factory=list)


class CandidateRow(BaseModel):
    """One row of the candidate ranking table."""

    rank: int
    well_id: str
    # The key every well endpoint takes; `well_id` is the publisher's id and
    # cannot be used to open, assess or filter by a well.
    well_uuid: uuid.UUID | None = None
    well_name: str
    latitude: float
    longitude: float
    region: str | None = None
    status: str
    total_depth_m: float | None = None
    temperature_c: float | None = None
    temperature_status: str
    temperature_confidence: str
    nearest_building_distance_m: float | None = None
    annual_demand_kwh: float | None = None
    thermal_output_kw: float | None = None
    thermal_output_status: str
    capex_gbp: float | None = None
    lcoh_p_per_kwh: float | None = None
    feasibility_score: float | None = None
    confidence_score: float | None = None
    recommendation: str | None = None
    is_mock: bool = False


class CandidateTable(BaseModel):
    items: list[CandidateRow]
    total: int
    limit: int
    offset: int
    ranking_basis: str = Field(
        description="Which field the rows are ordered by, so the UI can label the "
        "column it is sorted on.",
    )
    includes_mock_data: bool = False


class MapFeature(BaseModel):
    """GeoJSON feature for the map layer."""

    type: str = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any]


class MapFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[MapFeature]
    spatial_dialect: str


# ------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=256)

    model_config = ConfigDict(extra="forbid")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 -- the OAuth2 scheme name, not a secret
    expires_in: int
    user: UserRead


class UserRead(ORMBase):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    tenant_id: uuid.UUID


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str = Field(description="'postgresql', 'sqlite', or 'unavailable'")
    spatial_dialect: str
    redis: str
    llm: str = Field(description="'anthropic', 'mock', or 'disabled'")
    is_mock_data: bool


TokenResponse.model_rebuild()
ProjectDetail.model_rebuild()
