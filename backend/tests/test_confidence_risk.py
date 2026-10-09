"""Unit tests for the evidence confidence engine and the risk register."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import EpistemicStatus, RiskCategory
from app.engineering.confidence import (
    CONFIDENCE_WEIGHTS,
    assess_confidence,
    band_for,
)
from app.engineering.risk import RiskBuilder, required_categories


class TestConfidenceWeights:
    def test_weights_sum_to_one(self):
        assert sum(CONFIDENCE_WEIGHTS.values()) == pytest.approx(1.0)

    def test_five_axes_present(self):
        assert set(CONFIDENCE_WEIGHTS) == {
            "source_reliability",
            "data_completeness",
            "measurement_quality",
            "recency",
            "cross_source_agreement",
        }


class TestBands:
    def test_band_thresholds(self):
        assert band_for(0.90) == "high"
        assert band_for(0.60) == "medium"
        assert band_for(0.40) == "low"
        assert band_for(0.20) == "very_low"
        assert band_for(0.0) == "unknown"

    def test_boundaries(self):
        assert band_for(0.75) == "high"
        assert band_for(0.55) == "medium"
        assert band_for(0.35) == "low"


class TestSourceReliability:
    def test_no_sources_scores_low(self):
        result = assess_confidence(source_reliabilities=None)
        axis = next(c for c in result.components if c.name == "source_reliability")
        assert axis.score < 0.25

    def test_single_source_is_discounted(self):
        one = assess_confidence(source_reliabilities=[0.95], temperature_status="MEASURED")
        many = assess_confidence(
            source_reliabilities=[0.95, 0.92, 0.88], temperature_status="MEASURED"
        )
        a = next(c for c in one.components if c.name == "source_reliability")
        b = next(c for c in many.components if c.name == "source_reliability")
        assert b.score > a.score
        assert any("Only one source" in n for n in a.notes)

    def test_primary_sources_score_higher_than_press(self):
        primary = assess_confidence(
            source_reliabilities=[0.95, 0.92], temperature_status="MEASURED"
        )
        weak = assess_confidence(
            source_reliabilities=[0.35, 0.20], temperature_status="MEASURED"
        )
        assert primary.score > weak.score


class TestDataCompleteness:
    def test_empty_fields_score_low(self):
        result = assess_confidence(present_fields={})
        axis = next(c for c in result.components if c.name == "data_completeness")
        assert axis.score < 0.35

    def test_complete_fields_score_high(self):
        fields = {
            "temperature_c": 85.0, "total_depth_m": 2000.0, "tvd_m": 1900.0,
            "status": "producing", "original_purpose": "gas",
            "drilling_year": 1985, "operator": "Example Oil",
            "licence": "UK-OG", "formation": "Millstone Grit",
            "casing_string": "recorded", "bottomhole_pressure_bar": 120.0,
            "md_m": 2100.0, "max_deviation_deg": 5.0, "completion_type": "perforated",
            "latitude_offset_checked": "checked", "pressure_status": "MEASURED",
        }
        result = assess_confidence(
            present_fields=fields,
            integrity_assessed=True,
            demand_data_present=True,
            logs_available=True,
            temperature_status="MEASURED",
            measurement_method="static_bht",
        )
        axis = next(c for c in result.components if c.name == "data_completeness")
        assert axis.score > 0.85

    def test_missing_required_fields_are_named(self):
        result = assess_confidence(present_fields={"temperature_c": 85.0})
        axis = next(c for c in result.components if c.name == "data_completeness")
        assert any("Missing required fields" in n for n in axis.notes)

    def test_no_integrity_assessment_penalises(self):
        with_assessment = assess_confidence(
            present_fields={"temperature_c": 85.0}, integrity_assessed=True
        )
        without = assess_confidence(
            present_fields={"temperature_c": 85.0}, integrity_assessed=False
        )
        assert without.score < with_assessment.score

    def test_logs_bonus_applies(self):
        without = assess_confidence(present_fields={"temperature_c": 85.0})
        with_logs = assess_confidence(
            present_fields={"temperature_c": 85.0}, logs_available=True
        )
        assert with_logs.score > without.score


class TestMeasurementQuality:
    def test_stabilised_static_bht_is_the_best_method(self):
        result = assess_confidence(
            temperature_status=EpistemicStatus.MEASURED.value,
            measurement_method="static_bht",
            is_final_stabilised=True,
        )
        axis = next(c for c in result.components if c.name == "measurement_quality")
        assert axis.score > 0.85

    def test_regional_estimate_is_much_worse(self):
        measured = assess_confidence(
            temperature_status=EpistemicStatus.MEASURED.value,
            measurement_method="static_bht",
            is_final_stabilised=True,
        )
        estimated = assess_confidence(
            temperature_status=EpistemicStatus.ESTIMATE.value,
            measurement_method="regional_estimate",
        )
        m = next(c for c in measured.components if c.name == "measurement_quality")
        e = next(c for c in estimated.components if c.name == "measurement_quality")
        assert e.score < m.score * 0.5

    def test_unstabilised_reading_is_penalised_and_explained(self):
        result = assess_confidence(
            temperature_status=EpistemicStatus.MEASURED.value,
            measurement_method="max_dynamic",
            is_final_stabilised=False,
        )
        axis = next(c for c in result.components if c.name == "measurement_quality")
        assert any("stabilised" in n for n in axis.notes)

    def test_flow_test_adds_confidence(self):
        without = assess_confidence(
            temperature_status="MEASURED", measurement_method="static_bht"
        )
        with_flow = assess_confidence(
            temperature_status="MEASURED",
            measurement_method="static_bht",
            has_flow_test=True,
        )
        assert with_flow.score > without.score

    def test_high_variability_is_penalised(self):
        stable = assess_confidence(
            temperature_status="MEASURED", measurement_method="static_bht",
            temperature_variability_c=2.0,
        )
        variable = assess_confidence(
            temperature_status="MEASURED", measurement_method="static_bht",
            temperature_variability_c=25.0,
        )
        assert variable.score < stable.score

    def test_no_temperature_scores_very_low_on_this_axis(self):
        result = assess_confidence(temperature_status=EpistemicStatus.UNKNOWN.value)
        axis = next(c for c in result.components if c.name == "measurement_quality")
        assert axis.score < 0.1


class TestRecency:
    def test_recent_data_beats_old_data(self):
        now = datetime.now(UTC)
        recent = assess_confidence(
            temperature_status="MEASURED",
            measurement_method="static_bht",
            measurement_date=now - timedelta(days=365),
            well_status="producing",
        )
        old = assess_confidence(
            temperature_status="MEASURED",
            measurement_method="static_bht",
            measurement_date=now - timedelta(days=365 * 45),
            well_status="producing",
        )
        assert recent.score > old.score

    def test_abandoned_well_with_old_data_is_penalised(self):
        now = datetime.now(UTC)
        old_date = now - timedelta(days=365 * 30)
        abandoned = assess_confidence(
            temperature_status="MEASURED", measurement_method="static_bht",
            measurement_date=old_date, well_status="abandoned",
        )
        still_live = assess_confidence(
            temperature_status="MEASURED", measurement_method="static_bht",
            measurement_date=old_date, well_status="producing",
        )
        assert abandoned.score < still_live.score

    def test_no_date_is_low(self):
        result = assess_confidence(temperature_status="MEASURED", measurement_date=None)
        axis = next(c for c in result.components if c.name == "recency")
        assert axis.score <= 0.25


class TestCrossSourceAgreement:
    def test_agreeing_sources_score_well(self):
        result = assess_confidence(
            temperature_status="MEASURED",
            temperature_values_c=[85.0, 86.0, 84.5],
            sources=["nsta", "bgs", "operator"],
        )
        axis = next(c for c in result.components if c.name == "cross_source_agreement")
        assert axis.score > 0.85
        assert not result.conflicting_sources

    def test_disagreeing_sources_are_flagged(self):
        result = assess_confidence(
            temperature_status="MEASURED",
            temperature_values_c=[60.0, 95.0],
            sources=["nsta", "bgs"],
        )
        assert result.conflicting_sources
        assert "35.0 K" in result.conflicting_sources[0]
        axis = next(c for c in result.components if c.name == "cross_source_agreement")
        assert axis.score < 0.5

    def test_single_source_cannot_be_cross_checked(self):
        result = assess_confidence(
            temperature_status="MEASURED", sources=["nsta"], temperature_values_c=[85.0]
        )
        axis = next(c for c in result.components if c.name == "cross_source_agreement")
        assert axis.score < 0.5
        assert any("cannot be tested" in n for n in axis.notes)

    def test_wider_spread_lowers_the_score_monotonically(self):
        tight = assess_confidence(
            temperature_status="MEASURED", sources=["a", "b"],
            temperature_values_c=[84.0, 86.0],
        )
        loose = assess_confidence(
            temperature_status="MEASURED", sources=["a", "b"],
            temperature_values_c=[78.0, 92.0],
        )
        tight_component = next(c for c in tight.components if c.name == "cross_source_agreement")
        loose_component = next(c for c in loose.components if c.name == "cross_source_agreement")
        assert loose_component.score < tight_component.score


class TestOverallConfidence:
    def test_well_characterised_beats_well_unknown(self):
        now = datetime.now(UTC)
        good = assess_confidence(
            source_reliabilities=[0.95, 0.92],
            present_fields={
                "temperature_c": 85.0, "total_depth_m": 2000.0, "tvd_m": 1900.0,
                "status": "producing", "original_purpose": "gas", "drilling_year": 1985,
                "operator": "X", "licence": "Y", "formation": "Z", "casing_string": "yes",
            },
            integrity_assessed=True,
            demand_data_present=True,
            logs_available=True,
            temperature_status="MEASURED",
            measurement_method="static_bht",
            is_final_stabilised=True,
            measurement_date=now - timedelta(days=365 * 3),
            well_status="producing",
            temperature_values_c=[85.0, 86.0],
            sources=["nsta", "bgs"],
        )
        bad = assess_confidence(
            source_reliabilities=None,
            present_fields={},
            temperature_status=EpistemicStatus.UNKNOWN.value,
        )
        assert good.score > 0.7
        assert good.band == "high"
        assert bad.score < 0.3
        assert bad.band in ("very_low", "unknown", "low")

    def test_missing_temperature_caps_overall_confidence(self):
        """No temperature means the central question is unanswered."""
        high_everything_else = assess_confidence(
            source_reliabilities=[0.95, 0.92, 0.88],
            present_fields={
                "temperature_c": None, "total_depth_m": 2000.0, "tvd_m": 1900.0,
                "status": "producing", "original_purpose": "gas", "drilling_year": 1985,
                "operator": "X", "licence": "Y", "formation": "Z", "casing_string": "yes",
            },
            integrity_assessed=True,
            demand_data_present=True,
            logs_available=True,
            temperature_status=EpistemicStatus.UNKNOWN.value,
            sources=["a", "b", "c"],
            temperature_values_c=[80.0, 82.0],
        )
        assert high_everything_else.score < 0.6
        assert any("capped" in n for n in high_everything_else.components[-1].notes)

    def test_unknowns_are_passed_through(self):
        result = assess_confidence(unknowns=["casing_condition", "water_chemistry"])
        assert set(result.unknowns) == {"casing_condition", "water_chemistry"}

    def test_score_is_bounded(self):
        result = assess_confidence(
            source_reliabilities=[1.0] * 5,
            present_fields={k: 1 for k in ("temperature_c", "total_depth_m")},
            temperature_status="MEASURED",
        )
        assert 0.0 <= result.score <= 1.0

    def test_is_deterministic(self):
        kwargs = dict(
            source_reliabilities=[0.9],
            present_fields={"temperature_c": 80.0},
            temperature_status="MEASURED",
            measurement_method="static_bht",
        )
        assert assess_confidence(**kwargs).score == assess_confidence(**kwargs).score

    def test_serialises_every_axis(self):
        d = assess_confidence(temperature_status="MEASURED").to_dict()
        assert set(d["axes"]) == set(CONFIDENCE_WEIGHTS)
        assert "band" in d
        assert "confidence_version" in d


class TestRiskEngine:
    def _builder(self, **kwargs) -> RiskBuilder:
        defaults = dict(
            well_status="producing",
            integrity_status="unknown",
            temperature_status=EpistemicStatus.MEASURED.value,
            temperature_confidence="medium",
            drilling_year=1985,
            total_depth_m=2000.0,
            has_casing_record=True,
        )
        defaults.update(kwargs)
        return RiskBuilder(**defaults)

    def test_every_category_in_the_taxonomy_is_covered(self):
        assessment = self._builder().build()
        categories = {r.category for r in assessment.risks}
        assert categories == set(required_categories())
        assert len(assessment.risks) == len(required_categories())

    def test_every_risk_has_full_provenance(self):
        assessment = self._builder().build()
        for risk in assessment.risks:
            assert risk.title
            assert risk.description
            assert 0.0 <= risk.probability <= 1.0
            assert 0.0 <= risk.impact_value <= 1.0
            assert 0.0 <= risk.uncertainty <= 1.0
            assert risk.mitigation, f"{risk.category} has no mitigation"

    def test_risk_score_is_probability_times_impact(self):
        for risk in self._builder().build().risks:
            assert risk.risk_score == pytest.approx(risk.probability * risk.impact_value)

    def test_uncertainty_widens_the_score(self):
        assessment = self._builder().build()
        for risk in assessment.risks:
            assert risk.uncertainty_adjusted_score >= risk.risk_score

    def test_measured_temperature_lowers_its_risk(self):
        measured = self._builder(
            temperature_status=EpistemicStatus.MEASURED.value,
            temperature_confidence="high",
        ).build()
        unknown = self._builder(
            temperature_status=EpistemicStatus.UNKNOWN.value,
            temperature_confidence="unknown",
        ).build()
        a = next(r for r in measured.risks if r.category == RiskCategory.TEMPERATURE_UNCERTAINTY.value)
        b = next(r for r in unknown.risks if r.category == RiskCategory.TEMPERATURE_UNCERTAINTY.value)
        assert b.risk_score > a.risk_score
        assert b.uncertainty > a.uncertainty

    def test_unknown_temperature_risk_is_critical(self):
        assessment = self._builder(
            temperature_status=EpistemicStatus.UNKNOWN.value,
            temperature_confidence="unknown",
        ).build()
        temp_risk = next(
            r for r in assessment.risks if r.category == RiskCategory.TEMPERATURE_UNCERTAINTY.value
        )
        assert temp_risk.is_critical

    def test_abandoned_well_raises_integrity_risk(self):
        good = self._builder(integrity_status="good_condition").build()
        bad = self._builder(
            integrity_status="abandoned_no_access", well_status="abandoned"
        ).build()
        a = next(r for r in good.risks if r.category == RiskCategory.WELL_INTEGRITY.value)
        b = next(r for r in bad.risks if r.category == RiskCategory.WELL_INTEGRITY.value)
        assert b.risk_score > a.risk_score

    def test_long_distance_raises_network_risk(self):
        near = self._builder(distance_to_demand_m=300.0).build()
        far = self._builder(distance_to_demand_m=9000.0).build()
        a = next(r for r in near.risks if r.category == RiskCategory.NETWORK_DISTANCE.value)
        b = next(r for r in far.risks if r.category == RiskCategory.NETWORK_DISTANCE.value)
        assert b.risk_score > a.risk_score

    def test_open_loop_raises_groundwater_risk(self):
        closed = self._builder(requires_abstraction_licence=False).build()
        open_loop = self._builder(requires_abstraction_licence=True).build()
        a = next(r for r in closed.risks if r.category == RiskCategory.GROUNDWATER.value)
        b = next(r for r in open_loop.risks if r.category == RiskCategory.GROUNDWATER.value)
        assert b.risk_score > a.risk_score
        assert any("Environment Agency" in e for e in b.evidence)

    def test_lcoh_above_price_raises_heat_price_risk(self):
        good = self._builder(lcoh_p_per_kwh=5.0, heat_price_p_per_kwh=9.0).build()
        bad = self._builder(lcoh_p_per_kwh=15.0, heat_price_p_per_kwh=9.0).build()
        a = next(r for r in good.risks if r.category == RiskCategory.HEAT_PRICE.value)
        b = next(r for r in bad.risks if r.category == RiskCategory.HEAT_PRICE.value)
        assert b.risk_score > a.risk_score

    def test_single_off_taker_raises_connection_risk(self):
        single = self._builder(number_of_off_takers=1).build()
        many = self._builder(number_of_off_takers=25).build()
        a = next(r for r in single.risks if r.category == RiskCategory.CUSTOMER_CONNECTION.value)
        b = next(r for r in many.risks if r.category == RiskCategory.CUSTOMER_CONNECTION.value)
        assert a.risk_score > b.risk_score

    def test_salinity_raises_scaling_risk(self):
        fresh = self._builder(water_salinity_ppt=2.0).build()
        salty = self._builder(water_salinity_ppt=180.0).build()
        a = next(r for r in fresh.risks if r.category == RiskCategory.SCALING.value)
        b = next(r for r in salty.risks if r.category == RiskCategory.SCALING.value)
        assert b.risk_score > a.risk_score

    def test_aggregate_score_is_bounded_and_monotonic(self):
        low = self._builder(integrity_status="good_condition").build()
        high = self._builder(
            integrity_status="abandoned_no_access",
            well_status="abandoned",
            temperature_status=EpistemicStatus.UNKNOWN.value,
            temperature_confidence="unknown",
            distance_to_demand_m=15000.0,
        ).build()
        assert 0.0 <= low.aggregate_score <= 1.0
        assert 0.0 <= high.aggregate_score <= 1.0
        assert high.aggregate_score > low.aggregate_score

    def test_risks_serialise_completely(self):
        d = self._builder().build().to_dict()
        assert d["risk_count"] == len(required_categories())
        assert "aggregate_score" in d
        for risk in d["risks"]:
            for key in (
                "category", "probability", "impact", "uncertainty",
                "risk_score", "evidence", "mitigation",
            ):
                assert key in risk
