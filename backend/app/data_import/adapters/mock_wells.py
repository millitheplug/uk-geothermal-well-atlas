"""Development ingestion adapters.

These are the adapters the platform actually runs today. They implement the same
:class:`~app.data_import.base.Adapter` contract the real adapters will, and they
return the same record shapes, so replacing ``mock_nsta`` with ``nsta`` is a
change to one class, not to the application.

Critical property: every row written here carries ``is_mock=True`` on the
dataset and a ``mock_``-prefixed ``source`` on the row. The API surfaces both, and
``WellFilters.include_mock=False`` excludes them, so synthetic data cannot leak
into a report that claims to be about real wells.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DataConfidence, EpistemicStatus
from app.data_import.adapters import dev_wells
from app.data_import.base import Adapter, SourceDescriptor
from app.data_normalisation.normalise import (
    confidence_from_variability,
    normalise_integrity_status,
    normalise_temperature,
    normalise_well_record,
)
from app.data_validation.validators import RejectedRecord, parse_date, parse_float
from app.models.evidence import Dataset
from app.models.well import Well, WellIntegrity, WellTemperature

logger = logging.getLogger(__name__)


class MockWellAdapter(Adapter):
    """Loads the synthetic well dataset.

    Mirrors what a real NSTA adapter does: fetch raw records, normalise them
    against the platform vocabulary, validate coordinates and depth, and upsert
    on the stable well id so a re-import updates rather than duplicates.
    """

    source = "mock_nsta"
    is_mock = True

    def descriptor(self) -> SourceDescriptor:
        d = dev_wells.dataset_descriptor()
        return SourceDescriptor(
            source=self.source,
            name=d["name"],
            version=d["version"],
            description=d["description"],
            source_url=d["source_url"],
            download_date=d["download_date"],
            published_date=d["published_date"],
            licence=d["licence"],
            reliability=d["reliability"],
            is_mock=True,
            quality_score=0.0,
            validation_summary={"note": "synthetic dataset, quality score not meaningful"},
        )

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        yield from dev_wells.well_records()

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        kwargs = normalise_well_record(
            record,
            source=self.source,
            dataset_version=dataset.version,
        )

        well = db.scalar(
            select(Well).where(
                Well.source == self.source, Well.source_record_id == kwargs["source_record_id"]
            )
        )

        if well is None:
            well = Well(**kwargs)
            db.add(well)
        else:
            for key, value in kwargs.items():
                # Never overwrite a real measurement with a null from a later,
                # sparser version of the same dataset.
                if value is not None or getattr(well, key, None) is None:
                    setattr(well, key, value)

        db.flush()
        return True


class MockTemperatureAdapter(Adapter):
    """Loads individual temperature observations."""

    source = "mock_nsta_temps"
    is_mock = True
    entity_kind = "temperature"

    def descriptor(self) -> SourceDescriptor:
        return SourceDescriptor(
            source=self.source,
            name="Synthetic well temperature observations (development only)",
            version="2026.09.08",
            description=(
                "Entirely synthetic. Depth, temperature, date and method are "
                "invented. Includes deliberate cases: repeat measurements with "
                "scatter, an unstabilised reading that overstates temperature, and "
                "a 35 K conflict between two sources on one well."
            ),
            licence="Not applicable. No third-party data.",
            reliability="tier_mock",
            is_mock=True,
        )

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        yield from dev_wells.temperature_records()

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        well = db.scalar(select(Well).where(Well.well_id == record["well_id"]))
        if well is None:
            raise RejectedRecord(
                "unknown_well", f"no well with id '{record['well_id']}'", "well_id"
            )

        normalised = normalise_temperature(
            record.get("temperature_c"),
            record.get("measurement_method"),
            record.get("depth_m"),
        )
        if normalised is None:
            return False

        depth = parse_float(record.get("depth_m"), "depth_m", allow_none=False)

        existing = db.scalar(
            select(WellTemperature).where(
                WellTemperature.well_id == well.id,
                WellTemperature.depth_m == depth,
                WellTemperature.temperature_c == normalised.value,
                WellTemperature.source == record.get("source", self.source),
            )
        )
        if existing is not None:
            return False

        measured_at = None
        raw_date = record.get("measured_at")
        if raw_date:
            try:
                from app.data_validation.validators import parse_date  # noqa: PLC0415

                measured_at = datetime.combine(
                    parse_date(raw_date, "measured_at"), datetime.min.time(),
                    tzinfo=UTC,
                )
            except RejectedRecord:
                measured_at = None

        db.add(
            WellTemperature(
                well_id=well.id,
                depth_m=depth,
                temperature_c=normalised.value,
                measured_at=measured_at,
                measurement_method=str(
                    record.get("measurement_method") or "unknown"
                ),
                status=normalised.status,
                confidence=normalised.confidence or DataConfidence.LOW.value,
                is_final_stabilised=bool(record.get("is_final_stabilised", True)),
                source=str(record.get("source") or self.source),
                source_url=None,
                source_record_id=f"{record['well_id']}-{depth}-{normalised.value}",
                note=normalised.note,
            )
        )
        db.flush()
        _recompute_well_temperature(db, well)
        return True


class MockIntegrityAdapter(Adapter):
    """Loads well integrity assessments."""

    source = "mock_nsta_integrity"
    is_mock = True
    entity_kind = "record"

    def descriptor(self) -> SourceDescriptor:
        return SourceDescriptor(
            source=self.source,
            name="Synthetic well integrity assessments (development only)",
            version="2026.09.08",
            description=(
                "Entirely synthetic condition scores and statuses. Two wells are "
                "deliberately left with no integrity row so the 'not assessed' path "
                "is exercised."
            ),
            licence="Not applicable. No third-party data.",
            reliability="tier_mock",
            is_mock=True,
        )

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        yield from dev_wells.integrity_records()

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        well = db.scalar(select(Well).where(Well.well_id == record["well_id"]))
        if well is None:
            raise RejectedRecord(
                "unknown_well", f"no well with id '{record['well_id']}'", "well_id"
            )

        status = normalise_integrity_status(record.get("status"))
        # The development dataset supplies an ISO date string; the column is a
        # real Date, so it must be parsed rather than passed through.
        last_check = parse_date(record.get("last_integrity_check_date"), "last_integrity_check_date")

        existing = db.scalar(
            select(WellIntegrity).where(WellIntegrity.well_id == well.id)
        )
        values: dict[str, Any] = {
            "status": status.value,
            "status_status": status.status,
            "confidence": status.confidence or DataConfidence.LOW.value,
            "casing_condition_score": record.get("casing_condition_score"),
            "wellhead_condition_score": record.get("wellhead_condition_score"),
            "access_score": record.get("access_score"),
            "abandonment_score": record.get("abandonment_score"),
            "requires_reequipment": record.get("requires_reequipment"),
            "last_integrity_check_date": last_check,
            "source": self.source,
            "unknown_reasons": status.note,
        }

        if existing is None:
            db.add(WellIntegrity(well_id=well.id, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        db.flush()
        return True


class MockGeologyAdapter(Adapter):
    """Loads formation-level geology and water chemistry."""

    source = "mock_bgs_geology"
    is_mock = True
    entity_kind = "record"

    def descriptor(self) -> SourceDescriptor:
        return SourceDescriptor(
            source=self.source,
            name="Synthetic formation geology and water chemistry (development only)",
            version="2026.09.08",
            description=(
                "Entirely synthetic gradients, permeabilities, salinities and pH "
                "values. Only wells recorded as having water chemistry have a row."
            ),
            licence="Not applicable. No third-party data.",
            reliability="tier_mock",
            is_mock=True,
        )

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        yield from dev_wells.geology_records()

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        well = db.scalar(select(Well).where(Well.well_id == record["well_id"]))
        if well is None:
            raise RejectedRecord(
                "unknown_well", f"no well with id '{record['well_id']}'", "well_id"
            )

        from app.models.geology import Geology  # noqa: PLC0415

        existing = db.scalar(select(Geology).where(Geology.well_id == well.id))
        values = {
            "geothermal_gradient_c_per_km": record.get("geothermal_gradient_c_per_km"),
            "permeability_md": record.get("permeability_md"),
            "net_thickness_m": record.get("net_thickness_m"),
            "reservoir_lithology": record.get("reservoir_lithology"),
            "water_salinity_ppt": record.get("water_salinity_ppt"),
            "water_ph": record.get("water_ph"),
            "scaling_tendency": record.get("scaling_tendency"),
            "corrosion_tendency": record.get("corrosion_tendency"),
            "chemistry_status": record.get("chemistry_status", EpistemicStatus.UNKNOWN.value),
            "status": EpistemicStatus.ESTIMATE.value,
            "confidence": DataConfidence.LOW.value,
            "source": self.source,
        }

        if existing is None:
            db.add(Geology(well_id=well.id, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        db.flush()
        return True


def _recompute_well_temperature(db: Session, well: Well) -> None:
    """Refresh the rolled-up temperature on the well from its observations.

    The deepest stabilised reading is preferred, because a shallow reading
    systematically understates the target interval and the deepest point is the
    only one that represents the reservoir. Variability across sources is also
    recorded, since it feeds the thermal score directly.
    """
    observations = list(
        db.scalars(
            select(WellTemperature).where(WellTemperature.well_id == well.id)
        )
    )
    if not observations:
        return

    stabilised = [o for o in observations if o.is_final_stabilised]
    pool = stabilised or observations
    deepest = max(pool, key=lambda o: o.depth_m)

    well.temperature_c = deepest.temperature_c
    well.temperature_depth_m = deepest.depth_m
    well.temperature_status = deepest.status
    well.temperature_confidence = deepest.confidence
    well.temperature_source = deepest.source

    values = [o.temperature_c for o in observations]
    spread = max(values) - min(values)
    well.temperature_variability_c = round(spread, 2) if len(values) > 1 else None

    # A well whose sources disagree badly cannot inherit high confidence from any
    # single one of them.
    variability_band = confidence_from_variability(well.temperature_variability_c)
    order = [
        DataConfidence.HIGH.value,
        DataConfidence.MEDIUM.value,
        DataConfidence.LOW.value,
        DataConfidence.VERY_LOW.value,
        DataConfidence.UNKNOWN.value,
    ]
    if order.index(variability_band) > order.index(deepest.confidence):
        well.temperature_confidence = variability_band

    db.flush()


def recompute_all_temperatures(db: Session) -> int:
    """Refresh every well's rolled-up temperature. Run after a bulk import."""
    count = 0
    for well in db.scalars(select(Well)):
        _recompute_well_temperature(db, well)
        count += 1
    db.flush()
    return count
