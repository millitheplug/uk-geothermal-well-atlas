"""Unit tests for the financial calculations.

Expected values are derived by hand from the printed formulas, so a change to
the arithmetic breaks a test rather than silently changing the answer.
"""

from __future__ import annotations

import pytest

from app.core.enums import EpistemicStatus, GeothermalConfiguration
from app.engineering.base import CalculationError, Unit
from app.engineering.cost import capex
from app.engineering.financial import (
    IrrResult,
    break_even,
    discounted_payback,
    irr,
    lcoh,
    npv,
    payback,
)
from app.engineering.opex import opex


def _crf(rate: float, years: int) -> float:
    """Capital recovery factor, spelled out for the tests to reuse."""
    return (rate * (1 + rate) ** years) / ((1 + rate) ** years - 1)


class TestLCOH:
    def test_hand_computed(self):
        """1.2m capex, 45k opex, 1.4 GWh, 8%, 20 yr.

        CRF(8%, 20) = 0.10185
        capital recovery = 1,200,000 * 0.10185 = 122,220
        EUAC = 122,220 + 45,000 = 167,220
        LCOH = 167,220 / 1,400,000 * 100 = 11.944 p/kWh
        """
        result = lcoh(
            capex_gbp=1_200_000.0,
            annual_opex_gbp=45_000.0,
            annual_heat_kwh=1_400_000.0,
            discount_rate=0.08,
            project_lifetime_years=20,
        )
        assert result.result == pytest.approx(11.944, abs=0.01)
        assert result.result_unit == Unit.PENCE_PER_KWH

    def test_matches_manual_euac(self):
        result = lcoh(
            capex_gbp=1_000_000.0,
            annual_opex_gbp=30_000.0,
            annual_heat_kwh=1_000_000.0,
            discount_rate=0.07,
            project_lifetime_years=25,
        )
        expected_euac = 1_000_000.0 * _crf(0.07, 25) + 30_000.0
        assert result.intermediate_values["equivalent_uniform_annual_cost_gbp"] == pytest.approx(
            expected_euac
        )

    def test_zero_discount_rate_rejected(self):
        with pytest.raises(CalculationError, match="discount_rate of zero"):
            lcoh(
                capex_gbp=1_000_000.0,
                annual_opex_gbp=30_000.0,
                annual_heat_kwh=1_000_000.0,
                discount_rate=0.0,
            )

    def test_zero_heat_rejected(self):
        with pytest.raises(CalculationError, match="annual_heat_kwh"):
            lcoh(
                capex_gbp=1_000_000.0,
                annual_opex_gbp=30_000.0,
                annual_heat_kwh=0.0,
            )

    def test_zero_opex_allowed(self):
        result = lcoh(
            capex_gbp=1_000_000.0,
            annual_opex_gbp=0.0,
            annual_heat_kwh=2_000_000.0,
            discount_rate=0.08,
        )
        assert result.result > 0

    def test_more_heat_lowers_lcoh(self):
        low = lcoh(capex_gbp=1e6, annual_opex_gbp=50e3, annual_heat_kwh=500e3)
        high = lcoh(capex_gbp=1e6, annual_opex_gbp=50e3, annual_heat_kwh=2e6)
        assert high.result < low.result

    def test_longer_life_lowers_lcoh(self):
        short = lcoh(capex_gbp=1e6, annual_opex_gbp=50e3, annual_heat_kwh=1e6, project_lifetime_years=10)
        long = lcoh(capex_gbp=1e6, annual_opex_gbp=50e3, annual_heat_kwh=1e6, project_lifetime_years=30)
        assert long.result < short.result

    def test_is_labelled_derived(self):
        assert lcoh(capex_gbp=1e6, annual_opex_gbp=50e3, annual_heat_kwh=1e6).status == (
            EpistemicStatus.DERIVED
        )


class TestNPV:
    def test_hand_computed(self):
        """100k capex, 30k/yr for 3 years, 10%.

        PV = 30000/1.1 + 30000/1.21 + 30000/1.331
           = 27272.73 + 24793.39 + 22539.44 = 74605.56
        NPV = 74605.56 - 100000 = -25394.44
        """
        result = npv(
            initial_capex_gbp=100_000.0,
            cash_flows=[30_000.0, 30_000.0, 30_000.0],
            discount_rate=0.10,
        )
        assert result.result == pytest.approx(-25_394.44, abs=0.01)

    def test_positive_when_recovered_with_room_to_spare(self):
        result = npv(
            initial_capex_gbp=100_000.0,
            cash_flows=[50_000.0] * 5,
            discount_rate=0.05,
        )
        assert result.result > 0

    def test_zero_npv_at_the_discount_rate(self):
        """If the cash flows discount to exactly the capex, NPV is zero."""
        rate = 0.10
        years = 10
        # Annuity factor for 10 years at 10% is 6.14457.
        payment = 100_000.0 / ((1 - (1 + rate) ** -years) / rate)
        result = npv(initial_capex_gbp=100_000.0, cash_flows=[payment] * years, discount_rate=rate)
        assert result.result == pytest.approx(0.0, abs=1.0)

    def test_empty_cash_flows_rejected(self):
        with pytest.raises(CalculationError, match="at least one year"):
            npv(initial_capex_gbp=100_000.0, cash_flows=[])

    def test_higher_discount_rate_reduces_npv(self):
        low = npv(initial_capex_gbp=100e3, cash_flows=[40e3] * 10, discount_rate=0.03)
        high = npv(initial_capex_gbp=100e3, cash_flows=[40e3] * 10, discount_rate=0.12)
        assert high.result < low.result

    def test_negative_intermediate_cash_flows_supported(self):
        result = npv(
            initial_capex_gbp=100_000.0,
            cash_flows=[10_000.0, -20_000.0, 50_000.0],
            discount_rate=0.05,
        )
        assert result.result is not None


class TestIRR:
    def test_known_case(self):
        """-1000, +500, +500, +500. IRR is close to 23.375%.

        Checked at 23%: 500/1.23 + 500/1.5129 + 500/1.8609 = 406.5 + 330.5 + 268.7 = 1005.7
        Checked at 24%: 500/1.24 + 500/1.5376 + 500/1.9066 = 403.2 + 325.2 + 262.2 = 990.6
        Root is between 23% and 24%, near 23.38%.
        """
        result = irr(initial_capex_gbp=1000.0, cash_flows=[500.0, 500.0, 500.0])
        assert result.result == pytest.approx(0.2338, abs=0.002)

    def test_zero_rate_project(self):
        """Exactly 1000 back over one year is a 0% IRR."""
        result = irr(initial_capex_gbp=1000.0, cash_flows=[1000.0])
        assert result.result == pytest.approx(0.0, abs=1e-5)

    def test_zero_capex_with_positive_flows_has_no_irr(self):
        """Nothing was invested, so there is no return rate to report.

        NPV never falls to zero - it is positive at every rate - so the bracket
        widens to its limit and reports no IRR rather than an invented one.
        """
        result = irr(initial_capex_gbp=0.0, cash_flows=[500.0, 500.0])
        assert result.result is None
        assert result.status == EpistemicStatus.UNKNOWN
        assert result.intermediate_values["outcome"] == IrrResult.NOT_CONVERGED.value
        assert any("stays positive" in w for w in result.warnings)

    def test_capital_staged_so_late_it_gives_a_deeply_negative_irr(self):
        """1m spent against 100/yr for 5 years never recovers at a positive rate.

        A valid root exists only at a large negative discount rate, which the
        bracket finds by extending downwards. This is reported rather than
        hidden, because "returns only at -84%" is itself the answer.
        """
        result = irr(initial_capex_gbp=1_000_000.0, cash_flows=[100.0] * 5)
        assert result.result is not None
        assert result.result < 0.0

    def test_multiple_sign_changes_reports_ambiguity(self):
        result = irr(initial_capex_gbp=1000.0, cash_flows=[2000.0, -1500.0, 2000.0])
        assert result.result is None
        assert result.intermediate_values["outcome"] == IrrResult.MULTIPLE_ROOTS.value
        assert any("ambiguous" in w for w in result.warnings)

    def test_typical_project_solves_within_the_initial_bracket(self):
        """A 20-year annuity of 320k against a 2m outlay returns about 15%.

        The default bracket of -95% to +1000% already contains the root, so no
        widening is required here.
        """
        result = irr(initial_capex_gbp=2_000_000.0, cash_flows=[320_000.0] * 20)
        assert result.result is not None
        assert 0.13 < result.result < 0.17
        assert result.intermediate_values["bracket_expansions"] == 0
        assert result.intermediate_values["outcome"] == IrrResult.SOLVED.value

    def test_capital_staged_so_late_it_only_returns_at_a_negative_rate(self):
        """1m against 100/yr over 5 years breaks even only at about -84%.

        A valid root exists inside the default bracket, and it is reported as the
        alarming answer it is rather than being hidden.
        """
        result = irr(initial_capex_gbp=1_000_000.0, cash_flows=[100.0] * 5)
        assert result.result is not None
        assert -0.90 < result.result < 0.0

    def test_converges_quickly_for_a_typical_project(self):
        """320 kW/yr for 20 years against a 2m outlay is roughly a 14% return."""
        result = irr(initial_capex_gbp=2_000_000.0, cash_flows=[320_000.0] * 20)
        assert result.result is not None
        assert 0.10 < result.result < 0.18
        assert result.intermediate_values["iterations"] < 100

    def test_higher_return_means_higher_irr(self):
        low = irr(initial_capex_gbp=1000.0, cash_flows=[100.0] * 10)
        high = irr(initial_capex_gbp=1000.0, cash_flows=[300.0] * 10)
        assert low.result is not None and high.result is not None
        assert high.result > low.result


class TestPayback:
    def test_hand_computed(self):
        """1.2m capex against 300k/yr -> 4.0 years."""
        result = payback(initial_capex_gbp=1_200_000.0, annual_cash_flow_gbp=300_000.0)
        assert result.result == pytest.approx(4.0)

    def test_discounted_payback_exceeds_simple(self):
        simple = payback(
            initial_capex_gbp=1_200_000.0, annual_cash_flow_gbp=300_000.0
        )
        discounted = payback(
            initial_capex_gbp=1_200_000.0,
            annual_cash_flow_gbp=300_000.0,
            discount_rate=0.08,
        )
        assert discounted.intermediate_values["discounted_payback_years"] > simple.result

    def test_long_payback_warns(self):
        result = payback(initial_capex_gbp=5_000_000.0, annual_cash_flow_gbp=100_000.0)
        assert result.result == pytest.approx(50.0)
        assert any("exceeds" in w for w in result.warnings)

    def test_zero_cash_flow_reports_never_recovers(self):
        """A scheme with zero net cash flow never pays back. Report, don't raise:
        this is a screening outcome, and one unviable well must not abort a
        national run."""
        result = payback(initial_capex_gbp=1_000_000.0, annual_cash_flow_gbp=0.0)
        assert result.result is None
        assert result.status == EpistemicStatus.UNKNOWN
        assert any("never recovered" in w for w in result.warnings)

    def test_negative_cash_flow_reports_no_payback(self):
        result = payback(initial_capex_gbp=1_000_000.0, annual_cash_flow_gbp=-50_000.0)
        assert result.result is None
        assert result.status == EpistemicStatus.UNKNOWN
        assert any("does not recover" in w for w in result.warnings)

    def test_none_cash_flow_rejected(self):
        with pytest.raises(CalculationError, match="annual_cash_flow_gbp"):
            payback(initial_capex_gbp=1_000_000.0, annual_cash_flow_gbp=None)


class TestDiscountedPayback:
    def test_recovers_within_horizon(self):
        """100k against 30k/yr undiscounted is 3.33 years; at 5% it is later."""
        result = discounted_payback(
            initial_capex_gbp=100_000.0,
            cash_flows=[30_000.0] * 10,
            discount_rate=0.05,
        )
        assert result.result is not None
        assert 3.3 < result.result < 4.0

    def test_does_not_recover_reports_none_and_warns(self):
        result = discounted_payback(
            initial_capex_gbp=1_000_000.0,
            cash_flows=[10_000.0] * 5,
            discount_rate=0.08,
        )
        assert result.result is None
        assert any("does not turn positive" in w for w in result.warnings)

    def test_empty_flows_rejected(self):
        with pytest.raises(CalculationError):
            discounted_payback(initial_capex_gbp=1000.0, cash_flows=[], discount_rate=0.08)


class TestBreakEven:
    def test_hand_computed(self):
        """1m capex, 50k opex, 1 GWh/yr, 8%, 20 yr, no heat pump.

        CRF(8%, 20) = 0.101853
        capital recovery = 101,853
        + opex 50,000 = 151,853
        / 1,000,000 kWh * 100 = 15.19 p/kWh
        """
        result = break_even(
            capex_gbp=1_000_000.0,
            annual_opex_gbp=50_000.0,
            annual_heat_kwh=1_000_000.0,
            discount_rate=0.08,
            project_lifetime_years=20,
        )
        assert result.result == pytest.approx(15.185, abs=0.01)

    def test_heat_pump_electricity_raises_break_even(self):
        without = break_even(
            capex_gbp=1e6,
            annual_opex_gbp=50e3,
            annual_heat_kwh=1e6,
            electricity_price_p_per_kwh=None,
        )
        with_pump = break_even(
            capex_gbp=1e6,
            annual_opex_gbp=50e3,
            annual_heat_kwh=1e6,
            electricity_price_p_per_kwh=15.0,
            heat_pump_cop=4.0,
        )
        assert with_pump.result > without.result

    def test_lower_heat_demand_raises_break_even(self):
        high_demand = break_even(capex_gbp=1e6, annual_opex_gbp=50e3, annual_heat_kwh=2e6)
        low_demand = break_even(capex_gbp=1e6, annual_opex_gbp=50e3, annual_heat_kwh=500e3)
        assert low_demand.result > high_demand.result

    def test_reports_electricity_break_even_with_a_pump(self):
        result = break_even(
            capex_gbp=1e6,
            annual_opex_gbp=50e3,
            annual_heat_kwh=1e6,
            electricity_price_p_per_kwh=15.0,
            heat_pump_cop=3.5,
        )
        assert result.intermediate_values["break_even_electricity_price_p_per_kwh"] is not None
        assert result.intermediate_values["break_even_electricity_price_p_per_kwh"] > 0

    def test_caveat_present_on_the_result(self):
        result = break_even(capex_gbp=1e6, annual_opex_gbp=50e3, annual_heat_kwh=1e6)
        assert any("break-even" in w.lower() for w in result.warnings)


class TestCapex:
    def test_breakdown_sums_to_total(self):
        result = capex(thermal_kw=500.0, pipe_length_m=1500.0, well_depth_m=2000.0)
        parts = [
            result.intermediate_values["plant_gbp"],
            result.intermediate_values["well_recompletion_gbp"],
            result.intermediate_values["network_gbp"],
            result.intermediate_values["substation_gbp"],
            result.intermediate_values["planning_and_consents_gbp"],
            result.intermediate_values["contingency_gbp"],
        ]
        assert result.result == pytest.approx(sum(parts))

    def test_deeper_well_costs_more(self):
        shallow = capex(thermal_kw=500.0, pipe_length_m=1500.0, well_depth_m=1000.0)
        deep = capex(thermal_kw=500.0, pipe_length_m=1500.0, well_depth_m=4000.0)
        assert deep.result > shallow.result

    def test_longer_pipe_costs_more(self):
        short = capex(thermal_kw=500.0, pipe_length_m=500.0)
        long = capex(thermal_kw=500.0, pipe_length_m=5000.0)
        assert long.result > short.result

    def test_no_well_depth_means_no_recompletion_cost(self):
        result = capex(thermal_kw=500.0, pipe_length_m=1000.0, well_depth_m=None)
        assert result.intermediate_values["well_recompletion_gbp"] == 0.0

    def test_zero_contingency_reduces_total(self):
        with_contingency = capex(thermal_kw=500.0, pipe_length_m=1000.0)
        without = capex(thermal_kw=500.0, pipe_length_m=1000.0, contingency_fraction=0.0)
        assert without.result < with_contingency.result
        assert without.intermediate_values["contingency_gbp"] == 0.0

    def test_urban_route_costs_more(self):
        rural = capex(thermal_kw=500.0, pipe_length_m=2000.0, is_urban_route=False)
        urban = capex(thermal_kw=500.0, pipe_length_m=2000.0, is_urban_route=True)
        assert urban.result > rural.result

    def test_heat_pump_configuration_costs_more_to_equip(self):
        closed = capex(
            thermal_kw=500.0,
            pipe_length_m=1000.0,
            configuration=GeothermalConfiguration.CLOSED_LOOP,
        )
        with_pump = capex(
            thermal_kw=500.0,
            pipe_length_m=1000.0,
            configuration=GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP,
        )
        assert with_pump.result > closed.result

    def test_labelled_estimate_with_confidence(self):
        result = capex(thermal_kw=500.0, pipe_length_m=1000.0)
        assert result.status == EpistemicStatus.ESTIMATE
        assert result.confidence is not None and result.confidence < 0.5


class TestOpex:
    def test_closed_loop_avoids_abstraction_and_chemistry_costs(self):
        closed = opex(
            capex_gbp=2_000_000.0,
            thermal_kw=500.0,
            annual_heat_kwh=1_000_000.0,
            pipe_length_m=1500.0,
            configuration=GeothermalConfiguration.CLOSED_LOOP,
            water_mass_flow_kg_s=None,
        )
        open_loop = opex(
            capex_gbp=2_000_000.0,
            thermal_kw=500.0,
            annual_heat_kwh=1_000_000.0,
            pipe_length_m=1500.0,
            configuration=GeothermalConfiguration.OPEN_LOOP,
            water_mass_flow_kg_s=20.0,
        )
        assert open_loop.result > closed.result
        assert closed.intermediate_values["abstraction_gbp"] == 0.0
        assert open_loop.intermediate_values["abstraction_gbp"] > 0.0

    def test_open_loop_requires_flow_rate(self):
        with pytest.raises(CalculationError, match="water_mass_flow_kg_s"):
            opex(
                capex_gbp=2_000_000.0,
                thermal_kw=500.0,
                annual_heat_kwh=1_000_000.0,
                pipe_length_m=1500.0,
                configuration=GeothermalConfiguration.OPEN_LOOP,
                water_mass_flow_kg_s=None,
            )

    def test_breakdown_sums_to_total(self):
        result = opex(
            capex_gbp=2_000_000.0,
            thermal_kw=500.0,
            annual_heat_kwh=1_000_000.0,
            pipe_length_m=1500.0,
            configuration=GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP,
        )
        parts = [
            result.intermediate_values[k]
            for k in (
                "plant_fixed_gbp",
                "network_fixed_gbp",
                "heat_pump_service_gbp",
                "abstraction_gbp",
                "chemistry_gbp",
                "insurance_gbp",
                "land_lease_gbp",
            )
        ]
        assert result.result == pytest.approx(sum(parts))

    def test_fixed_costs_dominate_at_small_scale(self):
        """The reason small geothermal schemes struggle is arithmetic, not technology."""
        small = opex(
            capex_gbp=300_000.0,
            thermal_kw=50.0,
            annual_heat_kwh=100_000.0,
            pipe_length_m=800.0,
        )
        large = opex(
            capex_gbp=6_000_000.0,
            thermal_kw=2000.0,
            annual_heat_kwh=6_000_000.0,
            pipe_length_m=4000.0,
        )
        assert small.result / 100_000.0 > large.result / 6_000_000.0
