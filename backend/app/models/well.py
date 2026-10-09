"""Well domain: identity, geometry, temperature, integrity, logs.

Design note on temperature: `WellTemperature` stores the *observations*. The
singleton `Well` row stores a rolled-up `temperature_c` for map rendering and
sorting, but every scoring path is required to read the observation table and
to carry the epistemic status through. A well with no temperature observation
has `temperature_c IS NULL` and `temperature_status = UNKNOWN`; it is never
back-filled with a regional average.
"""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    DataConfidence,
    EpistemicStatus,
    GeothermalConfiguration,
    OriginalPurpose,
    WellIntegrityStatus,
    WellStatus,
)
from app.db.base import UUID, Base, UTCDateTime, created_at_col, updated_at_col

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Well(Base):
    __tablename__ = "wells"
    __table_args__ = (
        UniqueConstraint("source", "source_record_id", name="uq_wells_source_source_record_id"),
        Index("ix_wells_status_temperature", "status", "temperature_c"),
        # No tenant index: wells are national reference data and carry no
        # tenant_id. Access is controlled through the tenant-scoped tables that
        # reference them, see app.core.security.scoped_well_query.
        Index("ix_wells_region_status", "region", "status"),
        Index("ix_wells_score", "feasibility_score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ---- Identity -------------------------------------------------------
    well_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    well_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        doc="Stable platform identifier, e.g. 'UK-GB-001/02'. Surrogate for "
        "operator-specific names which are frequently duplicated.",
    )
    operator: Mapped[str | None] = mapped_column(String(255), index=True)
    licence: Mapped[str | None] = mapped_column(String(128), index=True)
    licence_type: Mapped[str | None] = mapped_column(String(64))

    # ---- Provenance (see models/base_mixins.py) -------------------------
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_record_id: Mapped[str | None] = mapped_column(String(128))
    dataset_version: Mapped[str | None] = mapped_column(String(64))
    source_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # ---- Location -------------------------------------------------------
    latitude: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    county: Mapped[str | None] = mapped_column(String(128), index=True)
    region: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
        doc="ITL/ITL-derived region used for map filters.",
    )
    onshore: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    grid_reference: Mapped[str | None] = mapped_column(String(32))

    # ---- Status and purpose --------------------------------------------
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=WellStatus.UNKNOWN.value)
    status_raw: Mapped[str | None] = mapped_column(
        String(64), doc="Verbatim source value before normalisation."
    )
    original_purpose: Mapped[str] = mapped_column(
        String(32), nullable=False, default=OriginalPurpose.UNKNOWN.value
    )
    drilling_year: Mapped[int | None] = mapped_column(Integer, index=True)
    commissioned_date: Mapped[date | None] = mapped_column(Date)

    # ---- Geometry -------------------------------------------------------
    total_depth_m: Mapped[float | None] = mapped_column(Float)
    tvd_m: Mapped[float | None] = mapped_column(Float)
    md_m: Mapped[float | None] = mapped_column(Float)
    max_deviation_deg: Mapped[float | None] = mapped_column(Float)
    is_deviated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_horizontal: Mapped[bool] = mapped_column(Boolean, default=False)

    # ---- Formation ------------------------------------------------------
    formation: Mapped[str | None] = mapped_column(String(255), index=True)
    formation_code: Mapped[str | None] = mapped_column(String(64))
    target_formation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("formations.id", ondelete="SET NULL"), index=True
    )
    lithology: Mapped[str | None] = mapped_column(String(128))
    basin: Mapped[str | None] = mapped_column(String(128), index=True)

    # ---- Rolled-up temperature (see module docstring) -------------------
    temperature_c: Mapped[float | None] = mapped_column(Float, index=True)
    temperature_depth_m: Mapped[float | None] = mapped_column(Float)
    temperature_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.UNKNOWN.value
    )
    temperature_source: Mapped[str | None] = mapped_column(String(255))
    temperature_confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DataConfidence.UNKNOWN.value
    )
    temperature_variability_c: Mapped[float | None] = mapped_column(
        Float,
        doc="Observed spread across multiple measurements. Large values depress "
        "the thermal score because they indicate a heterogeneous or "
        "poorly characterised reservoir.",
    )

    # ---- Pressure -------------------------------------------------------
    bottomhole_pressure_bar: Mapped[float | None] = mapped_column(Float)
    static_pressure_bar: Mapped[float | None] = mapped_column(Float)
    flowing_pressure_bar: Mapped[float | None] = mapped_column(Float)
    pressure_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.UNKNOWN.value
    )

    # ---- Construction ---------------------------------------------------
    casing_string: Mapped[str | None] = mapped_column(Text)
    completion_type: Mapped[str | None] = mapped_column(String(64))
    completion_date: Mapped[date | None] = mapped_column(Date)
    plugged_and_abandoned_date: Mapped[date | None] = mapped_column(Date)
    has_wellhead: Mapped[bool | None] = mapped_column(Boolean)
    loggable: Mapped[bool | None] = mapped_column(
        Boolean, doc="Can temperature be logged? Gates the validation plan."
    )

    # ---- Overall data confidence ---------------------------------------
    data_confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DataConfidence.UNKNOWN.value
    )
    data_confidence_score: Mapped[float | None] = mapped_column(Float)
    data_completeness: Mapped[float | None] = mapped_column(
        Float, doc="Fraction of required fields populated, 0-1."
    )
    known_data_gaps: Mapped[dict[str, Any] | None] = mapped_column(
        nullable=True, doc="JSON: {field: 'why it is missing'}"
    )

    # ---- Cached analysis results (recomputed by background workers) ------
    feasibility_score: Mapped[float | None] = mapped_column(Float, index=True)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(String(32), index=True)
    analysed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    analysis_version: Mapped[str | None] = mapped_column(String(16))

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    # ---- Relationships --------------------------------------------------
    temperatures: Mapped[list[WellTemperature]] = relationship(
        back_populates="well", cascade="all, delete-orphan", lazy="selectin"
    )
    integrity: Mapped[WellIntegrity | None] = relationship(
        back_populates="well", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    logs: Mapped[list[WellLog]] = relationship(back_populates="well", cascade="all, delete-orphan")
    analyses: Mapped[list[Analysis]] = relationship(
        back_populates="well", cascade="all, delete-orphan"
    )

    @property
    def has_reusable_casing(self) -> bool:
        """Whether a production casing string is documented.

        Not a judgement about integrity - see WellIntegrity for that.
        """
        return bool(self.casing_string and self.casing_string.strip())


class WellTemperature(Base):
    """A single temperature observation with full provenance.

    The geothermal case rests on these rows, so each one records how the
    number came about: a static bottom-hole survey, a production log, a
    circulation test, or a regional estimate interpolated from neighbours.
    """

    __tablename__ = "well_temperatures"
    __table_args__ = (Index("ix_well_temp_well_depth", "well_id", "depth_m"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), nullable=False, index=True
    )

    measured_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    depth_m: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)

    measurement_method: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="e.g. 'static_bht', 'max_dynamic', 'production_log', 'circulation_test', "
        "'regional_estimate'",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.MEASURED.value
    )
    confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DataConfidence.MEDIUM.value
    )

    geothermal_gradient_c_per_km: Mapped[float | None] = mapped_column(Float)
    is_final_stabilised: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        doc="False when the value is a transient early-time reading that has not "
        "thermally equilibrated. Such values systematically overstate the "
        "sustained temperature.",
    )
    shut_in_hours: Mapped[float | None] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_record_id: Mapped[str | None] = mapped_column(String(128))
    source_title: Mapped[str | None] = mapped_column(String(512))
    source_date: Mapped[date | None] = mapped_column(Date)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)

    well: Mapped[Well] = relationship(back_populates="temperatures")


class WellIntegrity(Base):
    """One-to-one assessment of whether the wellbore can be worked and reused.

    Deliberately separated from `Well.casing_string`: the presence of a casing
    record is a fact, while whether that casing is serviceable is an
    engineering judgement that carries its own evidence and confidence.
    """

    __tablename__ = "well_integrity"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WellIntegrityStatus.UNKNOWN.value
    )
    status_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.UNKNOWN.value
    )
    confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DataConfidence.UNKNOWN.value
    )

    # ---- Condition factors (each 0-1, higher is better) -----------------
    casing_condition_score: Mapped[float | None] = mapped_column(Float)
    wellhead_condition_score: Mapped[float | None] = mapped_column(Float)
    access_score: Mapped[float | None] = mapped_column(Float)
    abandonment_score: Mapped[float | None] = mapped_column(
        Float, doc="1.0 = not abandoned, 0.0 = properly abandoned and made safe."
    )
    productive_perforations: Mapped[str | None] = mapped_column(Text)
    corrosion_evidence: Mapped[str | None] = mapped_column(Text)
    scaling_evidence: Mapped[str | None] = mapped_column(Text)
    gas_hazard: Mapped[bool | None] = mapped_column(Boolean)

    requires_reequipment: Mapped[bool | None] = mapped_column(Boolean)
    estimated_recompletion_capex_gbp: Mapped[float | None] = mapped_column(Float)
    estimated_recompletion_capex_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.UNKNOWN.value
    )

    last_integrity_check_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    unknown_reasons: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    well: Mapped[Well] = relationship(back_populates="integrity")


class WellLog(Base):
    """Header record for a log or survey suite held against the well.

    Log curves themselves live in object storage; this row is the index entry
    with enough metadata to judge whether reading them would resolve the
    temperature or integrity unknowns.
    """

    __tablename__ = "well_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), nullable=False, index=True
    )
    log_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    logged_at: Mapped[date | None] = mapped_column(Date)
    run_number: Mapped[str | None] = mapped_column(String(64))
    top_depth_m: Mapped[float | None] = mapped_column(Float)
    bottom_depth_m: Mapped[float | None] = mapped_column(Float)
    storage_uri: Mapped[str | None] = mapped_column(String(1024))
    storage_etag: Mapped[str | None] = mapped_column(String(128))
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    content_checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    has_temperature_curve: Mapped[bool] = mapped_column(Boolean, default=False)
    tool_company: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=EpistemicStatus.MEASURED.value)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    is_public_domain: Mapped[bool] = mapped_column(Boolean, default=True)
    licence: Mapped[str | None] = mapped_column(String(255))

    well: Mapped[Well] = relationship(back_populates="logs")


class WellRecommendationColumns:
    """Cached recommendation columns, for reuse by other mapped classes.

    A plain mixin of ``mapped_column`` calls rather than a ``Base`` subclass:
    inheriting from ``Base`` without a table makes SQLAlchemy try to map a class
    that is only ever meant to be mixed in.
    """

    recommendation: Mapped[str | None] = mapped_column(
        String(32),
        index=True,
        doc="Cached deterministic recommendation, so map colouring and ranking "
        "stay cheap without recomputing.",
    )
    feasible_configuration: Mapped[str | None] = mapped_column(
        String(48),
        default=GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP.value,
        doc="Configuration the last assessment settled on.",
    )
