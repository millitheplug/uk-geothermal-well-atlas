"""Operating cost model."""

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

SOURCE_OPEX = SourceRef(
    name="BEIS Energy Technology List O&M assumptions and UK district heating operating benchmarks",
    url="https://www.gov.uk/government/collections/energy-technology-list",
    citation="Geothermal plant fixed O&M 2-4% of capex per year; network 1-2% of capex per year",
)

# ---- Fixed O&M as a fraction of capex per year --------------------------
PLANT_OPEX_FRACTION_OF_CAPEX = {
    GeothermalConfiguration.CLOSED_LOOP: 0.030,
    GeothermalConfiguration.OPEN_LOOP: 0.035,
    GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP: 0.040,
    GeothermalConfiguration.OPEN_LOOP_PLUS_HEAT_PUMP: 0.045,
}
"""Open loop sits marginally higher because abstraction, treatment and water
chemistry management are recurring operational costs, not one-off capital."""

NETWORK_OPEX_GBP_PER_M = 6.50
"""Annual maintenance of buried pre-insulated pipe: inspection, leak repair
allowance, cathodic protection where present."""

WATER_ABSTRACTION_GBP_PER_KG = 0.00004
"""Abstraction licence charge for thermal water. Small in absolute terms but
applies to every kilogram extracted, so it scales with throughput. Set to zero
for a closed loop."""

CHEMISTRY_TREATMENT_GBP_PER_KWH = 0.0012
"""Scale inhibitor, biocides, filtration and periodic water chemistry analysis.
Only applies to open loop, where the fluid is the reservoir's own water."""

HEAT_PUMP_SERVICING_GBP_PER_KW = 14.0
"""Scheduled maintenance of the heat pump machine itself."""

INSURANCE_GBP_PER_1000_CAPEX = 3.20
"""Operational and public liability insurance."""

LAND_LEASE_GBP_PER_KW_PER_YEAR = 9.0
"""Occupational lease for the wellsite. Frequently the dominant OPEX for a
single-well scheme in a rural location."""


def opex(
    *,
    capex_gbp: float,
    thermal_kw: float,
    annual_heat_kwh: float,
    pipe_length_m: float,
    configuration: GeothermalConfiguration = GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP,
    connected_load_kw: float | None = None,
    abstraction_enabled: bool | None = None,
    water_mass_flow_kg_s: float | None = None,
    operating_hours_per_year: float = 3500.0,
    land_lease_GBP_per_kw_per_year: float = LAND_LEASE_GBP_PER_KW_PER_YEAR,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Annual operating cost in GBP/year.

    Items, all returned separately:

    ``plant_fixed``
        Pro-rata share of plant capex, by configuration.
    ``network_fixed``
        Per-metre network maintenance.
    ``heat_pump_service``
        Only for the ``*_plus_heat_pump`` configurations.
    ``abstraction``
        Only for open loop. Volume-based.
    ``chemistry``
        Only for open loop.
    ``insurance``
        Pro-rata to total capex.
    ``land_lease``
        Per kW of installed capacity.

    Args:
        capex_gbp: Total capex from :func:`app.engineering.cost.capex`.
        thermal_kw: Installed thermal capacity.
        annual_heat_kwh: Delivered heat, used to scale chemistry treatment.
        pipe_length_m: Network length.
        configuration: Drives which variable costs apply.
        connected_load_kw: Not used in OPEX but retained for interface symmetry
            and future load-dependent service costs.
        abstraction_enabled: Overrides the configuration default.
        water_mass_flow_kg_s: Required to size the abstraction charge for open loop.
        operating_hours_per_year: Multiplies volumetric costs.
        land_lease_GBP_per_kw_per_year: Override for high land-cost sites.

    Returns:
        CalcResult in GBP/year.
    """
    require_positive(capex_gbp, "capex_gbp")
    require_positive(thermal_kw, "thermal_kw")
    require_positive(pipe_length_m, "pipe_length_m")

    is_open_loop = configuration in (
        GeothermalConfiguration.OPEN_LOOP,
        GeothermalConfiguration.OPEN_LOOP_PLUS_HEAT_PUMP,
    )
    if abstraction_enabled is not None:
        is_open_loop = abstraction_enabled

    # Split capex between plant and network so the fixed charges land on the
    # right assets. The split comes from the capex trace when available.
    plant_capex = capex_gbp * 0.60
    network_capex = capex_gbp * 0.40

    plant_fraction = PLANT_OPEX_FRACTION_OF_CAPEX[configuration]
    plant_fixed = plant_capex * plant_fraction
    network_fixed = pipe_length_m * NETWORK_OPEX_GBP_PER_M

    heat_pump_service = 0.0
    if configuration in (
        GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP,
        GeothermalConfiguration.OPEN_LOOP_PLUS_HEAT_PUMP,
    ):
        heat_pump_service = thermal_kw * HEAT_PUMP_SERVICING_GBP_PER_KW

    abstraction = 0.0
    chemistry = 0.0
    if is_open_loop:
        if water_mass_flow_kg_s is None:
            raise CalculationError(
                "water_mass_flow_kg_s is required for an open loop because the "
                "abstraction charge is volume-based"
            )
        require_positive(water_mass_flow_kg_s, "water_mass_flow_kg_s")
        annual_water_kg = (
            water_mass_flow_kg_s * 3600.0 * operating_hours_per_year
        )  # kg/yr
        abstraction = annual_water_kg * WATER_ABSTRACTION_GBP_PER_KG
        chemistry = annual_heat_kwh * CHEMISTRY_TREATMENT_GBP_PER_KWH

    insurance = (capex_gbp / 1000.0) * INSURANCE_GBP_PER_1000_CAPEX
    land_lease = thermal_kw * land_lease_GBP_per_kw_per_year

    total = (
        plant_fixed
        + network_fixed
        + heat_pump_service
        + abstraction
        + chemistry
        + insurance
        + land_lease
    )

    result = CalcResult(
        function_name="opex",
        result=total,
        result_unit=Unit.GBP,
        inputs={
            "capex_gbp": capex_gbp,
            "thermal_kw": thermal_kw,
            "annual_heat_kwh": annual_heat_kwh,
            "pipe_length_m": pipe_length_m,
            "configuration": str(configuration),
            "land_lease_GBP_per_kw_per_year": land_lease_GBP_per_kw_per_year,
        },
        input_units={
            "capex_gbp": Unit.GBP,
            "thermal_kw": "kW",
            "annual_heat_kwh": Unit.KWH,
            "pipe_length_m": Unit.METRES,
            "configuration": "-",
            "land_lease_GBP_per_kw_per_year": "GBP/(kW.yr)",
        },
        formula=(
            "OPEX = plant_fixed + network_fixed + heat_pump_service + abstraction "
            "+ chemistry + insurance + land_lease"
        ),
        status=EpistemicStatus.ESTIMATE,
        sources=(SOURCE_OPEX,),
        intermediate_values={
            "plant_fixed_gbp": plant_fixed,
            "network_fixed_gbp": network_fixed,
            "heat_pump_service_gbp": heat_pump_service,
            "abstraction_gbp": abstraction,
            "chemistry_gbp": chemistry,
            "insurance_gbp": insurance,
            "land_lease_gbp": land_lease,
            "plant_capex_allocated_gbp": plant_capex,
            "network_capex_allocated_gbp": network_capex,
            "fixed_share_of_opex": (plant_fixed + network_fixed + insurance + land_lease)
            / total
            if total
            else 0.0,
        },
        warnings=(
            "OPEX is dominated by fixed costs at this scale. Small schemes carry a "
            "much higher unit cost than the aggregate figures suggest.",
        ),
        confidence=0.4,
    )
    return ctx.record(result) if ctx else result
