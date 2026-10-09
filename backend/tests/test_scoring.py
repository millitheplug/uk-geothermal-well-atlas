"""Unit tests for feasibility scoring and the recommendation mapping."""

from __future__ import annotations

import pytest

from app.core.enums import DataConfidence, Recommendation, WellIntegrityStatus
from app.engineering.scoring import (
    SCORE_VERSION,
    WEIGHTS,
    composite_score,
    demand_score,
    economics_score,
    geometry_score,
    integrity_score,
    network_score,
    recommend,
    regulatory_score,
    thermal_score,
)


class TestWeights:
    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_specification_weights_are_respected(self):
        assert WEIGHTS["thermal"] == 0.25
        assert WEIGHTS["integrity"] == 0.20
        assert WEIGHTS["demand"] == 0.15
        assert WEIGHTS["economics"] == 0.15
        assert WEIGHTS["network"] == 0.10
        assert WEIGHTS["geometry"] == 0.05
        assert WEIGHTS["regulatory"] == 0.05
        assert WEIGHTS["data_confidence"] == 0.05

    def test_score_version_is_declared(self):
        assert SCORE_VERSION


class TestComposite:
    def test_all_ones_gives_one_hundred(self):
        assert composite_score(
            thermal=1, integrity=1, demand=1, economics=1,
            network=1, geometry=1, regulatory=1, data_confidence=1,
        ) == pytest.approx(100.0)

    def test_all_zeros_gives_zero(self):
        assert composite_score(
            thermal=0, integrity=0, demand=0, economics=0,
            network=0, geometry=0, regulatory=0, data_confidence=0,
        ) == pytest.approx(0.0)

    def test_half_everything_gives_fifty(self):
        assert composite_score(
            thermal=0.5, integrity=0.5, demand=0.5, economics=0.5,
            network=0.5, geometry=0.5, regulatory=0.5, data_confidence=0.5,
        ) == pytest.approx(50.0)

    def test_thermal_weight_dominates_a_thermal_only_difference(self):
        with_high_thermal = composite_score(
            thermal=1.0, integrity=0.5, demand=0.5, economics=0.5,
            network=0.5, geometry=0.5, regulatory=0.5, data_confidence=0.5,
        )
        with_low_thermal = composite_score(
            thermal=0.0, integrity=0.5, demand=0.5, economics=0.5,
            network=0.5, geometry=0.5, regulatory=0.5, data_confidence=0.5,
        )
        assert with_high_thermal - with_low_thermal == pytest.approx(25.0)

    def test_integrity_weight_is_second_largest(self):
        high = composite_score(
            thermal=0.5, integrity=1.0, demand=0.5, economics=0.5,
            network=0.5, geometry=0.5, regulatory=0.5, data_confidence=0.5,
        )
        low = composite_score(
            thermal=0.5, integrity=0.0, demand=0.5, economics=0.5,
            network=0.5, geometry=0.5, regulatory=0.5, data_confidence=0.5,
        )
        assert high - low == pytest.approx(20.0)

    def test_result_is_bounded(self):
        score = composite_score(
            thermal=5.0, integrity=5.0, demand=5.0, economics=5.0,
            network=5.0, geometry=5.0, regulatory=5.0, data_confidence=5.0,
        )
        assert score == pytest.approx(100.0)

    def test_is_deterministic(self):
        args = dict(
            thermal=0.7, integrity=0.6, demand=0.5, economics=0.4,
            network=0.3, geometry=0.2, regulatory=0.9, data_confidence=0.8,
        )
        assert composite_score(**args) == composite_score(**args)

    def test_bad_weights_rejected(self):
        bad = dict(WEIGHTS)
        bad["thermal"] = 0.5
        with pytest.raises(ValueError, match="sum to 1.0"):
            composite_score(
                thermal=0.5, integrity=0.5, demand=0.5, economics=0.5,
                network=0.5, geometry=0.5, regulatory=0.5, data_confidence=0.5,
                weights=bad,
            )


class TestThermalScore:
    def test_unknown_temperature_scores_zero(self):
        score, notes = thermal_score(source_temperature_c=None)
        assert score == 0.0
        assert any("cannot be assessed" in n for n in notes)

    def test_hot_well_outscores_cold_well(self):
        hot, _ = thermal_score(source_temperature_c=95.0, thermal_output_kw=800.0)
        cold, _ = thermal_score(source_temperature_c=45.0, thermal_output_kw=100.0)
        assert hot > cold

    def test_large_output_outscores_small_output(self):
        large, _ = thermal_score(source_temperature_c=80.0, thermal_output_kw=1500.0)
        small, _ = thermal_score(source_temperature_c=80.0, thermal_output_kw=40.0)
        assert large > small

    def test_measured_temperature_has_a_higher_ceiling_than_estimated(self):
        measured, _ = thermal_score(
            source_temperature_c=90.0,
            thermal_output_kw=800.0,
            is_measured=True,
            temperature_confidence=DataConfidence.LOW.value,
        )
        estimated, _ = thermal_score(
            source_temperature_c=90.0,
            thermal_output_kw=800.0,
            is_measured=False,
            temperature_confidence=DataConfidence.LOW.value,
        )
        assert estimated <= measured

    def test_estimated_temperature_is_capped(self):
        """The temperature-derived 65% of the score is capped at 55% for low confidence."""
        score, notes = thermal_score(
            source_temperature_c=150.0,
            thermal_output_kw=5000.0,
            is_measured=False,
            temperature_confidence=DataConfidence.LOW.value,
        )
        # temp_derived capped at 0.55, plus the uncapped output term 0.35.
        assert score == pytest.approx(0.55 + 0.35, abs=0.001)
        assert any("capped" in n for n in notes)

    def test_output_size_survives_the_temperature_cap(self):
        """A large well must still outrank a small one at equal temperature."""
        large, _ = thermal_score(
            source_temperature_c=80.0, thermal_output_kw=1500.0,
            temperature_confidence=DataConfidence.UNKNOWN.value,
        )
        small, _ = thermal_score(
            source_temperature_c=80.0, thermal_output_kw=40.0,
            temperature_confidence=DataConfidence.UNKNOWN.value,
        )
        assert large > small

    def test_measured_temperature_is_not_capped(self):
        score, _ = thermal_score(
            source_temperature_c=95.0,
            thermal_output_kw=1200.0,
            is_measured=True,
        )
        assert score > 0.8

    def test_cold_source_notes_that_a_heat_pump_is_needed(self):
        score, notes = thermal_score(source_temperature_c=50.0, target_supply_temperature_c=70.0)
        assert score < 0.4
        assert any("heat pump" in n.lower() for n in notes)

    def test_small_output_is_flagged(self):
        _, notes = thermal_score(source_temperature_c=85.0, thermal_output_kw=30.0)
        assert any("small" in n.lower() for n in notes)

    def test_score_is_bounded(self):
        for temp in (10.0, 50.0, 85.0, 120.0, 200.0):
            score, _ = thermal_score(source_temperature_c=temp, thermal_output_kw=1000.0)
            assert 0.0 <= score <= 1.0


class TestIntegrityScore:
    def test_unknown_integrity_is_scored_low_not_neutral(self):
        score, notes = integrity_score(integrity_status=None)
        assert score < 0.3
        assert any("not been assessed" in n for n in notes)

    def test_good_condition_beats_abandoned(self):
        good, _ = integrity_score(integrity_status=WellIntegrityStatus.GOOD_CONDITION.value)
        bad, _ = integrity_score(integrity_status=WellIntegrityStatus.POOR_UNKNOWN.value)
        assert good > bad

    def test_good_subscores_cannot_rescue_an_abandoned_well(self):
        """This is the ceiling behaviour that stops optimistic inputs winning."""
        optimistic, _ = integrity_score(
            integrity_status=WellIntegrityStatus.ABANDONED_NO_ACCESS.value,
            casing_condition_score=1.0,
            abandonment_score=1.0,
            access_score=1.0,
            wellhead_condition_score=1.0,
        )
        assert optimistic <= 0.30

    def test_missing_casing_record_penalises(self):
        with_record, _ = integrity_score(
            integrity_status=WellIntegrityStatus.GOOD_CONDITION.value, has_casing_record=True
        )
        without, notes = integrity_score(
            integrity_status=WellIntegrityStatus.GOOD_CONDITION.value, has_casing_record=False
        )
        assert without < with_record
        assert any("casing string" in n for n in notes)

    def test_score_is_bounded(self):
        for status in [s.value for s in WellIntegrityStatus]:
            score, _ = integrity_score(integrity_status=status)
            assert 0.0 <= score <= 1.0


class TestDemandScore:
    def test_no_demand_scores_zero(self):
        score, notes = demand_score(annual_demand_kwh=None, thermal_output_kw=500.0)
        assert score == 0.0
        assert notes

    def test_well_matched_demand_beats_massive_oversupply(self):
        matched, _ = demand_score(
            annual_demand_kwh=4_000_000.0, thermal_output_kw=500.0, number_of_buildings=25
        )
        starved, _ = demand_score(
            annual_demand_kwh=50_000.0, thermal_output_kw=500.0, number_of_buildings=1
        )
        assert matched > starved

    def test_single_off_taker_is_penalised(self):
        single, notes = demand_score(
            annual_demand_kwh=4_000_000.0, thermal_output_kw=500.0, number_of_buildings=1
        )
        many, _ = demand_score(
            annual_demand_kwh=4_000_000.0, thermal_output_kw=500.0, number_of_buildings=30
        )
        assert single < many
        assert any("one candidate off-taker" in n.lower() for n in notes)

    def test_low_demand_confidence_caps_the_score(self):
        high, _ = demand_score(
            annual_demand_kwh=4_000_000.0, thermal_output_kw=500.0,
            demand_confidence=DataConfidence.HIGH.value,
        )
        unknown, notes = demand_score(
            annual_demand_kwh=4_000_000.0, thermal_output_kw=500.0,
            demand_confidence=DataConfidence.UNKNOWN.value,
        )
        assert unknown < high
        assert any("capped" in n for n in notes)

    def test_peak_demand_mismatch_is_noted(self):
        _, notes = demand_score(
            annual_demand_kwh=4_000_000.0, thermal_output_kw=500.0, peak_demand_kw=20.0
        )
        assert any("oversized" in n for n in notes)


class TestNetworkScore:
    def test_unknown_distance_scores_zero(self):
        score, notes = network_score(distance_m=None)
        assert score == 0.0
        assert notes

    def test_shorter_is_better(self):
        near, _ = network_score(distance_m=300.0)
        far, _ = network_score(distance_m=8000.0)
        assert near > far

    def test_existing_network_helps(self):
        existing, _ = network_score(distance_m=1000.0, existing_network=True)
        greenfield, _ = network_score(distance_m=1000.0, existing_network=False)
        assert existing > greenfield

    def test_reinforcement_needed_hurts(self):
        ok, _ = network_score(distance_m=1000.0, existing_network=True, reinforcement_required=False)
        reinforced, _ = network_score(
            distance_m=1000.0, existing_network=True, reinforcement_required=True
        )
        assert reinforced < ok

    def test_long_route_is_flagged(self):
        _, notes = network_score(distance_m=9000.0)
        assert any("pipe cost" in n for n in notes)

    def test_score_is_bounded(self):
        for d in (0.0, 100.0, 1000.0, 5000.0, 50000.0):
            score, _ = network_score(distance_m=d)
            assert 0.0 <= score <= 1.0


class TestGeometryScore:
    def test_unknown_depth_scores_zero(self):
        score, _ = geometry_score(total_depth_m=None, tvd_m=None)
        assert score == 0.0

    def test_sweet_spot_beats_shallow_and_very_deep(self):
        sweet, _ = geometry_score(total_depth_m=2000.0, tvd_m=2000.0)
        shallow, _ = geometry_score(total_depth_m=300.0, tvd_m=300.0)
        very_deep, _ = geometry_score(total_depth_m=6000.0, tvd_m=6000.0)
        assert sweet > shallow
        assert sweet > very_deep

    def test_deviated_well_is_penalised(self):
        vertical, _ = geometry_score(total_depth_m=2000.0, tvd_m=2000.0, md_m=2000.0)
        deviated, notes = geometry_score(
            total_depth_m=2000.0, tvd_m=2000.0, md_m=2800.0, is_deviated=True
        )
        assert deviated < vertical
        assert any("deviated" in n.lower() for n in notes)

    def test_high_deviation_is_a_poor_candidate(self):
        score, notes = geometry_score(
            total_depth_m=2000.0, tvd_m=1500.0, md_m=2600.0,
            max_deviation_deg=75.0, is_deviated=True,
        )
        assert score < 0.6
        assert any("poor doublet candidate" in n for n in notes)

    def test_score_is_bounded(self):
        for depth in (100.0, 800.0, 2500.0, 8000.0):
            score, _ = geometry_score(total_depth_m=depth, tvd_m=depth)
            assert 0.0 <= score <= 1.0


class TestEconomicsScore:
    def test_missing_lcoh_scores_zero(self):
        score, notes = economics_score(lcoh_p_per_kwh=None, heat_price_p_per_kwh=8.5)
        assert score == 0.0
        assert notes

    def test_lcoh_below_price_beats_lcoh_above_price(self):
        good, _ = economics_score(lcoh_p_per_kwh=5.0, heat_price_p_per_kwh=8.5)
        bad, notes = economics_score(lcoh_p_per_kwh=14.0, heat_price_p_per_kwh=8.5)
        assert good > bad
        assert any("exceeds" in n for n in notes)

    def test_negative_npv_penalises(self):
        positive, _ = economics_score(lcoh_p_per_kwh=5.0, heat_price_p_per_kwh=8.5, npv_gbp=500e3)
        negative, notes = economics_score(lcoh_p_per_kwh=5.0, heat_price_p_per_kwh=8.5, npv_gbp=-500e3)
        assert negative < positive
        assert any("NPV is negative" in n for n in notes)

    def test_long_payback_penalises(self):
        quick, _ = economics_score(lcoh_p_per_kwh=6.0, heat_price_p_per_kwh=8.5, payback_years=4.0)
        slow, notes = economics_score(lcoh_p_per_kwh=6.0, heat_price_p_per_kwh=8.5, payback_years=22.0)
        assert slow < quick
        assert any("long" in n for n in notes)

    def test_score_is_bounded(self):
        for lcoh in (0.5, 5.0, 8.5, 20.0, 100.0):
            score, _ = economics_score(lcoh_p_per_kwh=lcoh, heat_price_p_per_kwh=8.5)
            assert 0.0 <= score <= 1.0


class TestRegulatoryScore:
    def test_closed_loop_beats_open_loop(self):
        closed, _ = regulatory_score(requires_abstraction_licence=False)
        open_loop, notes = regulatory_score(requires_abstraction_licence=True)
        assert closed > open_loop
        assert any("abstraction licence" in n for n in notes)

    def test_protected_site_hurts(self):
        normal, _ = regulatory_score()
        spa, notes = regulatory_score(is_spa=True)
        assert spa < normal
        assert any("Special Protection Area" in n for n in notes)

    def test_long_programme_hurts(self):
        quick, _ = regulatory_score(estimated_approval_months=4.0)
        slow, notes = regulatory_score(estimated_approval_months=30.0)
        assert slow < quick
        assert any("schedule risk" in n for n in notes)

    def test_score_is_bounded(self):
        worst = regulatory_score(
            requires_abstraction_licence=True,
            requires_discharge_consent=True,
            requires_planning_permission=True,
            is_spa=True,
            is_conservation_area=True,
            is_mining_subsidence_area=True,
            estimated_approval_months=48.0,
        )
        score, _ = worst
        assert 0.0 <= score <= 1.0


class TestRecommend:
    def test_high_score_high_confidence_is_high_priority(self):
        rec, reasons = recommend(feasibility_score=75.0, confidence_score=0.7)
        assert rec == Recommendation.HIGH_PRIORITY
        assert any("detailed due diligence" in r for r in reasons)

    def test_high_score_low_confidence_is_downgraded(self):
        rec, reasons = recommend(feasibility_score=75.0, confidence_score=0.2)
        assert rec != Recommendation.HIGH_PRIORITY
        assert any("discounted by 25%" in r for r in reasons)

    def test_very_low_score_is_do_not_pursue(self):
        rec, reasons = recommend(feasibility_score=12.0, confidence_score=0.6)
        assert rec == Recommendation.DO_NOT_PURSUE
        assert any("does not present a defensible case" in r for r in reasons)

    def test_middle_score_is_medium_priority(self):
        rec, _ = recommend(feasibility_score=50.0, confidence_score=0.5)
        assert rec == Recommendation.MEDIUM_PRIORITY

    def test_low_score_is_low_priority(self):
        rec, _ = recommend(feasibility_score=30.0, confidence_score=0.6)
        assert rec == Recommendation.LOW_PRIORITY

    def test_critical_risks_reduce_priority(self):
        without, _ = recommend(feasibility_score=70.0, confidence_score=0.7)
        with_risks, reasons = recommend(
            feasibility_score=70.0, confidence_score=0.7, critical_risk_count=5
        )
        assert with_risks != Recommendation.HIGH_PRIORITY or without == with_risks
        assert any("critical risks" in r for r in reasons)

    def test_reasoning_is_always_given(self):
        for score in (5.0, 30.0, 50.0, 80.0):
            _, reasons = recommend(feasibility_score=score, confidence_score=0.5)
            assert reasons, "every recommendation must explain itself"

    def test_lcoh_above_price_is_disclosed(self):
        _, reasons = recommend(
            feasibility_score=50.0, confidence_score=0.5,
            lcoh_p_per_kwh=12.0, heat_price_p_per_kwh=8.0,
        )
        assert any("not commercially competitive" in r for r in reasons)

    def test_data_gaps_are_disclosed(self):
        _, reasons = recommend(feasibility_score=50.0, confidence_score=0.5, data_gap_count=3)
        assert any("data gap" in r for r in reasons)

    def test_all_four_levels_are_reachable(self):
        levels = set()
        for feasibility in range(0, 101, 2):
            for confidence in (0.1, 0.4, 0.8):
                rec, _ = recommend(feasibility_score=float(feasibility), confidence_score=confidence)
                levels.add(rec)
        assert len(levels) == 4
