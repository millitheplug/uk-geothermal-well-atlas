"""Geological domain: stratigraphy, formations and the geology attached to a well."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import EpistemicStatus
from app.db.base import UUID, Base, UTCDateTime, created_at_col, updated_at_col


class Formation(Base):
    """A named geological unit in the UK onshore stratigraphy."""

    __tablename__ = "formations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code: Mapped[str | None] = mapped_column(String(64), index=True)
    age: Mapped[str | None] = mapped_column(String(64))
    lithology: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("formations.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))

    parent: Mapped[Formation | None] = relationship(remote_side="Formation.id", back_populates="children")
    children: Mapped[list[Formation]] = relationship(back_populates="parent")


class Geology(Base):
    """Geological context for a single well: gradient, permeability, chemistry.

    These are the properties that determine whether a hot formation can
    actually deliver water at rate, and they are the reason a high
    temperature alone is not enough.
    """

    __tablename__ = "geology"
    __table_args__ = (Index("ix_geology_well", "well_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    well_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), nullable=False, index=True
    )
    formation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("formations.id", ondelete="SET NULL")
    )
    geothermal_gradient_c_per_km: Mapped[float | None] = mapped_column(Float)
    surface_heat_flow_mw_m2: Mapped[float | None] = mapped_column(Float)
    permeability_md: Mapped[float | None] = mapped_column(Float)
    porosity_pct: Mapped[float | None] = mapped_column(Float)
    net_thickness_m: Mapped[float | None] = mapped_column(Float)
    reservoir_lithology: Mapped[str | None] = mapped_column(String(128))
    confining_unit: Mapped[str | None] = mapped_column(String(255))

    # Water chemistry drives scaling and corrosion risk. Recorded whether or not
    # analysis exists, with `chemistry_status` making the distinction explicit.
    water_salinity_ppt: Mapped[float | None] = mapped_column(Float)
    water_ph: Mapped[float | None] = mapped_column(Float)
    scaling_tendency: Mapped[str | None] = mapped_column(String(64))
    corrosion_tendency: Mapped[str | None] = mapped_column(String(64))
    chemistry_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.UNKNOWN.value
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.UNKNOWN.value
    )
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class GeothermalSetting(Base):
    """Regional geothermal character of a basin or licence area.

    Populated from BGS geothermal publications. Used for context in reports and
    for the geology stage of the agent pipeline - never used to substitute a
    measured well temperature.
    """

    __tablename__ = "geothermal_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    region: Mapped[str | None] = mapped_column(String(64), index=True)
    basin: Mapped[str | None] = mapped_column(String(128), index=True)
    typical_gradient_c_per_km: Mapped[float | None] = mapped_column(Float)
    typical_depth_min_m: Mapped[float | None] = mapped_column(Float)
    typical_depth_max_m: Mapped[float | None] = mapped_column(Float)
    estimated_potential_mw: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.ESTIMATE.value
    )
    summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_date: Mapped[date | None] = mapped_column(Date)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)

    settings_extra: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
