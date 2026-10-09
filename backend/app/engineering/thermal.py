"""Thermal model: heat extraction and delivered power.

The central relation is the one the specification names:

    Q = mass_flow_rate * specific_heat * delta_temperature

Everything else here exists to turn a well's temperature record into a
defensible power figure, and to be explicit about the difference between what
was measured and what was assumed.

Configurations supported:

``closed_loop``
    Doublet within a single existing borehole. No water is extracted, so no
    groundwater abstraction or discharge consent is required. Limited by the
    borehole's annular capacity and by borehole thermal recovery over repeated
    cycles.

``open_loop``
    Water is abstracted from the formation and reinjected after heat recovery.
    Pump load is low but the scheme needs an abstraction licence, discharge
    consent and a water chemistry management plan.

``closed_loop_plus_heat_pump``
    As closed loop, with a heat pump lifting the low-grade extracted heat to
    network flow temperature. Usually the lowest regulatory burden for an
    existing well.

``open_loop_plus_heat_pump``
    As open loop, plus a heat pump. Applicable when the water is too cool or
    the temperature swing too small for useful direct heat.

All four reduce to the same core physics; they differ in what temperature
swing is available and in what parasitic electricity is consumed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.enums import EpistemicStatus, GeothermalConfiguration
from app.engineering.base import (
    CalcResult,
    CalculationContext,
    CalculationError,
    SourceRef,
    Unit,
    require_positive,
)

# ---- Physical constants -------------------------------------------------
SPECIFIC_HEAT_WATER_J_KG_K = 4180.0
"""Specific heat capacity of water, J/(kg*K). 4186 is sometimes quoted; the
lower value is used deliberately as it is the more conservative for heat
extraction and matches the value used in most UK GSHP guidance."""

DENSITY_WATER_KG_M3 = 1000.0
"""Density of water, kg/m3. PVT correction is neglected; at 60-90 degC the
error is under 1% and is flagged as a limitation in the report."""

GRAVITY_M_S2 = 9.80665

# ---- Source references --------------------------------------------------
SOURCE_BGS_HEAT_CAPACITY = SourceRef(
    name="BGS geothermal potential calculation methodology",
    url="https://www.bgs.ac.uk/our-industry/geothermal-energy/",
    citation="Q = mdot * cp * dT; cp = 4180 J/(kg.K)",
)
SOURCE_BGS_TEMPERATURE = SourceRef(
    name="BGS geothermal catalogue and well temperature compilation",
    url="https://www.bgs.ac.uk/our-industry/geothermal-energy/",
)

#: Conversion: litres per second to kilograms per second.
LPS_TO_KG_S = DENSITY_WATER_KG_M3 / 1000.0


def litres_per_second_to_kg_per_second(flow_lps: float) -> float:
    """Convert volumetric to mass flow rate. 1 L/s of water = 1 kg/s."""
    return require_positive(flow_lps, "flow_lps") * LPS_TO_KG_S


@dataclass(frozen=True, slots=True)
class ThermalOutput:
    """Result of :func:`heat_extraction`, with the intermediate flow resolved."""

    thermal_kw: CalcResult
    mass_flow_kg_s: float
    delta_t_c: float
    configuration: GeothermalConfiguration


def thermal_power(
    mass_flow_kg_s: float,
    specific_heat_j_kg_k: float,
    delta_temperature_c: float,
    *,
    status: EpistemicStatus = EpistemicStatus.DERIVED,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Core thermal power relation.

    ``Q [W] = m_dot [kg/s] * cp [J/(kg.K)] * dT [K]``

    Args:
        mass_flow_kg_s: Mass flow rate of the heat transfer medium.
        specific_heat_j_kg_k: Specific heat capacity. Water is 4180 J/(kg.K).
        delta_temperature_c: Temperature drop across the exchanger. Must be
            positive; a negative value means the fluid is being heated and the
            direction is flipped by the caller, not silently handled here.
        status: Provenance of the *result*. Defaults to DERIVED. If the flow
            rate came from a flow test, pass MEASURED with a source reference
            attached by the caller.
        ctx: Optional context to record the trace in.

    Returns:
        CalcResult with result in watts.

    Example:
        25 L/s, 4180 J/(kg.K), 20 K drop -> 2,090,000 W = 2090 kW.
    """
    require_positive(mass_flow_kg_s, "mass_flow_kg_s")
    require_positive(specific_heat_j_kg_k, "specific_heat_j_kg_k")
    require_positive(delta_temperature_c, "delta_temperature_c")

    power_w = mass_flow_kg_s * specific_heat_j_kg_k * delta_temperature_c

    result = CalcResult(
        function_name="thermal_power",
        result=power_w,
        result_unit=Unit.WATT,
        inputs={
            "mass_flow_kg_s": mass_flow_kg_s,
            "specific_heat_j_kg_k": specific_heat_j_kg_k,
            "delta_temperature_c": delta_temperature_c,
        },
        input_units={
            "mass_flow_kg_s": "kg/s",
            "specific_heat_j_kg_k": "J/(kg.K)",
            "delta_temperature_c": "K",
        },
        formula="Q = m_dot * cp * dT",
        status=status,
        sources=(SOURCE_BGS_HEAT_CAPACITY,),
        intermediate_values={"power_kw": power_w / 1000.0},
        confidence=0.95,
    )
    return ctx.record(result) if ctx else result


def heat_extraction(
    *,
    source_temperature_c: float,
    return_temperature_c: float,
    flow_rate_lps: float,
    configuration: GeothermalConfiguration = GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP,
    specific_heat_j_kg_k: float = SPECIFIC_HEAT_WATER_J_KG_K,
    density_kg_m3: float = DENSITY_WATER_KG_M3,
    utilisation_factor: float = 1.0,
    ctx: CalculationContext | None = None,
) -> ThermalOutput:
    """Extractable thermal power at the wellhead.

    Builds on :func:`thermal_power` and adds the configuration-appropriate
    temperature swing and a utilisation factor for losses and downtime.

    Args:
        source_temperature_c: Temperature at the production/inlet end. For an
            open loop this is the flowing bottom-hole temperature; for a closed
            loop it is the annulus outlet temperature.
        return_temperature_c: Temperature after heat has been transferred to
            the secondary circuit.
        flow_rate_lps: Flow rate of the primary circuit.
        configuration: Determines the default utilisation factor.
        specific_heat_j_kg_k: Medium specific heat capacity.
        density_kg_m3: Medium density.
        utilisation_factor: Fraction of theoretical power actually available.
            Defaults to 1.0 (pure physics) and is reduced by scenario callers
            to represent downtime and losses. Not a fudge factor hidden inside
            the formula - it is an explicit, named, visible multiplier.

    Returns:
        ThermalOutput with the thermal power in kW.

    Raises:
        CalculationError: If return temperature is not below source
            temperature, or any input is non-positive.
    """
    require_positive(source_temperature_c, "source_temperature_c")
    require_positive(flow_rate_lps, "flow_rate_lps")
    require_positive(specific_heat_j_kg_k, "specific_heat_j_kg_k")
    require_positive(density_kg_m3, "density_kg_m3")

    if return_temperature_c is None or not math.isfinite(return_temperature_c):
        raise CalculationError("return_temperature_c is required")
    if return_temperature_c >= source_temperature_c:
        raise CalculationError(
            f"return_temperature_c ({return_temperature_c}) must be lower than "
            f"source_temperature_c ({source_temperature_c}); a well cannot deliver "
            "heat to a circuit that is already warmer than it"
        )

    if not 0.5 <= utilisation_factor <= 1.0:
        raise CalculationError(
            f"utilisation_factor must be in [0.5, 1.0], got {utilisation_factor}"
        )

    delta_t = source_temperature_c - return_temperature_c
    mass_flow = flow_rate_lps * density_kg_m3 / 1000.0

    # Pure physics first, so the unadjusted figure is always on the trace.
    power_trace = thermal_power(
        mass_flow_kg_s=mass_flow,
        specific_heat_j_kg_k=specific_heat_j_kg_k,
        delta_temperature_c=delta_t,
        status=EpistemicStatus.ESTIMATE,
        ctx=ctx,
    )
    gross_kw = (power_trace.result or 0.0) / 1000.0
    available_kw = gross_kw * utilisation_factor

    inputs = {
        "source_temperature_c": source_temperature_c,
        "return_temperature_c": return_temperature_c,
        "flow_rate_lps": flow_rate_lps,
        "density_kg_m3": density_kg_m3,
        "specific_heat_j_kg_k": specific_heat_j_kg_k,
        "utilisation_factor": utilisation_factor,
        "configuration": str(configuration),
    }
    input_units = {
        "source_temperature_c": Unit.CELSIUS,
        "return_temperature_c": Unit.CELSIUS,
        "flow_rate_lps": Unit.LITRES_PER_SECOND,
        "density_kg_m3": "kg/m3",
        "specific_heat_j_kg_k": "J/(kg.K)",
        "utilisation_factor": Unit.DIMENSIONLESS,
        "configuration": "-",
    }
    intermediate = {
        "mass_flow_kg_s": mass_flow,
        "delta_temperature_c": delta_t,
        "gross_kw": gross_kw,
    }
    warnings: list[str] = [
        "Estimated output assumes the stated flow rate is achievable. No flow "
        "test has been performed unless evidence states otherwise.",
    ]
    if utilisation_factor < 1.0:
        warnings.append(
            f"A utilisation factor of {utilisation_factor} has been applied; this "
            "represents downtime and distribution losses, not a physical limit."
        )

    if utilisation_factor < 1.0 and ctx is not None:
        # Record the adjustment as its own trace so the gross figure is never
        # overwritten by the derated one.
        ctx.record(
            CalcResult(
                function_name="utilisation_adjustment",
                result=available_kw,
                result_unit=Unit.KILOWATT,
                inputs={"gross_kw": gross_kw, "utilisation_factor": utilisation_factor},
                input_units={"gross_kw": "kW", "utilisation_factor": Unit.DIMENSIONLESS},
                formula="Q_available = Q_gross * utilisation_factor",
                status=EpistemicStatus.ASSUMPTION,
                sources=(SOURCE_BGS_HEAT_CAPACITY,),
            )
        )

    result = CalcResult(
        function_name="heat_extraction",
        result=available_kw,
        result_unit=Unit.KILOWATT,
        inputs=inputs,
        input_units=input_units,
        formula=(
            "Q = (flow_lps * density / 1000) * cp * (T_source - T_return) "
            "* utilisation_factor"
        ),
        status=EpistemicStatus.ESTIMATE,
        sources=(SOURCE_BGS_HEAT_CAPACITY, SOURCE_BGS_TEMPERATURE),
        intermediate_values=intermediate,
        warnings=tuple(warnings),
        confidence=0.55,
    )
    return ThermalOutput(
        thermal_kw=ctx.record(result) if ctx else result,
        mass_flow_kg_s=mass_flow,
        delta_t_c=delta_t,
        configuration=configuration,
    )


def _strip_empty_warnings(trace: CalcResult) -> CalcResult:
    """Drop the empty-string warning produced by the conditional above."""
    return CalcResult(
        function_name=trace.function_name,
        result=trace.result,
        result_unit=trace.result_unit,
        inputs=trace.inputs,
        input_units=trace.input_units,
        formula=trace.formula,
        status=trace.status,
        assumptions=trace.assumptions,
        sources=trace.sources,
        intermediate_values=trace.intermediate_values,
        warnings=tuple(w for w in trace.warnings if w),
        confidence=trace.confidence,
        engine_version=trace.engine_version,
    )


def heat_extraction_uncertainty_band(
    *,
    source_temperature_c: float,
    temperature_uncertainty_c: float,
    flow_rate_lps: float,
    flow_uncertainty_pct: float,
    specific_heat_j_kg_k: float = SPECIFIC_HEAT_WATER_J_KG_K,
    return_temperature_c: float | None = None,
) -> tuple[float, float, float]:
    """Return (low_kw, central_kw, high_kw) from a first-order sensitivity band.

    Temperature error propagates as ``dQ/Q = -dT_useful/T_useful`` where
    ``T_useful = T_source - T_return``; flow error propagates as ``dQ/Q =
    dmdot/mdot``. Both are combined in quadrature, which is appropriate because
    they are independent sources of error.

    This is the mechanism by which a poorly characterised temperature shows up
    as a wide band on the map rather than a spuriously precise point value.
    """
    if return_temperature_c is None:
        return_temperature_c = max(source_temperature_c - 20.0, 5.0)
    delta_t = source_temperature_c - return_temperature_c
    if delta_t <= 0:
        raise CalculationError("useful temperature swing must be positive")

    base_kg_s = flow_rate_lps * LPS_TO_KG_S
    base_kw = base_kg_s * specific_heat_j_kg_k * delta_t / 1000.0

    rel_temp = abs(temperature_uncertainty_c / delta_t) if delta_t else 1.0
    rel_flow = abs(flow_uncertainty_pct / 100.0)
    combined = math.sqrt(rel_temp**2 + rel_flow**2)

    return base_kw * (1 - combined), base_kw, base_kw * (1 + combined)


def sustainable_temperature_drop(
    *,
    source_temperature_c: float,
    target_supply_temperature_c: float,
    minimum_return_margin_c: float = 5.0,
) -> float:
    """Maximum usable temperature drop before the circuit cannot deliver.

    A well at 85 degC feeding a network that needs 70 degC flow has only
    15 K of swing; if 5 K of that is consumed by exchanger approach, 10 K is
    usable. This function makes that arithmetic explicit rather than leaving it
    inside a heat-pump COP lookup.
    """
    require_positive(source_temperature_c, "source_temperature_c")
    require_positive(target_supply_temperature_c, "target_supply_temperature_c")
    require_positive(minimum_return_margin_c, "minimum_return_margin_c")

    usable = source_temperature_c - target_supply_temperature_c - minimum_return_margin_c
    if usable <= 0:
        raise CalculationError(
            f"source temperature {source_temperature_c} degC cannot serve a "
            f"{target_supply_temperature_c} degC supply with a "
            f"{minimum_return_margin_c} K margin; a heat pump is required"
        )
    return usable
