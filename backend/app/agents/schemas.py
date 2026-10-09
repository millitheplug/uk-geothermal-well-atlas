"""Structured output schemas for the eleven agents.

Every agent returns one of these. Free text never travels between agents, and
none of these models contains a field that would let a language model state a
number it has not been given: agents receive the deterministic results as
context and can only describe them, label them and explain them.

``FactRecord`` is the backbone. An agent that makes an assertion must attach a
source; ``fact_type`` forces it to declare the epistemic status of that
assertion rather than defaulting to confident prose.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import EpistemicStatus, Recommendation

#: The six labels an agent must choose from for anything it asserts.
FactType = Literal["FACT", "MEASURED", "DERIVED", "ESTIMATE", "ASSUMPTION", "UNKNOWN"]


class FactRecord(BaseModel):
    """One assertion with its provenance and epistemic status."""

    statement: str = Field(
        min_length=1,
        description="What is asserted, in one sentence.",
    )
    fact_type: FactType = Field(
        description="Whether this is a documented fact, a measurement, a derived "
        "value, an estimate, an assumption, or an admitted unknown.",
    )
    source: str | None = Field(
        default=None,
        description="Source of the assertion. Required unless fact_type is ASSUMPTION "
        "or UNKNOWN.",
    )
    source_url: str | None = None
    field_name: str | None = Field(
        default=None, description="Which well field this assertion describes."
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("source")
    @classmethod
    def _require_source_for_claims(cls, v: str | None, info: Any) -> str | None:
        fact_type = (info.data or {}).get("fact_type")
        if fact_type in ("FACT", "MEASURED", "DERIVED", "ESTIMATE") and not v:
            raise ValueError(
                f"a {fact_type} assertion must cite a source; use ASSUMPTION or "
                "UNKNOWN instead if none exists"
            )
        return v


class UnknownRecord(BaseModel):
    """Something the agent could not determine, and why."""

    item: str
    reason: str = Field(
        description="Why it is unknown: no data, inaccessible data, or data that "
        "conflicts.",
    )
    impact: str = Field(description="What this uncertainty prevents being concluded.")
    resolution_action: str | None = Field(
        default=None, description="What would resolve it, if that is known.",
    )


class NextStep(BaseModel):
    action: str
    rationale: str
    priority: Literal["critical", "high", "medium", "low"]
    estimated_cost_gbp: float | None = Field(default=None, ge=0)
    estimated_duration_days: float | None = Field(default=None, ge=0)


class AgentBase(BaseModel):
    """Fields common to every agent output."""

    facts: list[FactRecord] = Field(
        default_factory=list,
        description="Assertions this agent makes. Each carries its own provenance.",
    )
    unknowns: list[UnknownRecord] = Field(default_factory=list)
    confidence_notes: str | None = None
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="This agent's confidence in its own interpretation.",
    )
    recommended_next_steps: list[NextStep] = Field(default_factory=list)


# ------------------------------------------------------------- agents
class WellDataInterpretation(AgentBase):
    """WellDataAgent: what the records say, and what they do not."""

    summary: str
    data_quality: Literal["good", "partial", "poor", "very_poor"]
    well_name_confirmed: bool = Field(
        description="False when the well name in the source is ambiguous or duplicated.",
    )


class GeothermalInterpretation(AgentBase):
    """GeothermalAgent: formation suitability and configuration options."""

    summary: str
    suitability_notes: list[str]
    recommended_configurations: list[
        Literal[
            "closed_loop",
            "open_loop",
            "closed_loop_plus_heat_pump",
            "open_loop_plus_heat_pump",
        ]
    ]
    permeability_status: str = Field(
        description="Whether permeability is known, which governs deliverability.",
    )


class WellIntegrityAssessment(AgentBase):
    """WellIntegrityAgent: can this wellbore be worked and reused?"""

    summary: str
    reuse_viability: Literal["good", "plausible", "compromised", "not_viable", "unknown"]
    requires_intervention: bool
    corrosion_risk: Literal["low", "moderate", "high", "unknown"]
    scaling_risk: Literal["low", "moderate", "high", "unknown"]


class HeatDemandAnalysis(AgentBase):
    """HeatDemandAgent: is there enough heat demand near this well?"""

    summary: str
    total_annual_demand_kwh: float | None = None
    nearest_building_distance_m: float | None = None
    demand_to_output_ratio: float | None = Field(
        default=None,
        description="Nearby annual demand divided by the well's maximum annual output. "
        "Below about 0.25 most of the output would have no customer.",
    )
    assessment_notes: list[str] = Field(default_factory=list)


class HeatNetworkAnalysis(AgentBase):
    """HeatNetworkAgent: can the heat be delivered?"""

    summary: str
    estimated_pipe_length_m: float | None = None
    estimated_loss_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    feasibility_notes: list[str] = Field(default_factory=list)
    alternative_approaches: list[str] = Field(default_factory=list)


class EngineeringAssessment(AgentBase):
    """EngineeringAgent: describes the Python results. Computes nothing itself."""

    summary: str
    thermal_output_status: str = Field(
        description="Must mirror the deterministic status. An agent may not upgrade "
        "ESTIMATE to MEASURED.",
    )
    configuration_rationale: str
    calculation_notes: str = Field(
        description="Statement of which engine produced the numbers.",
    )
    sensitivity_notes: str

    model_config = ConfigDict(extra="forbid")


class EconomicAssessment(AgentBase):
    """EconomicAgent: interprets the financial model without altering it."""

    summary: str
    lcoh_vs_heat_price_assessment: Literal["favourable", "marginal", "unfavourable", "unknown"]
    capex_notes: str
    viability_caveat: str = Field(
        description="Must state that these figures do not constitute commercial "
        "viability.",
    )
    break_even_heat_price_p_per_kwh: float | None = None


class RegulatoryAnalysis(AgentBase):
    """RegulatoryAgent: consents, obligations and programme."""

    summary: str
    consent_timeline_months: float | None = Field(default=None, ge=0)
    key_obstacles: list[str] = Field(default_factory=list)
    recommendation_notes: str


class RiskAssessmentSummary(AgentBase):
    """RiskAgent: narrative over the deterministic risk register."""

    summary: str
    top_risks: list[dict[str, Any]] = Field(default_factory=list)
    risk_drivers: list[str] = Field(default_factory=list)
    mitigation_overview: str


class FeasibilityAssessment(AgentBase):
    """FeasibilityAgent: explains the deterministic score. Does not set it."""

    summary: str
    overall_assessment: Literal["strong", "promising", "marginal", "weak", "not_viable"]
    recommendation: Recommendation = Field(
        description="Must equal the deterministic recommendation. The orchestrator "
        "rejects any mismatch.",
    )
    recommendation_reasoning: str
    confidence_caveat: str

    model_config = ConfigDict(extra="forbid")


class ReportSection(BaseModel):
    title: str
    content: str
    evidence_ids: list[str] = Field(default_factory=list)


class ReportOutput(BaseModel):
    """ReportAgent: the assembled screening report."""

    executive_summary: str
    sections: list[ReportSection]
    overall_recommendation: Recommendation
    disclaimers: list[str] = Field(
        default_factory=list,
        description="Statements the report must not omit, regardless of the input data.",
    )


#: Stage order used by the orchestrator and the progress UI.
AGENT_ORDER: tuple[type[BaseModel], ...] = (
    WellDataInterpretation,
    GeothermalInterpretation,
    WellIntegrityAssessment,
    HeatDemandAnalysis,
    HeatNetworkAnalysis,
    EngineeringAssessment,
    EconomicAssessment,
    RegulatoryAnalysis,
    RiskAssessmentSummary,
    FeasibilityAssessment,
    ReportOutput,
)


AGENT_SCHEMA_BY_NAME: dict[str, type[BaseModel]] = {
    s.__name__: s for s in AGENT_ORDER
}

AGENT_NAMES: tuple[str, ...] = (
    "WellDataAgent",
    "GeothermalAgent",
    "WellIntegrityAgent",
    "HeatDemandAgent",
    "HeatNetworkAgent",
    "EngineeringAgent",
    "EconomicAgent",
    "RegulatoryAgent",
    "RiskAgent",
    "FeasibilityAgent",
    "ReportAgent",
)
