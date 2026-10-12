"""Real-data ingestion and the integrity hard gate.

The features below are hand-written test rows in the NSTA schema, not records
copied from the publisher. Every test builds its own file with unique ids, so the
suite stays order-independent under pytest-randomly.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.core.enums import Recommendation, RiskCategory, WellIntegrityStatus
from app.data_import.adapters.nsta_wells import (
    SOURCE,
    NstaOnshoreWellAdapter,
    depth_below_ground_m,
    feature_to_record,
)
from app.data_import.registry import ADAPTERS, BOOTSTRAP_ORDER
from app.db.session import SessionLocal
from app.engineering.risk import RiskBuilder
from app.engineering.scoring import recommend
from app.models.evidence import Dataset
from app.models.well import Well, WellIntegrity, WellTemperature


def _feature(regno: str, **props) -> dict:
    base = {
        "WELLREGNO": regno,
        "NAME": f"TEST {regno}",
        "COMPLESTAT": "Completed (Operating)",
        "ORIGINTENT": "Development",
        "RESWOP": "Test Operator Ltd",
        "LICNO": "PEDL999",
        "ONS_COUNTY": "Testshire",
        "TDTVDSSM": 1800.0,
        "GRNDELEV_M": 50.0,
        "SPUDDATE": 631152000000,  # 1990-01-01
        "MXTDTEMPC": None,
        "TOPHOLEXDD": None,  # deliberately empty, as in the real data
        "TOPHOLEYDD": None,
    }
    base.update(props)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-1.2, 53.1]},
        "properties": base,
    }


def _write(tmp_path: Path, features: list[dict]) -> Path:
    path = tmp_path / "nsta.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "metadata": {
                    "downloaded_utc": "2026-10-12T00:00:00+00:00",
                    "record_count": len(features),
                },
                "features": features,
            }
        )
    )
    return path


def _ids() -> tuple[str, ...]:
    tag = uuid.uuid4().hex[:8].upper()
    return tuple(f"TEST/{tag}-{n}" for n in range(5))


# ---- Pure mapping -----------------------------------------------------------


class TestFeatureMapping:
    def test_coordinates_come_from_geometry_when_text_fields_are_empty(self):
        record = feature_to_record(_feature("T-1"))
        assert (record["longitude"], record["latitude"]) == (-1.2, 53.1)

    def test_placeholder_operator_becomes_null_not_a_name(self):
        record = feature_to_record(
            _feature("T-1", RESWOP="No Data Available", SUBAREAOP=None)
        )
        assert record["operator"] is None

    def test_depth_is_tvd_below_ground(self):
        assert depth_below_ground_m({"TDTVDSSM": 1800.0, "GRNDELEV_M": 50.0}) == 1850.0

    def test_zero_or_negative_depth_is_unknown_not_trusted(self):
        assert depth_below_ground_m({"TDTVDSSM": 0, "GRNDELEV_M": 40}) is None
        assert depth_below_ground_m({"TDTVDSSM": -2002.7, "GRNDELEV_M": 40}) is None
        assert depth_below_ground_m({"TDTVDSSM": None}) is None

    def test_phase3_abandonment_maps_to_no_access(self):
        record = feature_to_record(_feature("T-1", COMPLESTAT="Abandoned Phase 3"))
        assert record["status"] == "plugged and abandoned"
        assert record["_integrity_wording"] == "abandoned"

    def test_operating_well_gets_no_integrity_assessment(self):
        record = feature_to_record(_feature("T-1"))
        assert record["_integrity_wording"] is None


# ---- Separation and registration -------------------------------------------


@pytest.mark.usefixtures("_clean_real_rows")
class TestSeparation:
    def test_real_adapter_is_not_mock_and_not_bootstrapped(self):
        assert ADAPTERS["nsta_wells"].is_mock is False
        assert not ADAPTERS["nsta_wells"].source.startswith("mock_")
        assert "nsta_wells" not in BOOTSTRAP_ORDER

    def test_missing_file_is_a_reported_error_not_a_crash(self, tmp_path: Path):
        result = NstaOnshoreWellAdapter(tmp_path / "absent.geojson").run()
        assert not result.ok
        assert any("fetch_nsta_onshore_wells" in e for e in result.errors)


# ---- End-to-end ingest ------------------------------------------------------


@pytest.fixture
def _clean_real_rows() -> Iterator[None]:
    """Remove every row these tests commit.

    The schema is shared across the session, and other suites rightly assert
    that a development database holds only synthetic wells. Real rows written
    here must not outlive the test that wrote them.
    """
    yield
    with SessionLocal() as session:
        ids = select(Well.id).where(
            (Well.source == SOURCE) | Well.well_id.like("TEST/%")
        )
        session.execute(delete(WellTemperature).where(WellTemperature.well_id.in_(ids)))
        session.execute(delete(WellIntegrity).where(WellIntegrity.well_id.in_(ids)))
        session.execute(
            delete(Well).where((Well.source == SOURCE) | Well.well_id.like("TEST/%"))
        )
        session.execute(delete(Dataset).where(Dataset.source == SOURCE))
        session.commit()


@pytest.mark.usefixtures("_clean_real_rows")
class TestIngest:
    def test_ingest_writes_real_rows_with_provenance(self, tmp_path: Path, db):
        ok, phase3, hot, depthless, _ = _ids()
        path = _write(
            tmp_path,
            [
                _feature(ok),
                _feature(phase3, COMPLESTAT="Abandoned Phase 3"),
                _feature(hot, MXTDTEMPC=80.0),
                _feature(depthless, MXTDTEMPC=55.0, TDTVDSSM=None),
            ],
        )
        result = NstaOnshoreWellAdapter(path).run()
        assert result.ok, result.errors
        assert result.records_read == 4 and result.records_rejected == 0

        stmt = select(Well).where(Well.well_id.in_([ok, phase3, hot, depthless]))
        wells = {w.well_id: w for w in db.scalars(stmt)}
        assert len(wells) == 4
        assert all(w.source == SOURCE for w in wells.values())

        dataset = db.get(Dataset, result.dataset_id)
        assert dataset.is_mock is False
        assert dataset.licence and "North Sea Transition Authority" in dataset.licence
        assert dataset.validation_summary.get("sha256")

        # A temperature is MEASURED but never treated as stabilised.
        temp = db.scalar(select(WellTemperature).where(WellTemperature.well_id == wells[hot].id))
        assert temp.status == "MEASURED"
        assert temp.is_final_stabilised is False
        assert wells[hot].temperature_c == 80.0

        # A temperature with no depth is not used, but it is not silently lost.
        assert wells[depthless].temperature_c is None
        assert "temperature_depth_m" in (wells[depthless].known_data_gaps or {})

        # Missing temperature stays unknown, never zero.
        assert wells[ok].temperature_c is None

        # Integrity: phase 3 is no-access; an operating well is unassessed.
        integrity = db.scalar(select(WellIntegrity).where(WellIntegrity.well_id == wells[phase3].id))
        assert integrity.status == WellIntegrityStatus.ABANDONED_NO_ACCESS.value
        assert db.scalar(select(WellIntegrity).where(WellIntegrity.well_id == wells[ok].id)) is None

    def test_reingest_is_idempotent(self, tmp_path: Path, db):
        regno, *_ = _ids()
        path = _write(tmp_path, [_feature(regno, MXTDTEMPC=70.0)])
        NstaOnshoreWellAdapter(path).run()
        NstaOnshoreWellAdapter(path).run()
        assert len(list(db.scalars(select(Well).where(Well.well_id == regno)))) == 1
        well = db.scalar(select(Well).where(Well.well_id == regno))
        assert len(list(db.scalars(select(WellTemperature).where(WellTemperature.well_id == well.id)))) == 1

    def test_refuses_to_merge_into_a_synthetic_record(self, tmp_path: Path, db):
        regno, *_ = _ids()
        db.add(Well(well_id=regno, well_name="synthetic", latitude=53.0, longitude=-1.0,
                    status="unknown", original_purpose="unknown", source="mock_nsta",
                    source_record_id=regno, data_confidence="unknown"))
        db.commit()
        result = NstaOnshoreWellAdapter(_write(tmp_path, [_feature(regno)])).run()
        assert result.records_rejected == 1
        assert any("refusing to merge real and synthetic" in e for e in result.errors)
        assert db.scalar(select(Well).where(Well.well_id == regno)).source == "mock_nsta"


# ---- The integrity hard gate -------------------------------------------------


class TestIntegrityGate:
    def test_high_score_cannot_override_critical_integrity_risk(self):
        for score in (65.0, 80.0, 100.0):
            rec, reasons = recommend(
                feasibility_score=score, confidence_score=0.9, critical_integrity_risk=True
            )
            assert rec == Recommendation.LOW_PRIORITY
            assert any("hard gate" in r for r in reasons)

    def test_gate_never_raises_a_recommendation(self):
        rec, reasons = recommend(
            feasibility_score=5.0, confidence_score=0.9, critical_integrity_risk=True
        )
        assert rec == Recommendation.DO_NOT_PURSUE
        assert any("well-integrity risk is open" in r for r in reasons)

    def test_without_the_gate_the_same_score_is_high_priority(self):
        rec, _ = recommend(feasibility_score=80.0, confidence_score=0.9)
        assert rec == Recommendation.HIGH_PRIORITY

    def _integrity(self, status: str, well_status: str = "plugged_abandoned"):
        assessment = RiskBuilder(
            well_status=well_status, integrity_status=status,
            drilling_year=2010, total_depth_m=2000.0, has_casing_record=True,
        ).build()
        return next(r for r in assessment.risks if r.category == RiskCategory.WELL_INTEGRITY.value)

    def test_no_access_integrity_is_critical_even_for_a_young_well(self):
        assert self._integrity(WellIntegrityStatus.ABANDONED_NO_ACCESS.value).is_critical

    def test_poor_integrity_is_critical(self):
        assert self._integrity(WellIntegrityStatus.POOR_UNKNOWN.value).is_critical

    def test_good_integrity_is_not_critical(self):
        risk = self._integrity(WellIntegrityStatus.GOOD_CONDITION.value, well_status="producing")
        assert not risk.is_critical
