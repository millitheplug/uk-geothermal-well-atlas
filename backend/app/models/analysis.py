"""Projects, analyses, scenarios, financial models, risks and validation actions."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AnalysisStage,
    AnalysisStatus,
    EpistemicStatus,
    GeothermalConfiguration,
)
from app.db.base import UUID, Base, UTCDateTime, created_at_col, updated_at_col

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.well import Well


class Analysis(Base):
    """One complete feasibility assessment of one well.

    Holds the deterministic outputs and the agent outputs side by side so a
    reader can see which numbers came from Python and which came from an LLM.
    The LLM never writes to the score fields.
    """

    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_well_created", "well_id", "created_at"),
        Index("ix_analyses_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scenarios.id", ondelete="SET NULL"), index=True
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AnalysisStatus.PENDING.value
    )
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False, default="0.1.0")
    agent_model: Mapped[str | None] = mapped_column(String(128))
    agent_provider: Mapped[str | None] = mapped_column(String(64))

    # ---- Deterministic scores (computed in Python, never by the LLM) ----
    feasibility_score: Mapped[float | None] = mapped_column(Float, index=True)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(String(32), index=True)
    recommendation_rationale: Mapped[str | None] = mapped_column(Text)
    score_components: Mapped[dict[str, Any] | None] = mapped_column(
        nullable=True, doc="{thermal: {score, weight, contribution}, ...}"
    )

    # ---- Engineering summary (deterministic) ---------------------------
    recommended_configuration: Mapped[str | None] = mapped_column(
        String(48), default=GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP.value
    )
    source_temperature_c: Mapped[float | None] = mapped_column(Float)
    temperature_status: Mapped[str | None] = mapped_column(String(16))
    flow_rate_lps: Mapped[float | None] = mapped_column(Float)
    thermal_output_kw: Mapped[float | None] = mapped_column(Float)
    thermal_output_mw: Mapped[float | None] = mapped_column(Float)
    thermal_output_status: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        default=EpistemicStatus.ESTIMATE.value,
        doc="Provenance label for thermal output. Never MEASURED unless a flow test exists.",
    )
    heat_pump_cop: Mapped[float | None] = mapped_column(Float)
    delivered_heat_kw: Mapped[float | None] = mapped_column(Float)
    network_length_m: Mapped[float | None] = mapped_column(Float)
    network_heat_loss_kw: Mapped[float | None] = mapped_column(Float)
    demand_matched_kw: Mapped[float | None] = mapped_column(Float)
    nearest_building_distance_m: Mapped[float | None] = mapped_column(Float)
    annual_heat_production_kwh: Mapped[float | None] = mapped_column(Float)

    # ---- Economics summary (deterministic) -----------------------------
    capex_gbp: Mapped[float | None] = mapped_column(Float)
    opex_gbp_per_year: Mapped[float | None] = mapped_column(Float)
    lcoh_p_per_kwh: Mapped[float | None] = mapped_column(Float)
    npv_gbp: Mapped[float | None] = mapped_column(Float)
    irr_pct: Mapped[float | None] = mapped_column(Float)
    payback_years: Mapped[float | None] = mapped_column(Float)
    break_even_heat_price_p_per_kwh: Mapped[float | None] = mapped_column(Float)

    # ---- Aggregate risk -------------------------------------------------
    risk_score: Mapped[float | None] = mapped_column(Float, index=True)
    risk_count: Mapped[int | None] = mapped_column(Integer)
    critical_risk_count: Mapped[int | None] = mapped_column(Integer)

    # ---- Agent and report outputs --------------------------------------
    agent_outputs: Mapped[dict[str, Any] | None] = mapped_column(
        nullable=True, doc="Structured JSON per agent. Free text is not stored here."
    )
    report_uri: Mapped[str | None] = mapped_column(String(1024))
    report_markdown: Mapped[str | None] = mapped_column(Text)
    executive_summary: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    data_gaps: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    progress_stage: Mapped[str | None] = mapped_column(
        String(32), default=AnalysisStage.DATA_VALIDATION.value
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at_col()

    well: Mapped[Well] = relationship(back_populates="analyses")
    project: Mapped[Project | None] = relationship(back_populates="analyses")
    scenario: Mapped[Scenario | None] = relationship(back_populates="analyses")
    financial_model: Mapped[FinancialModel | None] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", uselist=False
    )
    risks: Mapped[list[Risk]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    validation_actions: Mapped[list[ValidationAction]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class Scenario(Base):
    """Bear / base / bull parameter set."""

    __tablename__ = "scenarios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(
        nullable=False,
        doc="Engineering parameter overrides, e.g. {flow_rate_lps: 25, capex_gbp: 2.1e6}",
    )
    probability_weight: Mapped[float | None] = mapped_column(
        Float, doc="Weight for probability-weighted expected value across scenarios."
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_col()

    analyses: Mapped[list[Analysis]] = relationship(back_populates="scenario")


class FinancialModel(Base):
    """Full cash-flow model for one analysis and scenario."""

    __tablename__ = "financial_models"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    project_lifetime_years: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_rate_pct: Mapped[float] = mapped_column(Float, nullable=False)
    electricity_price_p_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    heat_price_p_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)

    initial_capex_gbp: Mapped[float] = mapped_column(Float, nullable=False)
    capex_breakdown: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    annual_opex_gbp: Mapped[float] = mapped_column(Float, nullable=False)
    opex_breakdown: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    annual_revenue_gbp: Mapped[float | None] = mapped_column(Float)

    lcoh_p_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    npv_gbp: Mapped[float] = mapped_column(Float, nullable=False)
    irr_pct: Mapped[float | None] = mapped_column(Float)
    payback_years: Mapped[float | None] = mapped_column(Float)
    discounted_payback_years: Mapped[float | None] = mapped_column(Float)
    break_even_heat_price_p_per_kwh: Mapped[float | None] = mapped_column(Float)
    break_even_electricity_price_p_per_kwh: Mapped[float | None] = mapped_column(Float)

    cash_flows: Mapped[dict[str, Any] | None] = mapped_column(
        nullable=True, doc="{year: {capex, opex, revenue, net_cash_flow, discounted}}"
    )
    calculation_traces: Mapped[dict[str, Any] | None] = mapped_column(
        nullable=True, doc="Every intermediate function call with its formula."
    )
    is_viable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Deterministic threshold test only. Never a statement of commercial viability.",
    )
    viability_caveat: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    analysis: Mapped[Analysis] = relationship(back_populates="financial_model")


class Risk(Base):
    __tablename__ = "risks"
    __table_args__ = (Index("ix_risks_well_category", "well_id", "category"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )

    category: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    probability: Mapped[str] = mapped_column(String(24), nullable=False)
    probability_numeric: Mapped[float] = mapped_column(Float, nullable=False)
    impact: Mapped[str] = mapped_column(String(24), nullable=False)
    impact_numeric: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        doc="0-1. How little we know about the probability itself. Separate from risk_score.",
    )
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    uncertainty_adjusted_score: Mapped[float | None] = mapped_column(
        Float,
        doc="risk_score widened by uncertainty. Used for the dashboard's "
        "'needs data' signal so an unknown risk is not hidden.",
    )
    severity: Mapped[str] = mapped_column(String(24), nullable=False)

    evidence: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    mitigation: Mapped[str | None] = mapped_column(Text)
    validation_action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("validation_actions.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = created_at_col()

    analysis: Mapped[Analysis | None] = relationship(back_populates="risks")


class RegulatoryRequirement(Base):
    """A consent, licence or obligation that applies to geothermal reuse."""

    __tablename__ = "regulatory_requirements"
    __table_args__ = (Index("ix_regreq_well", "well_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), index=True
    )
    jurisdiction: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    authority: Mapped[str | None] = mapped_column(String(255))
    applies_to_configuration: Mapped[str | None] = mapped_column(String(48))
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    typical_lead_time_months: Mapped[float | None] = mapped_column(Float)
    estimated_cost_gbp: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="FACT")
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_date: Mapped[date | None] = mapped_column(Date)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_col()


class ValidationAction(Base):
    """A concrete next step that would retire a specific uncertainty."""

    __tablename__ = "validation_actions"
    __table_args__ = (Index("ix_validation_well_priority", "well_id", "priority"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )

    action_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rationale: Mapped[str | None] = mapped_column(Text)
    addresses_risk_ids: Mapped[dict[str, Any] | None] = mapped_column(
        nullable=True, doc="List of risk ids this action would retire."
    )
    addresses_data_gaps: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    estimated_cost_gbp: Mapped[float | None] = mapped_column(Float)
    estimated_duration_days: Mapped[float | None] = mapped_column(Float)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    outcome_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()

    analysis: Mapped[Analysis | None] = relationship(back_populates="validation_actions")
