"""Capital cost model.

Structured as bottom-up unit rates multiplied by physical quantities, so a
reviewer can see what drives the number. Nothing here is a lookup table of
"geothermal costs per kW"; those exist, they hide the physics, and they are
wrong for repurposed wells because the well itself is already sunk cost.

The dominant insight for this platform is that most of the capital for a
repurposed well goes on the plant around it, not on drilling. That is why
``well_recompletion_cost`` is a separate line item and why a well that already
exists scores better on economics than an identical-temperature well that does
not.
"""

from __future__ import annotations

from app.core.enums import EpistemicStatus, GeothermalConfiguration
from app.engineering.base import (
    CalcResult,
    CalculationContext,
    CalculationError,
    SourceRef,
    Unit,
    require_positive,
)
from app.engineering.network import pipe_length_cost_factor

SOURCE_BEIS_COSTS = SourceRef(
    name="BEIS Energy Technology List cost assumptions and UK geothermal project reporting",
    url="https://www.gov.uk/government/collections/energy-technology-list",
    citation="Heat pump plant 550-900 GBP/kWth installed; district heating mains 300-700 GBP/m",
)

SOURCE_GEOTHERMAL_WELL = SourceRef(
    name="UK geothermal project capital cost reporting (Cornwall, Wealden, Cardiff)",
    url="https://www.bgs.ac.uk/our-industry/geothermal-energy/",
    citation="Exploration and reprocessing of existing wells: GBP 0.2-1.5m per well",
)

# ---- Unit rates (all overridable) ---------------------------------------
PLANT_CAPEX_GBP_PER_KWTH = {
    GeothermalConfiguration.CLOSED_LOOP: 620.0,
    GeothermalConfiguration.OPEN_LOOP: 540.0,
    GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP: 780.0,
    GeothermalConfiguration.OPEN_LOOP_PLUS_HEAT_PUMP: 700.0,
}
"""Installed cost of the geothermal plant, excluding the borehole and the network.
Closed loop plus heat pump carries the higher rate because it includes a machine;
open loop is cheaper because the pumping duty is lower."""

WELL_RECOMPLETION_BASE_GBP = 350_000.0
"""Baseline cost of making an existing borehole geothermal-capable: pulling
old completion, running new tubing, re-perforating, wellhead works."""

WELL_RECOMPLETION_PER_KWTH_GBP = 45.0
"""Depth- and scope-driven increment on top of the base cost. Covers conductor
condition, casing integrity remediation and any required fishing."""

WELL_REPERFORMANCE_PER_100M_GROSS_DEPTH_GBP = 85_000.0
"""Multiplied by gross depth / 100 m. Deeper wells need more steel and slower
rig time. For a 3,000 m well this contributes GBP 2.55m."""

NETWORK_CAPEX_GBP_PER_M = 420.0
"""Buried twin pipe, installed. Urban routes cost more; the multiplier is
applied inside :func:`network_heat_loss`'s sibling :func:`pipe_length_cost_factor`."""

PLANNING_AND_CONSENTS_GBP = 145_000.0
"""Planning submission, environmental assessment, abstraction and discharge
consents, and legal work. Roughly fixed, so it dominates small projects."""

SUBSTATION_CAPEX_GBP_PER_KWTH = 120.0
"""Customer-side heat exchanger and metering per kW of connected load."""

CONTINGENCY_FRACTION = 0.20
"""Class 3 estimate contingency (AACE International). Applied to all direct
costs. Expressed as a visible line item, not folded into unit rates."""


def capex(
    *,
    thermal_kw: float,
    configuration: GeothermalConfiguration = GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP,
    pipe_length_m: float,
    connected_load_kw: float | None = None,
    well_depth_m: float | None = None,
    well_recompletion_multiplier: float = 1.0,
    is_urban_route: bool = False,
    planning_and_consents_gbp: float = PLANNING_AND_CONSENTS_GBP,
    contingency_fraction: float = CONTINGENCY_FRACTION,
    plant_GBP_per_kWth: float | None = None,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Total installed capital cost.

    Composition, all items visible in the returned breakdown:

    ``plant``
        Geothermal plant at a configuration-specific rate per kWth.
    ``well_recompletion``
        Only if a depth is given. Zero for a new borehole, which is handled by
        the caller adding drilling cost separately.
    ``network``
        Buried pipe, scaled by the length cost factor.
    ``substation``
        Per kW of connected customer load.
    ``planning_and_consents``
        Fixed.
    ``contingency``
        Percentage of the sum of the above.

    Args:
        thermal_kw: Design thermal output, used for plant sizing.
        configuration: Selects the plant unit rate.
        pipe_length_m: Buried network length to the off-takers.
        connected_load_kw: Customer load served. Defaults to ``thermal_kw``.
        well_depth_m: If given, a well reprocessing cost is included.
        well_recompletion_multiplier: Scales well cost up for poor integrity or
            for a fully abandoned well requiring reperforation.
        is_urban_route: Applies an urban cost multiplier to the pipe.
        planning_and_consents_gbp: Override or set to 0 for a brownfield
            tie-in that already holds consent.
        contingency_fraction: Set to 0 to see the base estimate.
        plant_GBP_per_kWth: Override the plant rate outright.

    Returns:
        CalcResult in GBP, with a full ``breakdown`` in intermediate values.
    """
    require_positive(thermal_kw, "thermal_kw")
    require_positive(pipe_length_m, "pipe_length_m")
    if contingency_fraction < 0:
        raise CalculationError("contingency_fraction cannot be negative")

    load_kw = connected_load_kw if connected_load_kw is not None else thermal_kw
    if load_kw < 0:
        raise CalculationError("connected_load_kw cannot be negative")

    rate = plant_GBP_per_kWth or PLANT_CAPEX_GBP_PER_KWTH[configuration]
    plant_cost = thermal_kw * rate

    well_cost = 0.0
    if well_depth_m:
        require_positive(well_depth_m, "well_depth_m")
        well_cost = (
            WELL_RECOMPLETION_BASE_GBP
            + WELL_REPERFORMANCE_PER_100M_GROSS_DEPTH_GBP * (well_depth_m / 100.0)
        ) * well_recompletion_multiplier

    network_factor = pipe_length_cost_factor(pipe_length_m, is_urban=is_urban_route)
    network_cost = pipe_length_m * NETWORK_CAPEX_GBP_PER_M * network_factor

    substation_cost = load_kw * SUBSTATION_CAPEX_GBP_PER_KWTH

    direct = plant_cost + well_cost + network_cost + substation_cost + planning_and_consents_gbp
    contingency = direct * contingency_fraction
    total = direct + contingency

    result = CalcResult(
        function_name="capex",
        result=total,
        result_unit=Unit.GBP,
        inputs={
            "thermal_kw": thermal_kw,
            "configuration": str(configuration),
            "pipe_length_m": pipe_length_m,
            "connected_load_kw": load_kw,
            "well_depth_m": well_depth_m,
            "well_recompletion_multiplier": well_recompletion_multiplier,
            "is_urban_route": is_urban_route,
            "planning_and_consents_gbp": planning_and_consents_gbp,
            "contingency_fraction": contingency_fraction,
            "plant_GBP_per_kWth": rate,
        },
        input_units={
            "thermal_kw": "kW",
            "configuration": "-",
            "pipe_length_m": Unit.METRES,
            "connected_load_kw": "kW",
            "well_depth_m": Unit.METRES,
            "well_recompletion_multiplier": Unit.DIMENSIONLESS,
            "is_urban_route": "-",
            "planning_and_consents_gbp": Unit.GBP,
            "contingency_fraction": Unit.DIMENSIONLESS,
            "plant_GBP_per_kWth": "GBP/kWth",
        },
        formula=(
            "CAPEX = plant + well_recompletion + network + substation + consents "
            "+ contingency, where contingency = contingency_fraction * (sum of the above)"
        ),
        status=EpistemicStatus.ESTIMATE,
        sources=(SOURCE_BEIS_COSTS, SOURCE_GEOTHERMAL_WELL),
        intermediate_values={
            "plant_gbp": plant_cost,
            "well_recompletion_gbp": well_cost,
            "network_gbp": network_cost,
            "network_length_cost_factor": network_factor,
            "substation_gbp": substation_cost,
            "planning_and_consents_gbp": planning_and_consents_gbp,
            "direct_gbp": direct,
            "contingency_gbp": contingency,
        },
        warnings=(
            "Class 3 capital estimate. Actual costs depend on well condition, ground "
            "access, route permissions and procurement strategy, none of which are "
            "characterised at screening stage.",
        ),
        confidence=0.35,
    )
    return ctx.record(result) if ctx else result


def capex_breakdown(result: CalcResult) -> dict[str, float]:
    """Extract the breakdown dict from a :func:`capex` trace."""
    return {
        k: v
        for k, v in result.intermediate_values.items()
        if k.endswith("_gbp") or k == "planning_and_consents_gbp"
    }
