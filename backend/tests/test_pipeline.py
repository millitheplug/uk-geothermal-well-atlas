"""Unit tests for heat pump performance, network loss and the full pipeline."""

from __future__ import annotations

import pytest

from app.core.enums import EpistemicStatus, GeothermalConfiguration
from app.engineering.base import CalculationError, CalculationContext, Unit
from app.engineering.heatpump import (
    HeatPumpNotRequired,
    annual_heat_production,
    carnot_cop,
    heat_pump_electricity_kw,
    heat_pump_performance,
)
from app.engineering.network import (
    network_heat_loss,
    pipe_length_cost_factor,
    supply_temperature_penalty,
)
from app.engineering.pipeline import WellInputs, assess_well
from app.engineering.parameters import DEFAULTS, DEFAULTS_BY_KEY, ParameterSet
from app.engineering.risk import required_categories


class TestCarnot:
    def test_hand_computed(self):
        """Carnot COP = Tc / (Tc - Te). 293.15 K / 30 K = 9.77."""
        assert carnot_cop(263.15, 293.15) == pytest.approx(9.7717, abs=0.001)

    def test_smaller_lift_gives_higher_cop(self):
        small = carnot_cop(308.15, 313.15)
        large = carnot_cop(263.15, 343.15)
        assert small > large

    def test_inverted_temperatures_rejected(self):
        with pytest.raises(CalculationError, match="below"):
            carnot_cop(300.0, 280.0)


class TestHeatPumpPerformance:
    """All cases here use source temperatures that genuinely need a lift.

    A well hot enough to serve the supply temperature directly raises
    ``HeatPumpNotRequired`` rather than returning a COP, which is the correct
    design outcome and is tested separately below.
    """

    def test_hot_source_gives_higher_cop(self):
        hot = heat_pump_performance(source_temperature_c=60.0, supply_temperature_c=90.0)
        cold = heat_pump_performance(source_temperature_c=45.0, supply_temperature_c=90.0)
        assert hot.result > cold.result

    def test_higher_supply_gives_lower_cop(self):
        low = heat_pump_performance(source_temperature_c=60.0, supply_temperature_c=70.0)
        high = heat_pump_performance(source_temperature_c=60.0, supply_temperature_c=90.0)
        assert low.result > high.result

    def test_cop_is_always_below_carnot(self):
        result = heat_pump_performance(source_temperature_c=60.0, supply_temperature_c=70.0)
        assert result.result < result.intermediate_values["carnot_cop"]

    def test_result_is_plausible_for_a_typical_reuse_case(self):
        result = heat_pump_performance(source_temperature_c=55.0, supply_temperature_c=70.0)
        assert 3.0 < result.result < 7.0

    def test_result_is_labelled_estimate(self):
        result = heat_pump_performance(source_temperature_c=55.0, supply_temperature_c=70.0)
        assert result.status == EpistemicStatus.ESTIMATE

    def test_high_supply_warns_about_cascading(self):
        warnings = heat_pump_performance(
            source_temperature_c=55.0, supply_temperature_c=95.0
        ).warnings
        assert any("cascad" in w.lower() for w in warnings)

    def test_always_carries_a_ground_temperature_caveat(self):
        warnings = heat_pump_performance(
            source_temperature_c=60.0, supply_temperature_c=80.0
        ).warnings
        assert any("ground temperature" in w.lower() for w in warnings)

    def test_hot_source_raises_not_required(self):
        """A well hotter than the supply needs no pump. This must be explicit."""
        with pytest.raises(HeatPumpNotRequired, match="directly"):
            heat_pump_performance(source_temperature_c=95.0, supply_temperature_c=70.0)

    def test_not_required_is_a_calculation_error_subclass(self):
        assert issubclass(HeatPumpNotRequired, CalculationError)

    def test_impractically_small_lift_raises_not_required(self):
        """A 72 degC source against a 70 degC supply leaves 3.5 K of refrigerant lift.

        Carnot would put the COP above 20, which no machine approaches. The
        function refuses rather than returning a number that would flatter the
        scheme.
        """
        with pytest.raises(HeatPumpNotRequired, match="usable temperature lift"):
            heat_pump_performance(source_temperature_c=72.0, supply_temperature_c=70.0)

    def test_no_lift_at_all_raises_not_required(self):
        """Once the source exceeds the supply, no pump is needed at all."""
        with pytest.raises(HeatPumpNotRequired):
            heat_pump_performance(source_temperature_c=75.0, supply_temperature_c=70.0)

    def test_zero_source_temperature_rejected(self):
        with pytest.raises(CalculationError, match="source_temperature_c"):
            heat_pump_performance(source_temperature_c=0.0, supply_temperature_c=70.0)

    def test_invalid_mechanical_efficiency_rejected(self):
        with pytest.raises(CalculationError, match="mechanical_efficiency"):
            heat_pump_performance(
                source_temperature_c=60.0, supply_temperature_c=70.0, mechanical_efficiency=1.5
            )

    def test_monotonic_in_source_temperature(self):
        scores = [
            heat_pump_performance(source_temperature_c=t, supply_temperature_c=90.0).result
            for t in (40.0, 50.0, 60.0, 70.0, 80.0)
        ]
        assert scores == sorted(scores)

    def test_records_the_actual_lift(self):
        result = heat_pump_performance(source_temperature_c=60.0, supply_temperature_c=80.0)
        lift = result.intermediate_values["temperature_lift_k"]
        # supply_mean 77.5 + 5 approach, source 60 - 3 approach.
        assert lift == pytest.approx((77.5 + 5.0) - (60.0 - 3.0))


class TestHeatPumpElectricity:
    def test_hand_computed(self):
        """100 kW thermal at COP 4 -> 25 kW electrical."""
        result = heat_pump_electricity_kw(thermal_kw=100.0, cop=4.0)
        assert result.result == pytest.approx(25.0)

    def test_higher_cop_means_less_electricity(self):
        low = heat_pump_electricity_kw(thermal_kw=500.0, cop=2.5)
        high = heat_pump_electricity_kw(thermal_kw=500.0, cop=6.0)
        assert high.result < low.result

    def test_zero_cop_rejected(self):
        with pytest.raises(CalculationError, match="cop"):
            heat_pump_electricity_kw(thermal_kw=500.0, cop=0.0)

    def test_labelled_derived(self):
        result = heat_pump_electricity_kw(thermal_kw=100.0, cop=4.0)
        assert result.status == EpistemicStatus.DERIVED


class TestAnnualHeatProduction:
    def test_hand_computed(self):
        """500 kW, 3000 h, 0.6 CF, no losses -> 900,000 kWh."""
        result = annual_heat_production(
            thermal_kw=500.0, operating_hours_per_year=3000.0, capacity_factor=0.6
        )
        assert result.result == pytest.approx(900_000.0)

    def test_losses_reduce_delivered_heat(self):
        without = annual_heat_production(thermal_kw=500.0)
        with_losses = annual_heat_production(
            thermal_kw=500.0, network_loss_fraction=0.20
        )
        assert with_losses.result < without.result

    def test_absolute_loss_matches_fractional_loss(self):
        """Passing the two representations of the same loss must agree."""
        via_fraction = annual_heat_production(
            thermal_kw=500.0,
            operating_hours_per_year=3000.0,
            capacity_factor=0.6,
            network_loss_fraction=0.20,
        )
        via_kw = annual_heat_production(
            thermal_kw=500.0,
            operating_hours_per_year=3000.0,
            capacity_factor=0.6,
            network_heat_loss_kw=100.0,
        )
        assert via_fraction.result == pytest.approx(via_kw.result)

    def test_losses_exceeding_output_raise(self):
        """A network whose losses exceed the whole output must fail loudly.

        0.95 of 100 kW still leaves 5% deliverable, which is physically
        possible if absurd. The guard exists for the case where the route is so
        long that the loss calculation exceeds the source entirely, which is
        arithmetically impossible to serve.
        """
        with pytest.raises(CalculationError, match="exceed available heat"):
            annual_heat_production(
                thermal_kw=100.0,
                operating_hours_per_year=1000.0,
                capacity_factor=0.1,
                network_heat_loss_kw=150.0,
            )

    def test_always_warns_that_capacity_factor_is_assumed(self):
        warnings = annual_heat_production(thermal_kw=500.0).warnings
        assert any("assumption" in w for w in warnings)

    def test_invalid_capacity_factor_rejected(self):
        with pytest.raises(CalculationError, match="capacity_factor"):
            annual_heat_production(thermal_kw=500.0, capacity_factor=0.0)


class TestNetworkHeatLoss:
    def test_hand_computed(self):
        """10 kg/s, 70/40 degC, 1500 m, ground 10 degC, k=0.20.

        mean temp = 55; excess = 45
        pipe loss = 0.20 * 1500 * 45 / 1000 = 13.5 kW
        delivered = 10 * 4180 * 30 / 1000 = 1254 kW
        fraction = 13.5 / 1254 = 1.08%
        """
        result = network_heat_loss(
            flow_rate_kg_s=10.0,
            supply_temperature_c=70.0,
            return_temperature_c=40.0,
            pipe_length_m=1500.0,
        )
        assert result.result == pytest.approx(13.5)
        assert result.intermediate_values["loss_fraction"] == pytest.approx(0.0108, abs=0.0002)

    def test_longer_pipe_greater_loss(self):
        short = network_heat_loss(
            flow_rate_kg_s=10.0, supply_temperature_c=70.0,
            return_temperature_c=40.0, pipe_length_m=500.0,
        )
        long = network_heat_loss(
            flow_rate_kg_s=10.0, supply_temperature_c=70.0,
            return_temperature_c=40.0, pipe_length_m=5000.0,
        )
        assert long.result == pytest.approx(short.result * 10)

    def test_hotter_network_greater_loss(self):
        cool = network_heat_loss(
            flow_rate_kg_s=10.0, supply_temperature_c=50.0,
            return_temperature_c=30.0, pipe_length_m=1000.0,
        )
        hot = network_heat_loss(
            flow_rate_kg_s=10.0, supply_temperature_c=90.0,
            return_temperature_c=60.0, pipe_length_m=1000.0,
        )
        assert hot.result > cool.result

    def test_fixed_loss_is_added(self):
        base = network_heat_loss(
            flow_rate_kg_s=10.0, supply_temperature_c=70.0,
            return_temperature_c=40.0, pipe_length_m=1000.0,
        )
        with_fixed = network_heat_loss(
            flow_rate_kg_s=10.0, supply_temperature_c=70.0,
            return_temperature_c=40.0, pipe_length_m=1000.0,
            additional_fixed_loss_kw=5.0,
        )
        assert with_fixed.result == pytest.approx(base.result + 5.0)

    def test_network_cooler_than_ground_rejected(self):
        with pytest.raises(CalculationError, match="would gain heat"):
            network_heat_loss(
                flow_rate_kg_s=10.0, supply_temperature_c=8.0,
                return_temperature_c=6.0, pipe_length_m=1000.0, ground_temperature_c=12.0,
            )

    def test_return_above_supply_rejected(self):
        with pytest.raises(CalculationError, match="must be below"):
            network_heat_loss(
                flow_rate_kg_s=10.0, supply_temperature_c=40.0,
                return_temperature_c=70.0, pipe_length_m=1000.0,
            )


class TestNetworkHelpers:
    def test_pipe_cost_factor_increases_with_length(self):
        short = pipe_length_cost_factor(500.0)
        long = pipe_length_cost_factor(8000.0)
        assert long > short > 0

    def test_urban_route_is_dearer(self):
        assert pipe_length_cost_factor(2000.0, is_urban=True) > pipe_length_cost_factor(2000.0)

    def test_zero_length_rejected(self):
        with pytest.raises(CalculationError):
            pipe_length_cost_factor(0.0)

    def test_supply_penalty_is_one_when_source_is_hot_enough(self):
        assert supply_temperature_penalty(
            available_temperature_c=95.0, required_supply_temperature_c=70.0
        ) == 1.0

    def test_supply_penalty_reduces_for_a_cold_source(self):
        penalty = supply_temperature_penalty(
            available_temperature_c=55.0, required_supply_temperature_c=90.0
        )
        assert 0.0 < penalty < 1.0

    def test_penalty_never_reaches_zero_exactly(self):
        penalty = supply_temperature_penalty(
            available_temperature_c=45.0, required_supply_temperature_c=95.0
        )
        assert penalty > 0.0


class TestParameters:
    def test_every_default_has_a_rationale(self):
        for spec in DEFAULTS:
            assert spec.rationale, f"{spec.key} has no rationale"

    def test_every_default_names_its_source_or_its_judgement(self):
        for spec in DEFAULTS:
            assert spec.source or "judgement" in spec.rationale.lower() or spec.value is None

    def test_monte_carlo_inputs_declare_a_distribution(self):
        for spec in DEFAULTS:
            if spec.low is not None and spec.high is not None:
                assert spec.distribution, f"{spec.key} has a range but no distribution"

    def test_overrides_take_precedence(self):
        params = ParameterSet.build(overrides={"flow_rate_lps": 50.0})
        assert params["flow_rate_lps"] == 50.0
        assert params.overrides_applied["flow_rate_lps"] is True

    def test_scenario_applies_but_user_override_wins(self):
        params = ParameterSet.build(
            overrides={"flow_rate_lps": 50.0}, scenario={"flow_rate_lps": 10.0}
        )
        assert params["flow_rate_lps"] == 50.0

    def test_none_overrides_do_not_clobber_defaults(self):
        params = ParameterSet.build(overrides={"flow_rate_lps": None})
        assert params["flow_rate_lps"] == DEFAULTS_BY_KEY["flow_rate_lps"].value

    def test_unknowns_lists_the_gaps(self):
        params = ParameterSet.build()
        assert "source_temperature_c" in params.unknowns()

    def test_assumptions_exclude_unknown_values(self):
        params = ParameterSet.build()
        keys = {a.key for a in params.as_assumptions()}
        assert "source_temperature_c" not in keys
        assert "flow_rate_lps" in keys

    def test_assumptions_record_whether_they_are_defaults(self):
        params = ParameterSet.build(overrides={"flow_rate_lps": 50.0})
        ref = next(a for a in params.as_assumptions() if a.key == "flow_rate_lps")
        assert ref.is_default is False


def _good_well(**overrides) -> WellInputs:
    """A well with everything characterised, for pipeline tests."""
    defaults = dict(
        well_id="TEST-001",
        well_name="Test Well 1",
        latitude=53.4,
        longitude=-2.5,
        status="producing",
        original_purpose="gas",
        operator="Test Oil",
        licence="UK-OG-100",
        drilling_year=1985,
        total_depth_m=2000.0,
        tvd_m=1950.0,
        md_m=2050.0,
        formation="Millstone Grit",
        has_casing_record=True,
        # 62 degC needs a real heat pump lift to reach a 70 degC supply, so the
        # configuration-specific behaviour under test is exercised rather than
        # short-circuited by the "source is hotter than the network" path.
        temperature_c=62.0,
        temperature_depth_m=1950.0,
        temperature_status=EpistemicStatus.MEASURED.value,
        temperature_confidence="high",
        temperature_method="static_bht",
        temperature_measurements_c=[87.0, 88.0, 89.0],
        temperature_sources=["nsta", "bgs"],
        source_reliabilities=[0.92, 0.88],
        integrity_status="good_condition",
        annual_demand_kwh=6_000_000.0,
        peak_demand_kw=1200.0,
        number_of_buildings=30,
        nearest_building_distance_m=600.0,
        demand_confidence="high",
        required_supply_temperature_c=70.0,
        existing_network=True,
    )
    defaults.update(overrides)
    return WellInputs(**defaults)


class TestPipeline:
    def test_runs_end_to_end(self):
        result = assess_well(_good_well())
        assert result.feasibility_score > 0
        assert result.thermal_output_kw and result.thermal_output_kw > 0
        assert result.capex_gbp and result.capex_gbp > 0
        assert result.lcoh_p_per_kwh and result.lcoh_p_per_kwh > 0
        assert result.recommendation

    def test_is_deterministic(self):
        a = assess_well(_good_well())
        b = assess_well(_good_well())
        assert a.feasibility_score == b.feasibility_score
        assert a.capex_gbp == b.capex_gbp
        assert a.lcoh_p_per_kwh == b.lcoh_p_per_kwh

    def test_well_without_temperature_gets_no_thermal_output(self):
        result = assess_well(
            _good_well(temperature_c=None, temperature_status=EpistemicStatus.UNKNOWN.value,
                       temperature_confidence="unknown", temperature_measurements_c=[],
                       temperature_sources=[], source_reliabilities=[])
        )
        assert result.thermal_output_kw is None
        assert result.thermal_output_status == EpistemicStatus.UNKNOWN.value
        assert result.capex_gbp is None
        assert result.lcoh_p_per_kwh is None

    def test_missing_temperature_is_recorded_as_a_gap(self):
        result = assess_well(_good_well(temperature_c=None))
        assert any("temperature" in g.lower() for g in result.data_gaps)

    def test_missing_temperature_first_action_is_to_measure(self):
        result = assess_well(_good_well(temperature_c=None))
        assert "temperature" in result.next_action.lower()

    def test_missing_integrity_first_action_is_integrity_work(self):
        result = assess_well(_good_well(integrity_status=None))
        assert "integrity" in result.next_action.lower()

    def test_thermal_output_never_claimed_measured_without_a_flow_test(self):
        result = assess_well(_good_well(has_flow_test=False))
        assert result.thermal_output_status == EpistemicStatus.ESTIMATE.value
        assert result.thermal_output_status != EpistemicStatus.MEASURED.value

    def test_thermal_output_is_measured_with_a_flow_test(self):
        result = assess_well(_good_well(has_flow_test=True))
        assert result.thermal_output_status == EpistemicStatus.MEASURED.value

    def test_source_hot_enough_for_direct_heat_drops_the_heat_pump(self):
        """88 degC into a 70 degC network needs no lift, so no pump is fitted."""
        result = assess_well(_good_well(temperature_c=88.0))
        assert not result.configuration.endswith("plus_heat_pump")
        assert result.heat_pump_cop is None
        assert any("Heat pump removed" in w for w in result.warnings)

    def test_cold_well_needs_a_heat_pump(self):
        """62 degC cannot serve a 70 degC network directly, so a pump is required."""
        result = assess_well(_good_well(temperature_c=62.0))
        assert result.configuration.endswith("plus_heat_pump")
        assert result.heat_pump_cop and result.heat_pump_cop > 1.0
        assert any("heat pump is required" in w for w in result.warnings)

    def test_cold_well_still_extracts_meaningful_power(self):
        """A 62 degC well has 42 K of primary-circuit swing available.

        The swing is bounded by the heat pump's evaporator inlet limit, not by the
        network supply temperature. Treating the latter as the limit would
        understate a cold well's potential by an order of magnitude.
        """
        result = assess_well(_good_well(temperature_c=62.0))
        assert result.thermal_output_kw and result.thermal_output_kw > 500.0

    def test_abandoned_well_selects_closed_loop(self):
        """An abandoned well has no water chemistry record, so open loop is
        unavailable and the licensing burden of an abstraction licence is avoided."""
        result = assess_well(_good_well(status="abandoned", integrity_status="poor_unknown"))
        assert result.configuration.startswith("closed_loop")
        assert "abstraction" in " ".join(result.warnings).lower()

    def test_live_well_with_benign_chemistry_can_use_open_loop(self):
        result = assess_well(
            _good_well(
                status="producing",
                water_salinity_ppt=20.0,
                water_ph=7.2,
                scaling_tendency="low",
            )
        )
        assert result.configuration.startswith("open_loop")
        assert any("open loop plus heat pump is viable" in w for w in result.warnings)

    def test_live_well_with_unknown_chemistry_avoids_open_loop(self):
        result = assess_well(
            _good_well(status="producing", water_salinity_ppt=None, water_ph=None)
        )
        assert result.configuration.startswith("closed_loop")

    def test_live_well_with_benign_chemistry_can_use_open_loop(self):
        result = assess_well(
            _good_well(
                status="producing",
                water_salinity_ppt=20.0,
                water_ph=7.2,
                scaling_tendency="low",
            )
        )
        assert result.configuration == GeothermalConfiguration.OPEN_LOOP_PLUS_HEAT_PUMP.value

    def test_hotter_well_scores_higher(self):
        """55 degC and 72 degC both need a lift, so the comparison is clean."""
        cold = assess_well(_good_well(temperature_c=55.0))
        hot = assess_well(_good_well(temperature_c=72.0))
        assert hot.feasibility_score > cold.feasibility_score

    def test_hotter_well_extracts_more_power(self):
        cold = assess_well(_good_well(temperature_c=55.0))
        hot = assess_well(_good_well(temperature_c=72.0))
        assert hot.thermal_output_kw > cold.thermal_output_kw

    def test_better_integrity_scores_higher(self):
        good = assess_well(_good_well(integrity_status="good_condition"))
        poor = assess_well(_good_well(integrity_status="abandoned_no_access"))
        assert good.feasibility_score > poor.feasibility_score

    def test_more_demand_scores_higher(self):
        little = assess_well(_good_well(annual_demand_kwh=200_000.0))
        lots = assess_well(_good_well(annual_demand_kwh=12_000_000.0))
        assert lots.feasibility_score > little.feasibility_score

    def test_nearer_demand_scores_higher(self):
        near = assess_well(_good_well(nearest_building_distance_m=200.0))
        far = assess_well(_good_well(nearest_building_distance_m=9000.0))
        assert near.feasibility_score > far.feasibility_score

    def test_abandoned_well_costs_more_to_recommission(self):
        live = assess_well(_good_well())
        abandoned = assess_well(_good_well(status="abandoned", integrity_status="poor_unknown"))
        assert abandoned.capex_gbp > live.capex_gbp

    def test_no_flow_test_warning_is_always_present(self):
        result = assess_well(_good_well(has_flow_test=False))
        assert any("flow test" in w.lower() for w in result.warnings)

    def test_confidence_is_reported_separately_from_feasibility(self):
        result = assess_well(_good_well())
        assert 0.0 <= result.confidence_score <= 1.0
        assert 0.0 <= result.feasibility_score <= 100.0
        assert result.confidence_band

    def test_risk_register_covers_the_whole_taxonomy(self):
        result = assess_well(_good_well())
        assert len(result.risk_assessment.risks) == len(required_categories())

    def test_recommendation_always_has_a_rationale(self):
        result = assess_well(_good_well())
        assert result.recommendation_rationale

    def test_next_action_is_always_populated(self):
        for well in (
            _good_well(),
            _good_well(temperature_c=None),
            _good_well(integrity_status=None),
            _good_well(annual_demand_kwh=None),
        ):
            assert assess_well(well).next_action

    def test_calculation_trace_records_every_function(self):
        result = assess_well(_good_well())
        names = {t["function_name"] for t in result.calculation_trace["traces"]}
        assert "heat_extraction" in names
        assert "capex" in names
        assert "opex" in names
        assert "lcoh" in names
        assert "npv" in names
        assert "irr" in names

    def test_every_trace_exposes_the_six_required_fields(self):
        result = assess_well(_good_well())
        for trace in result.calculation_trace["traces"]:
            assert "inputs" in trace
            assert "input_units" in trace
            assert "formula" in trace
            assert "result" in trace
            assert "status" in trace
            assert "sources" in trace

    def test_serialises_to_a_complete_dict(self):
        d = assess_well(_good_well()).to_dict()
        for key in (
            "well_id", "configuration", "thermal", "network", "economics",
            "scores", "recommendation", "risk", "confidence_detail",
            "data_gaps", "calculation_trace",
        ):
            assert key in d
        assert d["thermal"]["status"]

    def test_unknown_flow_rate_scenario_runs(self):
        """The scenario runner must not crash on an implausible input."""
        result = assess_well(_good_well(), overrides={"flow_rate_lps": 5.0})
        assert result.thermal_output_kw and result.thermal_output_kw > 0

    def test_context_collects_traces(self):
        ctx = CalculationContext()
        assess_well(_good_well(), ctx=ctx)
        assert len(ctx.traces) > 10
        assert ctx.to_dict()["engine_version"]

    def test_lcoh_is_labelled_and_units_declared(self):
        result = assess_well(_good_well())
        trace = next(
            t for t in result.calculation_trace["traces"] if t["function_name"] == "lcoh"
        )
        assert trace["result_unit"] == Unit.PENCE_PER_KWH
        assert trace["status"] == EpistemicStatus.DERIVED.value
