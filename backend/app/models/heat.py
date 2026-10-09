"""Heat side of the model: buildings, demand, networks and prices."""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import EpistemicStatus
from app.db.base import UUID, Base, created_at_col, updated_at_col


class Building(Base):
    """A heat off-taker: domestic, commercial or industrial."""

    __tablename__ = "buildings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source", "source_record_id", name="uq_buildings_tenant_id_source_source_record_id"
        ),
        Index("ix_buildings_tenant_lat_lon", "tenant_id", "latitude", "longitude"),
        Index("ix_buildings_heat_demand", "annual_heat_demand_kwh"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    building_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True, doc="domestic | commercial | industrial | public"
    )
    postcode: Mapped[str | None] = mapped_column(String(16), index=True)
    address_reference: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    region: Mapped[str | None] = mapped_column(String(64), index=True)

    floor_area_m2: Mapped[float | None] = mapped_column(Float)
    construction_year: Mapped[int | None] = mapped_column(Integer)
    annual_heat_demand_kwh: Mapped[float | None] = mapped_column(Float, index=True)
    peak_heat_demand_kw: Mapped[float | None] = mapped_column(Float)
    load_factor: Mapped[float | None] = mapped_column(Float)
    current_heating_technology: Mapped[str | None] = mapped_column(String(64))
    current_fuel: Mapped[str | None] = mapped_column(String(64))
    required_supply_temperature_c: Mapped[float | None] = mapped_column(
        Float, doc="Flow temperature the emitter needs. Governs whether a given "
        "source temperature is usable directly or needs a heat pump."
    )
    connection_potential: Mapped[str | None] = mapped_column(
        String(32),
        index=True,
        doc="high | medium | low | unknown. Whether a connection is technically and "
        "commercially plausible at this address.",
    )
    connection_potential_reason: Mapped[str | None] = mapped_column(Text)
    is_connected_to_network: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.ESTIMATE.value
    )
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_record_id: Mapped[str | None] = mapped_column(String(128))
    dataset_version: Mapped[str | None] = mapped_column(String(64))
    source_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = created_at_col()


class HeatDemand(Base):
    """Aggregate demand for an area, typically a postcode sector or LSOA.

    Separate from `Building` because demand zoning data is published at
    settlement level, not per address. The national dashboard aggregates
    from here.
    """

    __tablename__ = "heat_demands"
    __table_args__ = (
        Index("ix_heat_demand_area_lat_lon", "latitude", "longitude"),
        Index("ix_heat_demand_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    area_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    area_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="postcode_sector", doc="postcode_sector | lsoa | lau"
    )
    area_name: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    region: Mapped[str | None] = mapped_column(String(64), index=True)

    population: Mapped[int | None] = mapped_column(Integer)
    household_count: Mapped[int | None] = mapped_column(Integer)
    total_annual_demand_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    domestic_share_pct: Mapped[float | None] = mapped_column(Float)
    peak_demand_kw: Mapped[float | None] = mapped_column(Float)
    gas_network_present: Mapped[bool | None] = mapped_column(Boolean)
    average_supply_temperature_c: Mapped[float | None] = mapped_column(Float)
    upgrade_potential_score: Mapped[float | None] = mapped_column(
        Float, doc="0-1 published readiness score where available."
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.ESTIMATE.value
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_record_id: Mapped[str | None] = mapped_column(String(128))
    dataset_version: Mapped[str | None] = mapped_column(String(64))
    source_date: Mapped[date | None] = mapped_column(Date)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = created_at_col()


class HeatNetwork(Base):
    """An existing or planned district heating network."""

    __tablename__ = "heat_networks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    operator: Mapped[str | None] = mapped_column(String(255))
    centre_latitude: Mapped[float | None] = mapped_column(Float, index=True)
    centre_longitude: Mapped[float | None] = mapped_column(Float, index=True)

    existing: Mapped[bool] = mapped_column(Boolean, default=False)
    operational: Mapped[bool | None] = mapped_column(Boolean)
    network_type: Mapped[str | None] = mapped_column(
        String(32), doc="district | communal | industrial estate | planned"
    )
    current_heat_source: Mapped[str | None] = mapped_column(String(64))
    current_heat_source_capacity_mw: Mapped[float | None] = mapped_column(Float)
    flow_temperature_c: Mapped[float | None] = mapped_column(Float)
    return_temperature_c: Mapped[float | None] = mapped_column(Float)
    network_length_m: Mapped[float | None] = mapped_column(Float)
    connected_buildings: Mapped[int | None] = mapped_column(Integer)
    annual_delivered_heat_gwh: Mapped[float | None] = mapped_column(Float)
    spare_capacity_mw: Mapped[float | None] = mapped_column(Float)
    reinforcement_required: Mapped[bool | None] = mapped_column(Boolean)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.ESTIMATE.value
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_date: Mapped[date | None] = mapped_column(Date)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class EnergyPrice(Base):
    """A dated tariff used as a financial input.

    Financial models store the price id they used, so a model can always be
    re-run against the price book current at the time.
    """

    __tablename__ = "energy_prices"
    __table_args__ = (UniqueConstraint("fuel", "valid_from", name="uq_energy_prices_fuel_valid_from"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fuel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    price_p_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    standing_charge_p_per_kwh: Mapped[float | None] = mapped_column(Float)
    levies_p_per_kwh: Mapped[float | None] = mapped_column(Float)
    carbon_price_p_per_kwh: Mapped[float | None] = mapped_column(Float)
    vat_applied: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    customer_segment: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EpistemicStatus.ESTIMATE.value
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_date: Mapped[date | None] = mapped_column(Date)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    price_basis: Mapped[dict[str, Any] | None] = mapped_column(
        nullable=True, doc="Tax/levy decomposition used to derive price_basis."
    )
