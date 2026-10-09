"""Evidence, assumptions and datasets: the traceability substrate.

The rule this module exists to enforce: nothing is asserted without a claim
record, and no claim record exists without a source. `Evidence` holds the
source artefact; `Claim` is the sentence an agent or a calculation made about
it; `Assumption` records the analyst's choices; `Dataset` records provenance
for everything ingested.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

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

from app.core.enums import EpistemicStatus, SourceReliability
from app.db.base import UUID, Base, UTCDateTime, created_at_col


class Dataset(Base):
    """One ingested dataset. Registered before its rows are written.

    Every adapter must register a Dataset and attach its id to the rows it
    writes, so that "which version of which download is this?" always has an
    answer.
    """

    __tablename__ = "datasets"
    __table_args__ = (
        # `source` carries index=True on the column, which the naming convention
        # already renders as ix_datasets_source. Declaring it again here would
        # create the same index twice.
        UniqueConstraint("source", "version", name="uq_datasets_source_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, doc="Adapter id, e.g. 'nsta', 'bgs_wells'"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    download_date: Mapped[date | None] = mapped_column(Date)
    published_date: Mapped[date | None] = mapped_column(Date)
    licence: Mapped[str | None] = mapped_column(String(512))
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    reliability: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SourceReliability.TIER_C.value
    )
    quality_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, doc="0-1, computed by data_validation."
    )
    row_count: Mapped[int | None] = mapped_column(Integer)
    validation_report_uri: Mapped[str | None] = mapped_column(String(1024))
    is_mock: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="True for synthetic development data. Mock rows are excluded from "
        "any production report and are watermarked in the API response.",
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="registered")
    validation_summary: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    registered_at: Mapped[datetime] = created_at_col()
    last_ingested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Evidence(Base):
    """A source document, log suite, dataset row or calculation trace.

    `reliability` is the trusted value from `EvidenceReliability`;
    `relevance` and `quality` are assigned per use, because the same BGS
    report may be highly relevant to one well and only contextual to another.
    """

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_well", "well_id"),
        Index("ix_evidence_reliability", "reliability"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), index=True
    )

    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_title: Mapped[str | None] = mapped_column(String(512))
    source_date: Mapped[date | None] = mapped_column(Date)
    document_type: Mapped[str | None] = mapped_column(
        String(64),
        doc="well_report | log_suite | bgs_publication | nsta_record | tariff_sheet | "
        "assumption_note | calculation_trace",
    )

    reliability: Mapped[float] = mapped_column(
        Float, nullable=False, doc="0-1 trusted source reliability"
    )
    relevance: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, doc="0-1 relevance to the specific claim"
    )
    quality: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, doc="0-1 quality of the measurement itself"
    )
    excerpt: Mapped[str | None] = mapped_column(Text, doc="Verbatim supporting text.")
    page_reference: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.MEASURED.value
    )
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    extra: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = created_at_col()

    claims: Mapped[list[Claim]] = relationship(back_populates="evidence", cascade="all, delete-orphan")


class Claim(Base):
    """A single assertion, bound to its evidence and to the field it describes.

    Stored rather than computed because reports, API responses and audit
    exports all need to answer "why does the platform say this?".
    """

    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_well_field", "well_id", "field_name"),
        Index("ix_claims_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), index=True
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"), index=True
    )
    assumption_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assumptions.id", ondelete="SET NULL"), index=True
    )

    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(16))
    agent: Mapped[str | None] = mapped_column(
        String(64), doc="Which agent produced this claim."
    )
    is_critical: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        doc="Critical claims gate the recommendation: temperature, integrity, economics.",
    )
    contradicted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()

    evidence: Mapped[Evidence | None] = relationship(back_populates="claims")


class Assumption(Base):
    """An analyst or system choice that is not an observation.

    Assumptions are first-class rows rather than literals in code so that a
    scenario can differ from the base case, and so the report can list every
    input that would change the answer if it were wrong.
    """

    __tablename__ = "assumptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(
        nullable=True, doc="{value, unit, low, high}"
    )
    unit: Mapped[str | None] = mapped_column(String(32))
    low_value: Mapped[float | None] = mapped_column(Float)
    high_value: Mapped[float | None] = mapped_column(Float)
    distribution: Mapped[str | None] = mapped_column(
        String(32), doc="uniform | triangular | normal | lognormal. Required for Monte Carlo."
    )
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL")
    )
    scenario: Mapped[str | None] = mapped_column(String(32), index=True)
    is_user_supplied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_col()


class CalculationTrace(Base):
    """Persisted record of one deterministic calculation.

    Mirrors the in-memory `CalcResult` so a finished financial model can be
    audited input by input without re-running it.
    """

    __tablename__ = "calculation_traces"
    __table_args__ = (Index("ix_calc_trace_well_function", "well_id", "function_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    function_name: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[float | None] = mapped_column(Float)
    result_unit: Mapped[str | None] = mapped_column(String(32))
    intermediate_values: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    warnings: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False, default="0.1.0")
    created_at: Mapped[datetime] = created_at_col()
