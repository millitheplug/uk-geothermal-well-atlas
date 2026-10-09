"""Unit tests for the thermal model.

Every expected value here is computed by hand from the formula, not copied from
a previous run of the code. If the implementation drifts, these fail.
"""

from __future__ import annotations

import pytest

from app.core.enums import EpistemicStatus, GeothermalConfiguration
from app.engineering.base import CalculationError, Unit
from app.engineering.thermal import (
    SPECIFIC_HEAT_WATER_J_KG_K,
    heat_extraction,
    heat_extraction_uncertainty_band,
    litres_per_second_to_kg_per_second,
    sustainable_temperature_drop,
    thermal_power,
)


class TestThermalPower:
    def test_basic_relationship(self):
        """Q = m_dot * cp * dT. 10 kg/s, 4180 J/(kg.K), 20 K -> 836,000 W."""
        result = thermal_power(
            mass_flow_kg_s=10.0,
            specific_heat_j_kg_k=4180.0,
            delta_temperature_c=20.0,
        )
        assert result.result == pytest.approx(836_000.0)
        assert result.result_unit == Unit.WATT
        assert result.formula == "Q = m_dot * cp * dT"

    def test_units_are_reported(self):
        result = thermal_power(10.0, 4180.0, 20.0)
        assert result.input_units["mass_flow_kg_s"] == "kg/s"
        assert result.input_units["delta_temperature_c"] == "K"

    def test_is_labelled_derived_by_default(self):
        result = thermal_power(10.0, 4180.0, 20.0)
        assert result.status == EpistemicStatus.DERIVED

    def test_can_be_labelled_measured(self):
        result = thermal_power(10.0, 4180.0, 20.0, status=EpistemicStatus.MEASURED)
        assert result.status == EpistemicStatus.MEASURED

    def test_zero_delta_temperature_rejected(self):
        with pytest.raises(CalculationError, match="delta_temperature_c"):
            thermal_power(10.0, 4180.0, 0.0)

    def test_negative_flow_rejected(self):
        with pytest.raises(CalculationError, match="mass_flow_kg_s"):
            thermal_power(-5.0, 4180.0, 20.0)

    def test_none_flow_rejected(self):
        with pytest.raises(CalculationError, match="mass_flow_kg_s"):
            thermal_power(None, 4180.0, 20.0)

    def test_infinite_flow_rejected(self):
        with pytest.raises(CalculationError, match="finite"):
            thermal_power(float("inf"), 4180.0, 20.0)

    def test_linear_in_delta_t(self):
        a = thermal_power(10.0, 4180.0, 10.0).result
        b = thermal_power(10.0, 4180.0, 20.0).result
        assert b == pytest.approx(2 * a)

    def test_linear_in_flow(self):
        a = thermal_power(5.0, 4180.0, 20.0).result
        b = thermal_power(10.0, 4180.0, 20.0).result
        assert b == pytest.approx(2 * a)

    def test_zero_division_safety(self):
        """cp of zero is physically meaningless and must be rejected."""
        with pytest.raises(CalculationError):
            thermal_power(10.0, 0.0, 20.0)


class TestFlowConversion:
    def test_one_litre_per_second_is_one_kilogram_per_second(self):
        assert litres_per_second_to_kg_per_second(1.0) == pytest.approx(1.0)

    def test_twenty_five_litres_per_second(self):
        assert litres_per_second_to_kg_per_second(25.0) == pytest.approx(25.0)

    def test_zero_rejected(self):
        with pytest.raises(CalculationError):
            litres_per_second_to_kg_per_second(0.0)


class TestHeatExtraction:
    def test_hand_computed_case(self):
        """25 L/s, 4180 J/(kg.K), 85 to 65 degC, no derating.

        mass flow = 25 kg/s; dT = 20 K
        Q = 25 * 4180 * 20 = 2,090,000 W = 2090 kW
        """
        result = heat_extraction(
            source_temperature_c=85.0,
            return_temperature_c=65.0,
            flow_rate_lps=25.0,
        )
        assert result.thermal_kw.result == pytest.approx(2090.0)
        assert result.mass_flow_kg_s == pytest.approx(25.0)
        assert result.delta_t_c == pytest.approx(20.0)

    def test_utilisation_factor_scales_linearly(self):
        base = heat_extraction(
            source_temperature_c=85.0, return_temperature_c=65.0, flow_rate_lps=25.0
        )
        derated = heat_extraction(
            source_temperature_c=85.0,
            return_temperature_c=65.0,
            flow_rate_lps=25.0,
            utilisation_factor=0.8,
        )
        assert derated.thermal_kw.result == pytest.approx(base.thermal_kw.result * 0.8)

    def test_result_is_labelled_estimate_not_measured(self):
        """The critical guarantee: no output is ever claimed as measured without a flow test."""
        result = heat_extraction(
            source_temperature_c=85.0, return_temperature_c=65.0, flow_rate_lps=25.0
        )
        assert result.thermal_kw.status == EpistemicStatus.ESTIMATE
        assert result.thermal_kw.status != EpistemicStatus.MEASURED

    def test_carries_no_flow_test_warning(self):
        result = heat_extraction(
            source_temperature_c=85.0, return_temperature_c=65.0, flow_rate_lps=25.0
        )
        assert any("flow test" in w for w in result.thermal_kw.warnings)

    def test_return_above_source_rejected(self):
        with pytest.raises(CalculationError, match="must be lower"):
            heat_extraction(
                source_temperature_c=65.0, return_temperature_c=85.0, flow_rate_lps=25.0
            )

    def test_equal_temperatures_rejected(self):
        with pytest.raises(CalculationError):
            heat_extraction(
                source_temperature_c=70.0, return_temperature_c=70.0, flow_rate_lps=25.0
            )

    def test_out_of_range_utilisation_rejected(self):
        with pytest.raises(CalculationError, match="utilisation_factor"):
            heat_extraction(
                source_temperature_c=85.0,
                return_temperature_c=65.0,
                flow_rate_lps=25.0,
                utilisation_factor=0.2,
            )

    def test_zero_flow_rejected(self):
        with pytest.raises(CalculationError, match="flow_rate_lps"):
            heat_extraction(
                source_temperature_c=85.0, return_temperature_c=65.0, flow_rate_lps=0.0
            )

    def test_zero_delta_t_only(self):
        """A 0.001 K swing gives a tiny but positive result."""
        result = heat_extraction(
            source_temperature_c=85.0, return_temperature_c=84.999, flow_rate_lps=25.0
        )
        assert 0 < result.thermal_kw.result < 0.2

    def test_swing_dominated_by_flow_at_constant_delta_t(self):
        """Doubling flow doubles output; this is the linearity the whole model rests on."""
        low = heat_extraction(source_temperature_c=90.0, return_temperature_c=50.0, flow_rate_lps=10.0)
        high = heat_extraction(source_temperature_c=90.0, return_temperature_c=50.0, flow_rate_lps=20.0)
        assert high.thermal_kw.result == pytest.approx(low.thermal_kw.result * 2.0)

    def test_bigger_swing_gives_more_power_at_same_flow(self):
        small = heat_extraction(source_temperature_c=90.0, return_temperature_c=80.0, flow_rate_lps=20.0)
        large = heat_extraction(source_temperature_c=90.0, return_temperature_c=50.0, flow_rate_lps=20.0)
        assert large.thermal_kw.result > small.thermal_kw.result

    def test_all_four_configurations_supported(self):
        for config in GeothermalConfiguration:
            result = heat_extraction(
                source_temperature_c=85.0,
                return_temperature_c=65.0,
                flow_rate_lps=25.0,
                configuration=config,
            )
            assert result.thermal_kw.result == pytest.approx(2090.0)
            assert result.configuration == config

    def test_configuration_recorded_in_inputs(self):
        result = heat_extraction(
            source_temperature_c=85.0,
            return_temperature_c=65.0,
            flow_rate_lps=25.0,
            configuration=GeothermalConfiguration.OPEN_LOOP,
        )
        assert result.thermal_kw.inputs["configuration"] == "open_loop"

    def test_result_serialises_with_full_provenance(self):
        result = heat_extraction(
            source_temperature_c=85.0, return_temperature_c=65.0, flow_rate_lps=25.0
        )
        d = result.thermal_kw.to_dict()
        for key in ("inputs", "input_units", "formula", "result", "status", "sources", "assumptions"):
            assert key in d
        assert d["sources"], "a calculation must cite at least one source"

    def test_uses_documented_specific_heat(self):
        assert SPECIFIC_HEAT_WATER_J_KG_K == 4180.0


class TestUncertaintyBand:
    def test_band_brackets_the_central_value(self):
        low, mid, high = heat_extraction_uncertainty_band(
            source_temperature_c=85.0,
            temperature_uncertainty_c=10.0,
            flow_rate_lps=25.0,
            flow_uncertainty_pct=40.0,
            return_temperature_c=65.0,
        )
        assert low < mid < high

    def test_zero_uncertainty_gives_zero_width_band(self):
        low, mid, high = heat_extraction_uncertainty_band(
            source_temperature_c=85.0,
            temperature_uncertainty_c=0.0,
            flow_rate_lps=25.0,
            flow_uncertainty_pct=0.0,
            return_temperature_c=65.0,
        )
        assert low == pytest.approx(mid)
        assert high == pytest.approx(mid)

    def test_wider_uncertainty_widens_band(self):
        narrow_low, _, narrow_high = heat_extraction_uncertainty_band(
            source_temperature_c=85.0,
            temperature_uncertainty_c=5.0,
            flow_rate_lps=25.0,
            flow_uncertainty_pct=10.0,
            return_temperature_c=65.0,
        )
        wide_low, _, wide_high = heat_extraction_uncertainty_band(
            source_temperature_c=85.0,
            temperature_uncertainty_c=25.0,
            flow_rate_lps=25.0,
            flow_uncertainty_pct=60.0,
            return_temperature_c=65.0,
        )
        assert (wide_high - wide_low) > (narrow_high - narrow_low)

    def test_unknown_temperature_gives_wide_band(self):
        """An unknown-confidence well must not present a tight band."""
        _, _, confident_high = heat_extraction_uncertainty_band(
            source_temperature_c=85.0,
            temperature_uncertainty_c=3.0,
            flow_rate_lps=25.0,
            flow_uncertainty_pct=15.0,
            return_temperature_c=65.0,
        )
        _, _, unknown_high = heat_extraction_uncertainty_band(
            source_temperature_c=85.0,
            temperature_uncertainty_c=30.0,
            flow_rate_lps=25.0,
            flow_uncertainty_pct=60.0,
            return_temperature_c=65.0,
        )
        assert unknown_high > confident_high * 1.2


class TestSustainableTemperatureDrop:
    def test_basic_case(self):
        """85 degC source, 70 degC supply, 5 K margin -> 10 K usable."""
        assert sustainable_temperature_drop(
            source_temperature_c=85.0, target_supply_temperature_c=70.0
        ) == pytest.approx(10.0)

    def test_too_cold_raises(self):
        with pytest.raises(CalculationError, match="heat pump is required"):
            sustainable_temperature_drop(
                source_temperature_c=60.0, target_supply_temperature_c=70.0
            )

    def test_margin_is_deducted(self):
        with_margin = sustainable_temperature_drop(
            source_temperature_c=85.0, target_supply_temperature_c=70.0, minimum_return_margin_c=5.0
        )
        without_margin = sustainable_temperature_drop(
            source_temperature_c=85.0, target_supply_temperature_c=70.0, minimum_return_margin_c=1.0
        )
        assert without_margin > with_margin
