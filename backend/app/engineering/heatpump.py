"""Heat pump performance.

COP is not a constant and is certainly not a free parameter. It is estimated
here from three things that are physically meaningful:

* the source temperature actually available;
* the lift the pump has to achieve (condensing and evaporating temperatures); and
* the Carnot limit implied by those temperatures.

The result is then derated for part-load operation and for the parasitic losses
of the real machine. Every derating factor is a named input with a default and
a rationale, so a reviewer can see exactly how much optimism is being applied.

For an existing oil or gas well the dominant term is usually not the
thermodynamics but the *sustainable temperature swing* of the borehole, which is
handled in :mod:`app.engineering.thermal`.
"""

from __future__ import annotations

import math

from app.core.enums import EpistemicStatus
from app.engineering.base import (
    CalcResult,
    CalculationContext,
    CalculationError,
    SourceRef,
    Unit,
    require_positive,
)

SOURCE_COP_TEMPERATURE = SourceRef(
    name="IEA Heat Pump Programme / IEA Future of Heat Pumps report, seasonal performance vs source temperature",
    url="https://www.iea.org/reports/the-future-of-heat-pumps",
    citation="COP declines approximately linearly with lift; SCOP ~3 at 30 degC source, ~5.5 at 50 degC",
)

DEFAULT_PART_LOAD_DERATE = 0.92
"""Assumed ratio of seasonal COP to rated COP for a heat load with realistic
weather-driven part-load behaviour."""

DEFAULT_MECHANICAL_EFFICIENCY = 0.80
"""Fraction of electricity that reaches the refrigerant cycle after compressor,
motor and control losses. Applied as a multiplier, not a divisor: the losses are
already inside the measured seasonal COP of a real machine."""

DEFAULT_CARNOT_RATIO = 0.30
"""Real-machine performance as a fraction of Carnot.

Lower than the 0.5 sometimes quoted in theory because Carnot ignores the
irreversibilities that dominate a real cycle: compression is not isothermal,
throttling is genuinely irreversible, and heat exchangers have finite approach
temperatures. 0.30 reproduces published seasonal performance for water-source
machines at geothermal lifts."""

EVAPORATOR_APPROACH_K = 3.0
"""Temperature difference across the primary-side heat exchanger. The refrigerant
sits 3 K below the source water."""

CONDENSER_APPROACH_K = 5.0
"""Temperature difference across the secondary-side heat exchanger. The
refrigerant sits 5 K above the flow temperature."""

MINIMUM_EVAPORATOR_INLET_C = 20.0
"""Coldest primary-circuit water a plate heat exchanger will pass to a heat pump.

This, not the network supply temperature, is what limits the usable temperature
swing in the primary circuit. A heat pump can lift water from 20 degC, so a 55
degC well has 35 K of swing available even though it cannot serve a 70 degC
network directly. Conflating the two would understate a cold well's potential by
an order of magnitude."""

MINIMUM_PRACTICAL_LIFT_K = 10.0
"""Below this lift the Carnot COP diverges towards infinity and no real compressor
would be selected: the machine would cycle continuously, the capacity would be
negligible, and the theoretical COP would be a meaningless number. A lift this
small means the well should serve the circuit directly, or the network should
run at a lower supply temperature."""


class HeatPumpNotRequired(CalculationError):
    """The source is already at or above the target supply temperature.

    Not an error condition but a design outcome: at this temperature the heat
    can be delivered directly and a heat pump would add cost and parasitic load
    for no benefit. Raised so callers can downgrade the configuration explicitly
    rather than receiving a meaningless COP.
    """


def carnot_cop(evaporating_temperature_k: float, condensing_temperature_k: float) -> float:
    """Theoretical maximum COP between two absolute temperatures."""
    if evaporating_temperature_k <= 0 or condensing_temperature_k <= 0:
        raise CalculationError("temperatures must be positive absolute values")
    if evaporating_temperature_k >= condensing_temperature_k:
        raise CalculationError(
            "evaporating temperature must be below condensing temperature"
        )
    return condensing_temperature_k / (condensing_temperature_k - evaporating_temperature_k)


def heat_pump_performance(
    *,
    source_temperature_c: float,
    supply_temperature_c: float,
    return_temperature_c: float | None = None,
    part_load_derate: float = DEFAULT_PART_LOAD_DERATE,
    mechanical_efficiency: float = DEFAULT_MECHANICAL_EFFICIENCY,
    carnot_ratio: float = DEFAULT_CARNOT_RATIO,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Seasonal coefficient of performance for a geothermal heat pump.

    Method:

    1. Convert the source and supply temperatures to Kelvin.
    2. Compute the Carnot COP for that temperature pair.
    3. Apply a realistic ratio of real-world to Carnot performance. This is the
       single most contestable number in the module, so it is an explicit input
       with a documented default rather than a buried constant.
    4. Apply part-load and mechanical derating.

    Args:
        source_temperature_c: Available source temperature, i.e. the well.
        supply_temperature_c: Required flow temperature to the network.
        return_temperature_c: Required return temperature. Defaults to
            ``supply - 5 K``, a low-temperature differential typical of modern
            district heating.
        part_load_derate: Seasonal-to-rated COP ratio.
        mechanical_efficiency: Fraction of electricity reaching the cycle.

    Returns:
        CalcResult in dimensionless COP units.

    Raises:
        HeatPumpNotRequired: when the source is already hot enough to serve the
            circuit directly. Callers should downgrade to a no-pump
            configuration rather than handling this as a failure.

    Example:
        55 degC source, 70 degC supply, 65 degC return -> COP around 4.6.
    """
    require_positive(source_temperature_c, "source_temperature_c")
    require_positive(supply_temperature_c, "supply_temperature_c")
    require_positive(part_load_derate, "part_load_derate")
    if not 0 < mechanical_efficiency <= 1.0:
        raise CalculationError(
            f"mechanical_efficiency must be in (0, 1], got {mechanical_efficiency}"
        )

    effective_return = (
        return_temperature_c
        if return_temperature_c is not None
        else supply_temperature_c - 5.0
    )
    mean_supply_c = (supply_temperature_c + effective_return) / 2.0

    # Check the design intent before computing a COP. If the source is already
    # warmer than the circuit needs, the correct answer is "no heat pump", and
    # a COP number would be meaningless.
    if source_temperature_c >= supply_temperature_c + CONDENSER_APPROACH_K:
        raise HeatPumpNotRequired(
            f"source temperature {source_temperature_c:.1f} degC already exceeds the "
            f"{supply_temperature_c:.1f} degC supply temperature by more than the "
            f"{CONDENSER_APPROACH_K:.0f} K condenser approach. Heat can be delivered "
            "directly and a heat pump would add cost and parasitic load for no benefit."
        )

    # Refrigerant temperatures, allowing for finite heat-exchanger approaches.
    evaporating_k = source_temperature_c - EVAPORATOR_APPROACH_K + 273.15
    condensing_k = mean_supply_c + CONDENSER_APPROACH_K + 273.15

    lift_k = condensing_k - evaporating_k
    if lift_k < MINIMUM_PRACTICAL_LIFT_K:
        raise HeatPumpNotRequired(
            f"the usable temperature lift is only {lift_k:.1f} K after allowing for "
            f"{EVAPORATOR_APPROACH_K:.0f} K evaporator and {CONDENSER_APPROACH_K:.0f} K "
            f"condenser approaches. No compressor is viable below about "
            f"{MINIMUM_PRACTICAL_LIFT_K:.0f} K, and the implied COP would be "
            "meaningless. Deliver heat directly instead."
        )

    carnot = carnot_cop(evaporating_k, condensing_k)

    rated_cop = carnot * carnot_ratio

    # Second-law degradation at higher condensing temperatures.
    condensing_penalty = 1.0 - 0.004 * max(0.0, supply_temperature_c - 60.0)
    rated_cop *= max(0.2, condensing_penalty)

    seasonal_cop = rated_cop * part_load_derate * mechanical_efficiency

    warnings: list[str] = []
    if seasonal_cop > 8.0:
        warnings.append(
            f"A COP of {seasonal_cop:.1f} at {supply_temperature_c} degC supply is "
            "at the optimistic end of what commercial machines achieve. Verify against "
            "manufacturer data at the design point before relying on it."
        )
    if supply_temperature_c >= 90.0:
        warnings.append(
            "Supply temperatures at or above 90 degC normally require cascading or a "
            "high-temperature cascade, which reduces net COP significantly."
        )
    warnings.append(
        "COP is estimated from source and supply temperatures only. Ground temperature "
        "diversity, borehole thermal response and control strategy are not modelled."
    )

    result = CalcResult(
        function_name="heat_pump_performance",
        result=seasonal_cop,
        result_unit=Unit.DIMENSIONLESS,
        inputs={
            "source_temperature_c": source_temperature_c,
            "supply_temperature_c": supply_temperature_c,
            "return_temperature_c": effective_return,
            "part_load_derate": part_load_derate,
            "mechanical_efficiency": mechanical_efficiency,
            "carnot_ratio": carnot_ratio,
            "evaporator_approach_k": EVAPORATOR_APPROACH_K,
            "condenser_approach_k": CONDENSER_APPROACH_K,
        },
        input_units={
            "source_temperature_c": Unit.CELSIUS,
            "supply_temperature_c": Unit.CELSIUS,
            "return_temperature_c": Unit.CELSIUS,
            "part_load_derate": Unit.DIMENSIONLESS,
            "mechanical_efficiency": Unit.DIMENSIONLESS,
            "carnot_ratio": Unit.DIMENSIONLESS,
            "evaporator_approach_k": "K",
            "condenser_approach_k": "K",
        },
        formula=(
            "COP = Carnot(T_evap = T_source - 3K, T_cond = T_supply_mean + 5K) "
            "* carnot_ratio * condensing_penalty * part_load_derate "
            "* mechanical_efficiency"
        ),
        status=EpistemicStatus.ESTIMATE,
        sources=(SOURCE_COP_TEMPERATURE,),
        intermediate_values={
            "carnot_cop": carnot,
            "rated_cop": rated_cop,
            "mean_supply_temperature_c": mean_supply_c,
            "evaporating_temperature_c": evaporating_k - 273.15,
            "condensing_temperature_c": condensing_k - 273.15,
            "temperature_lift_k": condensing_k - evaporating_k,
            "condensing_penalty": condensing_penalty,
        },
        warnings=tuple(warnings),
        confidence=0.5,
    )
    return ctx.record(result) if ctx else result


def heat_pump_electricity_kw(
    thermal_kw: float,
    cop: float,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Parasitic electricity for a heat pump delivering ``thermal_kw``.

    ``P_electric = Q_thermal / COP``

    This term is what makes a low-temperature well with a high supply
    requirement commercially unattractive, and it is the reason heat pump
    electricity price is a first-class financial input.
    """
    require_positive(thermal_kw, "thermal_kw")
    require_positive(cop, "cop")

    electricity_kw = thermal_kw / cop

    result = CalcResult(
        function_name="heat_pump_electricity_kw",
        result=electricity_kw,
        result_unit=Unit.KILOWATT,
        inputs={"thermal_kw": thermal_kw, "cop": cop},
        input_units={"thermal_kw": "kW", "cop": Unit.DIMENSIONLESS},
        formula="P_electric = Q_thermal / COP",
        status=EpistemicStatus.DERIVED,
        intermediate_values={"net_electricity_kw": electricity_kw - thermal_kw},
        confidence=0.9,
    )
    return ctx.record(result) if ctx else result


def annual_heat_production(
    *,
    thermal_kw: float,
    operating_hours_per_year: float = 3500.0,
    capacity_factor: float = 0.6,
    network_heat_loss_kw: float = 0.0,
    network_loss_fraction: float = 0.0,
    heat_pump_cop: float | None = None,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Annual heat delivered to customers, in kWh.

    Chain, in order:

    1. ``Q_annual_available = thermal_kw * operating_hours * capacity_factor``
    2. subtract distribution losses, given either as a fraction or in kW;
    3. if a heat pump is fitted, the figure entering it is the wellhead thermal
       output, and the pump's electricity is costed in :mod:`financial`, not here.

    Args:
        thermal_kw: Wellhead thermal power.
        operating_hours_per_year: Typically 3000-4000 for space heating in the UK.
        capacity_factor: Fraction of those hours at full output. Heat demand is
            weather-driven and never flat.
        network_heat_loss_kw: Absolute distribution loss at full flow.
        network_loss_fraction: Fractional loss. Used only if the kW value is
            zero, to avoid double counting.
        heat_pump_cop: Recorded for traceability; does not change delivered heat,
            which is set by the load, not by the pump.

    Returns:
        CalcResult in kWh.
    """
    require_positive(thermal_kw, "thermal_kw")
    require_positive(operating_hours_per_year, "operating_hours_per_year")
    if not 0 < capacity_factor <= 1.0:
        raise CalculationError(
            f"capacity_factor must be in (0, 1], got {capacity_factor}"
        )

    available_kwh = thermal_kw * operating_hours_per_year * capacity_factor

    if network_heat_loss_kw > 0:
        loss_kwh = network_heat_loss_kw * operating_hours_per_year * capacity_factor
    else:
        loss_kwh = available_kwh * network_loss_fraction

    delivered_kwh = available_kwh - loss_kwh

    if delivered_kwh < 0:
        raise CalculationError(
            f"network losses ({loss_kwh:.0f} kWh) exceed available heat "
            f"({available_kwh:.0f} kWh); the network is longer or "
            "higher-loss than the well can support"
        )

    result = CalcResult(
        function_name="annual_heat_production",
        result=delivered_kwh,
        result_unit=Unit.KWH,
        inputs={
            "thermal_kw": thermal_kw,
            "operating_hours_per_year": operating_hours_per_year,
            "capacity_factor": capacity_factor,
            "network_heat_loss_kw": network_heat_loss_kw,
            "network_loss_fraction": network_loss_fraction,
            "heat_pump_cop": heat_pump_cop,
        },
        input_units={
            "thermal_kw": "kW",
            "operating_hours_per_year": Unit.HOURS,
            "capacity_factor": Unit.DIMENSIONLESS,
            "network_heat_loss_kw": "kW",
            "network_loss_fraction": Unit.DIMENSIONLESS,
            "heat_pump_cop": Unit.DIMENSIONLESS,
        },
        formula=(
            "E_delivered = Q_thermal * operating_hours * capacity_factor "
            "- E_loss, where E_loss = Q_loss * operating_hours * capacity_factor "
            "or E_available * loss_fraction"
        ),
        status=EpistemicStatus.ESTIMATE,
        intermediate_values={
            "available_kwh": available_kwh,
            "loss_kwh": loss_kwh,
            "loss_fraction": loss_kwh / available_kwh if available_kwh else 0.0,
        },
        warnings=(
            "Annual production assumes the well runs continuously at the stated "
            "capacity factor. Real heat demand is weather-dependent and the "
            "capacity factor is an assumption, not a measurement.",
        ),
        confidence=0.45,
    )
    return ctx.record(result) if ctx else result
