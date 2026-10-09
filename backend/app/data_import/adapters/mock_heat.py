"""Adapters for the synthetic heat-demand and price datasets."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EpistemicStatus
from app.data_import.adapters import mock_heat_demand as dev
from app.data_import.base import Adapter, SourceDescriptor
from app.data_validation.validators import RejectedRecord, parse_date, parse_float
from app.models.evidence import Dataset
from app.models.heat import Building, EnergyPrice, HeatDemand, HeatNetwork

logger = logging.getLogger(__name__)


def _descriptor(key: str, source: str) -> SourceDescriptor:
    d = dev.DATASETS[key]
    return SourceDescriptor(
        source=source,
        name=d["name"],
        version=d["version"],
        description=d["description"],
        licence=d["licence"],
        reliability=d["reliability"],
        is_mock=True,
    )


class MockBuildingAdapter(Adapter):
    """Loads synthetic building heat demand."""

    source = "mock_heat_demand"
    is_mock = True
    entity_kind = "building"

    def descriptor(self) -> SourceDescriptor:
        return _descriptor("buildings", self.source)

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        yield from dev.building_records()

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        from app.data_validation.validators import validate_building_record  # noqa: PLC0415

        result = validate_building_record(record)
        if not result.is_valid:
            first = result.errors[0]
            raise RejectedRecord(first.code, first.message, first.field)

        values = result.cleaned
        source_record_id = str(record.get("id") or "").strip()
        if not source_record_id:
            raise RejectedRecord(
                "missing_source_record_id",
                "building record has no id, so a re-import would duplicate it",
                "id",
            )

        existing = db.scalar(
            select(Building).where(
                Building.source == self.source,
                Building.source_record_id == source_record_id,
            )
        )

        payload = {
            "building_type": values.get("building_type", "domestic"),
            "postcode": values.get("postcode"),
            "address_reference": values.get("address_reference"),
            "latitude": values["latitude"],
            "longitude": values["longitude"],
            "region": values.get("region"),
            "floor_area_m2": values.get("floor_area_m2"),
            "construction_year": int(values["construction_year"])
            if values.get("construction_year")
            else None,
            "annual_heat_demand_kwh": values.get("annual_heat_demand_kwh"),
            "peak_heat_demand_kw": values.get("peak_heat_demand_kw"),
            "required_supply_temperature_c": values.get("required_supply_temperature_c"),
            "current_fuel": values.get("current_fuel"),
            "current_heating_technology": values.get("current_heating_technology"),
            "connection_potential": record.get("connection_potential"),
            "is_connected_to_network": bool(record.get("is_connected_to_network", False)),
            # Modelled from floor area, never metered.
            "status": EpistemicStatus.ESTIMATE.value,
            "confidence": "medium",
            "source": self.source,
            "dataset_version": dataset.version,
            "source_record_id": source_record_id,
        }

        if existing is None:
            db.add(Building(tenant_id=record.get("tenant_id") or _dev_tenant(db), **payload))
        else:
            for field_name, value in payload.items():
                setattr(existing, field_name, value)

        db.flush()
        return True


class MockHeatDemandAreaAdapter(Adapter):
    """Loads settlement-level demand aggregates."""

    source = "mock_heat_demand_areas"
    is_mock = True

    def descriptor(self) -> SourceDescriptor:
        return _descriptor("heat_demand_areas", self.source)

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        yield from dev.heat_demand_area_records()

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        lat = parse_float(record.get("latitude"), "latitude", allow_none=False)
        lon = parse_float(record.get("longitude"), "longitude", allow_none=False)

        area_code = str(record.get("area_code") or "").strip()
        if not area_code:
            raise RejectedRecord(
                "missing_area_code",
                "demand area record has no area_code, so it cannot be deduplicated",
                "area_code",
            )

        existing = db.scalar(
            select(HeatDemand).where(
                HeatDemand.source == self.source,
                HeatDemand.area_code == area_code,
            )
        )

        payload = {
            "area_code": area_code,
            "area_name": record.get("area_name"),
            "area_type": record.get("area_type", "postcode_sector"),
            "latitude": lat,
            "longitude": lon,
            "region": record.get("region"),
            "population": record.get("population"),
            "household_count": record.get("household_count"),
            "total_annual_demand_kwh": parse_float(
                record.get("total_annual_demand_kwh"), "total_annual_demand_kwh",
                allow_none=False,
            ),
            "domestic_share_pct": record.get("domestic_share_pct"),
            "peak_demand_kw": record.get("peak_demand_kw"),
            "gas_network_present": record.get("gas_network_present"),
            "average_supply_temperature_c": record.get("average_supply_temperature_c"),
            "upgrade_potential_score": record.get("upgrade_potential_score"),
            "status": EpistemicStatus.ESTIMATE.value,
            "source": self.source,
            "dataset_version": dataset.version,
            "source_record_id": area_code,
            "is_mock": True,
        }

        if existing is None:
            db.add(HeatDemand(tenant_id=_dev_tenant(db), **payload))
        else:
            for field_name, value in payload.items():
                setattr(existing, field_name, value)

        db.flush()
        return True


class MockHeatNetworkAdapter(Adapter):
    """Loads synthetic heat networks."""

    source = "mock_heat_networks"
    is_mock = True

    def descriptor(self) -> SourceDescriptor:
        return _descriptor("heat_networks", self.source)

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        yield from dev.heat_network_records()

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        existing = db.scalar(
            select(HeatNetwork).where(
                HeatNetwork.source == self.source, HeatNetwork.name == record["name"]
            )
        )

        payload = {
            "operator": record.get("operator"),
            "centre_latitude": record.get("centre_latitude"),
            "centre_longitude": record.get("centre_longitude"),
            "existing": bool(record.get("existing", False)),
            "operational": record.get("operational"),
            "network_type": record.get("network_type"),
            "current_heat_source": record.get("current_heat_source"),
            "current_heat_source_capacity_mw": record.get("current_heat_source_capacity_mw"),
            "flow_temperature_c": record.get("flow_temperature_c"),
            "return_temperature_c": record.get("return_temperature_c"),
            "network_length_m": record.get("network_length_m"),
            "connected_buildings": record.get("connected_buildings"),
            "annual_delivered_heat_gwh": record.get("annual_delivered_heat_gwh"),
            "spare_capacity_mw": record.get("spare_capacity_mw"),
            "reinforcement_required": record.get("reinforcement_required"),
            "status": EpistemicStatus.ESTIMATE.value,
            "source": self.source,
            "is_mock": True,
        }

        if existing is None:
            db.add(HeatNetwork(tenant_id=_dev_tenant(db), name=record["name"], **payload))
        else:
            for field_name, value in payload.items():
                setattr(existing, field_name, value)

        db.flush()
        return True


class MockEnergyPriceAdapter(Adapter):
    """Loads the synthetic tariff book."""

    source = "mock_energy_prices"
    is_mock = True

    def descriptor(self) -> SourceDescriptor:
        return _descriptor("energy_prices", self.source)

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        yield from dev.energy_price_records()

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        valid_from = parse_date(record.get("valid_from"), "valid_from", allow_none=False)
        valid_to = (
            parse_date(record["valid_to"], "valid_to") if record.get("valid_to") else None
        )

        existing = db.scalar(
            select(EnergyPrice).where(
                EnergyPrice.fuel == record["fuel"],
                EnergyPrice.valid_from == valid_from,
            )
        )

        # Heat price is an assumption about what a scheme could achieve, not a
        # published tariff, and is labelled as such so it is never mistaken for
        # market evidence.
        is_assumption = record["fuel"].startswith("heat_")
        payload = {
            "price_p_per_kwh": parse_float(
                record["price_p_per_kwh"], "price_p_per_kwh", allow_none=False
            ),
            "levies_p_per_kwh": record.get("levies_p_per_kwh"),
            "standing_charge_p_per_kwh": record.get("standing_charge_p_per_kwh"),
            "carbon_price_p_per_kwh": record.get("carbon_price_p_per_kwh"),
            "valid_to": valid_to,
            "customer_segment": record.get("customer_segment"),
            "status": (
                EpistemicStatus.ASSUMPTION.value
                if is_assumption
                else EpistemicStatus.ESTIMATE.value
            ),
            "source": self.source,
            "price_basis": record.get("price_basis"),
            "is_mock": True,
        }

        if existing is None:
            db.add(EnergyPrice(fuel=record["fuel"], valid_from=valid_from, **payload))
        else:
            for field_name, value in payload.items():
                setattr(existing, field_name, value)

        db.flush()
        return True


class MockRegulatoryAdapter(Adapter):
    """Loads consent and obligation records.

    These are statements of law and regulator policy rather than measurements of
    a particular well, so they are FACT-status and not mock-flagged on the rows -
    only the dataset is synthetic. Flagging them would understate the reliability
    of a statement that is genuinely true.
    """

    source = "mock_regulatory"
    is_mock = True

    def descriptor(self) -> SourceDescriptor:
        return SourceDescriptor(
            source=self.source,
            name="UK geothermal regulatory requirements (development register)",
            version="2026.09.08",
            description=(
                "Consents and obligations applicable to geothermal reuse in each UK "
                "jurisdiction. Descriptions reflect published regulator policy; the "
                "lead times and costs are engineering estimates, not quoted figures."
            ),
            licence="Not applicable. Compiled from public regulatory guidance.",
            reliability="tier_b",
            is_mock=True,
        )

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        yield from dev.regulatory_requirement_records()

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        from app.models.analysis import RegulatoryRequirement  # noqa: PLC0415

        existing = db.scalar(
            select(RegulatoryRequirement).where(
                RegulatoryRequirement.source == self.source,
                RegulatoryRequirement.title == record["title"],
            )
        )

        payload = {
            "jurisdiction": record["jurisdiction"],
            "description": record.get("description"),
            "authority": record.get("authority"),
            "applies_to_configuration": record.get("applies_to_configuration"),
            "is_mandatory": bool(record.get("is_mandatory", True)),
            "typical_lead_time_months": record.get("typical_lead_time_months"),
            "estimated_cost_gbp": record.get("estimated_cost_gbp"),
            "status": record.get("status", EpistemicStatus.FACT.value),
            "source": self.source,
            "source_url": None,
            "is_mock": False,
        }

        if existing is None:
            db.add(RegulatoryRequirement(title=record["title"], **payload))
        else:
            for field_name, value in payload.items():
                setattr(existing, field_name, value)

        db.flush()
        return True


def _dev_tenant(db: Session):
    """The development tenant, created on first use.

    Tenant-scoped models need a tenant, and the synthetic datasets belong to the
    development tenant. Created here rather than assumed so an adapter run against
    an empty database does not fail on a foreign key.
    """
    import uuid  # noqa: PLC0415

    from app.models.user import Tenant  # noqa: PLC0415

    tenant = db.scalar(select(Tenant).where(Tenant.slug == "development"))
    if tenant is None:
        tenant = Tenant(
            id=uuid.UUID("00000000-0000-0000-0000-0000000000ff"),
            slug="development",
            name="Development (synthetic data)",
            max_analyses_per_day=100_000,
        )
        db.add(tenant)
        db.flush()
    return tenant.id

