"""Real ingestion adapter: NSTA onshore England petroleum wellbores.

Reads the GeoJSON written by ``python -m scripts.fetch_nsta_onshore_wells``
(publisher: North Sea Transition Authority, NSTA Open User Licence) and writes
real well rows, temperature observations and record-based integrity rows.

Separation from synthetic data
------------------------------
``source = "nsta_onshore"`` has no ``mock_`` prefix and ``is_mock = False``, so
every existing filter (``include_mock``, the ``X-Is-Mock-Data`` header, the map
tint) treats these rows as real, and synthetic rows stay distinguishable from
them in the same database. The adapter is deliberately **not** in the mock
bootstrap order: real data is loaded only when someone asks for it.

What is and is not inferred
---------------------------
* Coordinates come from the feature geometry (WGS84). The publisher's text
  decimal-degree fields are sometimes empty; the geometry never is.
* Depth is true vertical depth below ground where ground elevation is known
  (TVDSS + ground elevation), otherwise TVDSS. Implausible depths are nulled by
  the shared validator, never kept.
* ``MXTDTEMPC`` is stored as ``MEASURED`` but **non-stabilised** with LOW
  confidence: the dataset does not say whether it is a stabilised survey or an
  uncorrected bottom-hole temperature taken while drilling.
* Integrity rows are written only where the NSTA mechanical status itself says
  the bore is abandoned or plugged. An operating well gets **no** integrity row,
  because "completed" is not an inspection, and an unassessed well must stay
  UNKNOWN rather than be assumed sound.
* Nothing missing is filled. ~98% of wells carry no temperature; their thermal
  potential remains unknown.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DataConfidence, SourceReliability
from app.data_import.adapters.mock_wells import _recompute_well_temperature
from app.data_import.base import Adapter, SourceDescriptor, checksum_file
from app.data_normalisation.normalise import (
    normalise_integrity_status,
    normalise_temperature,
    normalise_well_record,
)
from app.data_validation.validators import RejectedRecord
from app.models.evidence import Dataset
from app.models.well import Well, WellIntegrity, WellTemperature

logger = logging.getLogger(__name__)

SOURCE = "nsta_onshore"
SOURCE_URL = "https://www.arcgis.com/home/item.html?id=d40f9dc58ca84268935582152a5b20f9"
LICENCE = "NSTA Open User Licence. Contains data from the North Sea Transition Authority."
TEMPERATURE_METHOD = "nsta_max_hole_temperature"

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PATH = _REPO_ROOT / "data" / "adapters" / "nsta" / "nsta_onshore_wells_wgs84.geojson"

#: NSTA mechanical status -> (platform well-status wording, integrity wording).
#: Both right-hand values are phrases the shared normalisers already recognise.
#: ``None`` for integrity means "no assessment exists; write no row".
MECHANICAL_STATUS: dict[str, tuple[str, str | None]] = {
    # Phase 3: abandoned to surface, wellhead removed. Re-entry means drilling out
    # surface plugs: treat as no access.
    "abandoned phase 3": ("plugged and abandoned", "abandoned"),
    "plugged": ("plugged and abandoned", "plugged"),
    # Phase 1/2: reservoir or intermediate barriers set, upper bore may remain.
    # Not accessible for production without workover.
    "abandoned phase 1": ("abandoned", "suspended"),
    "abandoned phase 2": ("abandoned", "suspended"),
    "completed (shut in)": ("shut in", None),
    "completed (operating)": ("producing", None),
}

_PLACEHOLDERS = {"", "no data available", "unknown", "n/a", "none"}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _PLACEHOLDERS else text


def _number(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _epoch_ms_to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def depth_below_ground_m(props: dict[str, Any]) -> float | None:
    """TD as true vertical depth below ground, or None when not defensible."""
    tvdss = _number(props.get("TDTVDSSM"))
    if tvdss is None or tvdss <= 0:
        return None
    ground = _number(props.get("GRNDELEV_M"))
    if ground is not None and ground > 0:
        return round(tvdss + ground, 1)
    return round(tvdss, 1)


def feature_to_record(feature: dict[str, Any]) -> dict[str, Any]:
    """Map one NSTA GeoJSON feature to the shared raw well-record shape.

    Pure function: no database access, so it can be tested directly.
    """
    props = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or [None, None]

    mech_raw = _text(props.get("COMPLESTAT"))
    status_wording, integrity_wording = MECHANICAL_STATUS.get(
        (mech_raw or "").lower(), (mech_raw or "unknown", None)
    )
    spud = _epoch_ms_to_date(props.get("SPUDDATE"))
    intent = (_text(props.get("ORIGINTENT")) or "").lower()

    return {
        "well_id": _text(props.get("WELLREGNO")),
        "id": _text(props.get("WELLREGNO")),
        "well_name": _text(props.get("NAME")) or _text(props.get("WELLREGNO")),
        "longitude": coords[0],
        "latitude": coords[1],
        "status": status_wording,
        "status_raw": mech_raw,
        "purpose": "exploration" if intent in ("exploration", "appraisal") else "unknown",
        "operator": _text(props.get("RESWOP")) or _text(props.get("SUBAREAOP")),
        "licence": _text(props.get("LICNO")),
        "county": _text(props.get("ONS_COUNTY")),
        "total_depth_m": depth_below_ground_m(props),
        "drilling_year": spud.year if spud else None,
        "spud_date": spud.isoformat() if spud else None,
        # Kept separate from the well fields: written as observation rows.
        "_max_hole_temperature_c": _number(props.get("MXTDTEMPC")),
        "_integrity_wording": integrity_wording,
        "_mechanical_status": mech_raw,
    }


class NstaOnshoreWellAdapter(Adapter):
    """Loads real NSTA onshore England wellbores from a downloaded GeoJSON."""

    source = SOURCE
    is_mock = False

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get("NSTA_WELLS_PATH") or DEFAULT_PATH)
        self._metadata: dict[str, Any] | None = None

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.path} not found. Run `python -m scripts.fetch_nsta_onshore_wells` "
                "from the repository root first, or set NSTA_WELLS_PATH."
            )
        return json.loads(self.path.read_text(encoding="utf-8"))

    def descriptor(self) -> SourceDescriptor:
        payload = self._read()
        meta = payload.get("metadata") or {}
        self._metadata = meta
        downloaded = meta.get("downloaded_utc")
        download_date = (
            datetime.fromisoformat(downloaded.replace("Z", "+00:00")).date()
            if downloaded
            else None
        )
        checksum = checksum_file(self.path)
        return SourceDescriptor(
            source=self.source,
            name="NSTA onshore England petroleum wellbores (top holes, WGS84)",
            # Versioned by content, so a re-download with changed data is a new
            # dataset version and an identical one is idempotent.
            version=f"{download_date or 'undated'}-{checksum[:12]}",
            source_url=SOURCE_URL,
            description=(
                "Real wellbore headers published by the North Sea Transition "
                "Authority. England only. Temperatures are sparse and of unstated "
                "stabilisation; integrity is inferred only from abandonment status."
            ),
            download_date=download_date,
            licence=LICENCE,
            reliability=SourceReliability.TIER_A.value,
            is_mock=False,
            quality_score=0.0,
            validation_summary={
                "sha256": checksum,
                "publisher_record_count": meta.get("record_count"),
                "field_coverage": meta.get("field_coverage"),
            },
        )

    def fetch(self, db: Session) -> Iterator[dict[str, Any]]:
        payload = self._read()
        for feature in payload.get("features", []):
            yield feature_to_record(feature)

    def load(self, db: Session, record: dict[str, Any], dataset: Dataset) -> bool:
        if not record.get("well_id"):
            raise RejectedRecord("missing_id", "feature has no WELLREGNO", "WELLREGNO")

        well_fields = {k: v for k, v in record.items() if not k.startswith("_")}
        kwargs = normalise_well_record(
            well_fields,
            source=self.source,
            source_url=SOURCE_URL,
            dataset_version=dataset.version,
        )
        # The shared normaliser derives status_raw from "status"; keep NSTA's own
        # wording so the interface shows what the publisher actually said.
        kwargs["status_raw"] = record.get("_mechanical_status")

        well = db.scalar(
            select(Well).where(
                Well.source == self.source,
                Well.source_record_id == kwargs["source_record_id"],
            )
        )
        if well is None:
            # A synthetic row may share an id pattern; real ids are namespaced
            # by source, so never adopt a row from another source.
            clash = db.scalar(select(Well).where(Well.well_id == kwargs["well_id"]))
            if clash is not None and clash.source != self.source:
                raise RejectedRecord(
                    "id_clash",
                    f"well_id '{kwargs['well_id']}' already belongs to source "
                    f"'{clash.source}'; refusing to merge real and synthetic records",
                    "well_id",
                )
            well = Well(**kwargs)
            db.add(well)
        else:
            for key, value in kwargs.items():
                if value is not None or getattr(well, key, None) is None:
                    setattr(well, key, value)
        db.flush()

        self._load_temperature(db, well, record)
        self._load_integrity(db, well, record)
        return True

    def _load_temperature(self, db: Session, well: Well, record: dict[str, Any]) -> None:
        value = record.get("_max_hole_temperature_c")
        depth = well.total_depth_m
        if value is None:
            return
        if depth is None:
            # A temperature with no depth cannot drive a thermal calculation, so
            # it is not used, but it is never dropped silently: the reading is
            # recorded as a data gap so the evidence stays visible.
            gaps = dict(well.known_data_gaps or {})
            gaps["temperature_depth_m"] = (
                f"NSTA reports a maximum hole temperature of {value} degC but no "
                "usable depth, so it cannot be used; thermal potential stays unknown"
            )
            well.known_data_gaps = gaps
            db.flush()
            return
        normalised = normalise_temperature(value, TEMPERATURE_METHOD, depth)
        if normalised is None:
            return
        record_id = f"{well.well_id}-MXTDTEMPC"
        existing = db.scalar(
            select(WellTemperature).where(
                WellTemperature.well_id == well.id,
                WellTemperature.source_record_id == record_id,
            )
        )
        if existing is None:
            db.add(
                WellTemperature(
                    well_id=well.id,
                    depth_m=depth,
                    temperature_c=normalised.value,
                    measured_at=None,
                    measurement_method=TEMPERATURE_METHOD,
                    status=normalised.status,
                    confidence=normalised.confidence or DataConfidence.LOW.value,
                    is_final_stabilised=False,
                    source=self.source,
                    source_url=SOURCE_URL,
                    source_record_id=record_id,
                    note=(
                        "NSTA 'hole temperature - maximum'. Stabilisation not stated; "
                        "may be an uncorrected drilling BHT, which typically reads low. "
                        "Depth assumed to be TD."
                    ),
                )
            )
            db.flush()
        _recompute_well_temperature(db, well)

    def _load_integrity(self, db: Session, well: Well, record: dict[str, Any]) -> None:
        wording = record.get("_integrity_wording")
        if not wording:
            return
        status = normalise_integrity_status(wording)
        values: dict[str, Any] = {
            "status": status.value,
            "status_status": status.status,
            "confidence": status.confidence or DataConfidence.LOW.value,
            "source": self.source,
            "unknown_reasons": (
                f"Inferred from NSTA mechanical status '{record.get('_mechanical_status')}'. "
                "No physical inspection is recorded."
            ),
        }
        existing = db.scalar(select(WellIntegrity).where(WellIntegrity.well_id == well.id))
        if existing is None:
            db.add(WellIntegrity(well_id=well.id, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        db.flush()
