"""Deterministic pipeline: well data in, scored assessment out.

This is the orchestration layer that chains the pure functions in this package
into one reproducible run. It contains no LLM calls and no I/O. Its output is
a single :class:`WellAssessment` that the agent layer may then explain, but
never alter.

Order of operations matters and is fixed:

1. validate the well's data and identify gaps;
2. establish the source temperature, or record that it is unknown;
3. size the thermal configuration;
4. size the network from real matched demand;
5. cost it;
6. score it;
7. register the risks the scoring surfaced;
8. recommend a next action.

Run the same well twice with the same parameters and you get the same numbers,
to the last decimal place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.enums import (
    DataConfidence,
    EpistemicStatus,
    GeothermalConfiguration,
    WellStatus,
)
from app.engineering import confidence as confidence_engine
from app.engineering import cost as cost_engine
from app.engineering import financial as fin_engine
from app.engineering import heatpump, scoring, thermal
from app.engineering import network as network_engine
from app.engineering import parameters as param_engine
from app.engineering import risk as risk_engine
from app.engineering.base import CalculationContext, CalculationError
from app.engineering.opex import opex

PIPELINE_VERSION = "0.1.0"


@dataclass
class WellInputs:
    """Everything the pipeline needs about one well.

    Assembled by the service layer from the database. Plain data, no ORM
    objects, so the pipeline can be unit tested without a database.
    """

    well_id: str
    well_name: str
    latitude: float
    longitude: float
    status: str = WellStatus.UNKNOWN.value
    original_purpose: str | None = None
    operator: str | None = None
    licence: str | None = None
    drilling_year: int | None = None
    total_depth_m: float | None = None
    tvd_m: float | None = None
    md_m: float | None = None
    max_deviation_deg: float | None = None
    is_deviated: bool = False
    formation: str | None = None
    basin: str | None = None
    has_casing_record: bool = False
    has_wellhead: bool | None = None
    completion_type: str | None = None

    # Temperature
    temperature_c: float | None = None
    temperature_depth_m: float | None = None
    temperature_status: str = EpistemicStatus.UNKNOWN.value
    temperature_confidence: str = DataConfidence.UNKNOWN.value
    temperature_variability_c: float | None = None
    temperature_method: str | None = None
    temperature_measured_at: Any = None
    temperature_measurements_c: list[float] = field(default_factory=list)
    temperature_sources: list[str] = field(default_factory=list)
    has_flow_test: bool = False

    # Integrity
    integrity_status: str | None = None
    casing_condition_score: float | None = None
    wellhead_condition_score: float | None = None
    access_score: float | None = None
    abandonment_score: float | None = None

    # Geology and chemistry
    water_salinity_ppt: float | None = None
    water_ph: float | None = None
    scaling_tendency: str | None = None
    corrosion_tendency: str | None = None
    geothermal_gradient_c_per_km: float | None = None

    # Matched demand
    annual_demand_kwh: float | None = None
    peak_demand_kw: float | None = None
    number_of_buildings: int | None = None
    nearest_building_distance_m: float | None = None
    demand_confidence: str = DataConfidence.UNKNOWN.value
    required_supply_temperature_c: float | None = None
    existing_network: bool = False
    network_reinforcement_required: bool | None = None

    # Regulatory flags
    requires_abstraction_licence: bool = False
    requires_discharge_consent: bool = False
    requires_planning_permission: bool | None = None
    is_spa: bool = False
    is_conservation_area: bool = False
    is_mining_subsidence_area: bool = False
    is_heritage_asset: bool = False

    # Data provenance
    source_reliabilities: list[float] = field(default_factory=list)
    has_logs: bool = False
    is_mock_data: bool = False

    def present_fields(self) -> dict[str, Any]:
        """Field map for the completeness axis."""
        return {
            "temperature_c": self.temperature_c,
            "total_depth_m": self.total_depth_m,
            "tvd_m": self.tvd_m,
            "status": self.status,
            "original_purpose": self.original_purpose,
            "drilling_year": self.drilling_year,
            "operator": self.operator,
            "licence": self.licence,
            "formation": self.formation,
            "casing_string": "present" if self.has_casing_record else None,
            "bottomhole_pressure_bar": None,
            "md_m": self.md_m,
            "max_deviation_deg": self.max_deviation_deg,
            "completion_type": self.completion_type,
            "latitude_offset_checked": "checked",
            "pressure_status": EpistemicStatus.UNKNOWN.value,
        }


@dataclass
class WellAssessment:
    """Complete deterministic output for one well and one scenario."""

    well_id: str
    configuration: str
    source_temperature_c: float | None
    thermal_output_kw: float | None
    thermal_output_low_kw: float | None
    thermal_output_high_kw: float | None
    thermal_output_status: str
    heat_pump_cop: float | None
    heat_pump_electricity_kw: float | None
    network_length_m: float | None
    network_heat_loss_kw: float | None
    network_loss_fraction: float | None
    delivered_heat_kw: float | None
    annual_heat_kwh: float | None
    demand_matched_kw: float | None
    #: Distance to the nearest matched off-taker. Carried on the result rather
    #: than only on WellInputs because every downstream surface - scoring, the
    #: report, the API - needs it and re-deriving it would be error-prone.
    nearest_building_distance_m: float | None
    annual_demand_kwh: float | None
    peak_demand_kw: float | None
    number_of_buildings: int | None
    demand_confidence: str
    capex_gbp: float | None
    opex_gbp_per_year: float | None
    lcoh_p_per_kwh: float | None
    npv_gbp: float | None
    irr_pct: float | None
    payback_years: float | None
    break_even_heat_price_p_per_kwh: float | None
    feasibility_score: float
    confidence_score: float
    confidence_band: str
    recommendation: str
    recommendation_rationale: list[str] = field(default_factory=list)
    component_scores: dict[str, Any] = field(default_factory=dict)
    risk_assessment: risk_engine.RiskAssessment | None = None
    confidence_assessment: confidence_engine.ConfidenceAssessment | None = None
    data_gaps: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_action: str = ""
    calculation_trace: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    pipeline_version: str = PIPELINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "well_id": self.well_id,
            "pipeline_version": self.pipeline_version,
            "configuration": self.configuration,
            "source_temperature_c": self.source_temperature_c,
            "thermal": {
                "output_kw": self.thermal_output_kw,
                "output_low_kw": self.thermal_output_low_kw,
                "output_high_kw": self.thermal_output_high_kw,
                "status": self.thermal_output_status,
                "heat_pump_cop": self.heat_pump_cop,
                "heat_pump_electricity_kw": self.heat_pump_electricity_kw,
                "delivered_heat_kw": self.delivered_heat_kw,
            },
            "network": {
                "length_m": self.network_length_m,
                "heat_loss_kw": self.network_heat_loss_kw,
                "loss_fraction": self.network_loss_fraction,
                "demand_matched_kw": self.demand_matched_kw,
            },
            "annual_heat_kwh": self.annual_heat_kwh,
            "economics": {
                "capex_gbp": self.capex_gbp,
                "opex_gbp_per_year": self.opex_gbp_per_year,
                "lcoh_p_per_kwh": self.lcoh_p_per_kwh,
                "npv_gbp": self.npv_gbp,
                "irr_pct": self.irr_pct,
                "payback_years": self.payback_years,
                "break_even_heat_price_p_per_kwh": self.break_even_heat_price_p_per_kwh,
            },
            "scores": {
                "feasibility": round(self.feasibility_score, 2),
                "confidence": round(self.confidence_score, 4),
                "confidence_band": self.confidence_band,
                "components": self.component_scores,
            },
            "recommendation": {
                "level": self.recommendation,
                "rationale": self.recommendation_rationale,
                "next_action": self.next_action,
            },
            "risk": self.risk_assessment.to_dict() if self.risk_assessment else None,
            "confidence_detail": (
                self.confidence_assessment.to_dict() if self.confidence_assessment else None
            ),
            "data_gaps": self.data_gaps,
            "unknowns": self.unknowns,
            "warnings": self.warnings,
            "parameters": self.parameters,
            "calculation_trace": self.calculation_trace,
        }


def assess_well(
    inputs: WellInputs,
    *,
    configuration: str | None = None,
    overrides: dict[str, Any] | None = None,
    ctx: CalculationContext | None = None,
) -> WellAssessment:
    """Run the full deterministic pipeline for one well.

    Args:
        inputs: Well data.
        configuration: Override the automatic configuration choice.
        overrides: User parameter overrides, applied over the defaults.
        ctx: Optional context; a fresh one is created if not supplied.

    Returns:
        WellAssessment. Never raises for missing data: a gap produces a lower
        score and a recorded gap, not an exception. A well with no temperature
        is scored, reported as ``thermal_output_status = UNKNOWN`` and
        recommended as needing measurement.
    """
    context = ctx or CalculationContext()
    warnings: list[str] = []
    data_gaps: list[str] = []
    unknowns: list[str] = []

    params = param_engine.ParameterSet.build(overrides=overrides)

    # ---- 1. Data validation -------------------------------------------
    if inputs.temperature_c is None:
        data_gaps.append(
            "No temperature measurement exists for this well. Thermal potential "
            "cannot be assessed."
        )
        unknowns.append("source_temperature_c")
    if inputs.integrity_status is None:
        data_gaps.append("Well integrity has not been assessed.")
    if inputs.annual_demand_kwh is None:
        data_gaps.append("No heat demand has been matched to this well's location.")
    if not inputs.has_casing_record:
        data_gaps.append("No casing string is documented.")
    if inputs.total_depth_m is None:
        data_gaps.append("Total depth is not recorded.")
    for gap in params.unknowns():
        if gap not in unknowns:
            unknowns.append(gap)

    # ---- 2. Configuration choice --------------------------------------
    config = configuration or _choose_configuration(inputs, warnings)

    # ---- 3. Temperature and thermal model ------------------------------
    source_temp = inputs.temperature_c
    heat_pump_cop: float | None = None
    pump_electricity_kw: float | None = None
    thermal_kw: float | None = None
    thermal_low: float | None = None
    thermal_high: float | None = None
    thermal_status = EpistemicStatus.UNKNOWN.value
    delivered_kw: float | None = None
    usable_delta_t = 0.0

    target_supply = (
        inputs.required_supply_temperature_c
        or params["target_supply_temperature_c"]
    )

    if source_temp is not None:
        # Two different temperature limits apply, and conflating them badly
        # understates a cold well.
        #
        # For *direct* heat, the swing is set by the network supply temperature.
        # For a well fed through a *heat pump*, the primary circuit can be
        # cooled to the evaporator inlet limit, which is far below the supply
        # temperature, so much more swing is available.
        try:
            direct_delta_t = thermal.sustainable_temperature_drop(
                source_temperature_c=source_temp,
                target_supply_temperature_c=target_supply,
                minimum_return_margin_c=5.0,
            )
            needs_heat_pump = False
        except CalculationError as exc:
            direct_delta_t = 0.0
            needs_heat_pump = True
            warnings.append(str(exc))

        if needs_heat_pump and config in (
            GeothermalConfiguration.CLOSED_LOOP.value,
            GeothermalConfiguration.OPEN_LOOP.value,
        ):
            config = (
                GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP.value
                if not inputs.requires_abstraction_licence
                else GeothermalConfiguration.OPEN_LOOP_PLUS_HEAT_PUMP.value
            )
            warnings.append(
                f"Configuration changed to {config} because the source cannot "
                "serve the target supply temperature directly."
            )

        # The primary circuit swing is bounded by what the heat side can accept.
        if config.endswith("plus_heat_pump"):
            usable_delta_t = max(
                source_temp - heatpump.MINIMUM_EVAPORATOR_INLET_C, 1.0
            )
        else:
            usable_delta_t = max(direct_delta_t, 1.0)

        return_temp = source_temp - usable_delta_t

        extraction = thermal.heat_extraction(
            source_temperature_c=source_temp,
            return_temperature_c=return_temp,
            flow_rate_lps=params["flow_rate_lps"],
            configuration=config,
            utilisation_factor=params["utilisation_factor"],
            ctx=context,
        )
        thermal_kw = extraction.thermal_kw.result
        delivered_kw = thermal_kw
        thermal_status = (
            EpistemicStatus.MEASURED.value
            if inputs.has_flow_test and inputs.temperature_status == EpistemicStatus.MEASURED.value
            else EpistemicStatus.ESTIMATE.value
        )

        if not inputs.has_flow_test:
            warnings.append(
                "Thermal output is an ESTIMATE. No flow test has been performed on "
                "this well, so the achievable flow rate is assumed."
            )

        temp_uncertainty = {
            DataConfidence.HIGH.value: 3.0,
            DataConfidence.MEDIUM.value: 8.0,
            DataConfidence.LOW.value: 15.0,
            DataConfidence.VERY_LOW.value: 25.0,
            DataConfidence.UNKNOWN.value: 30.0,
        }.get(inputs.temperature_confidence.lower(), 20.0)

        thermal_low, _, thermal_high = thermal.heat_extraction_uncertainty_band(
            source_temperature_c=source_temp,
            temperature_uncertainty_c=temp_uncertainty,
            flow_rate_lps=params["flow_rate_lps"],
            flow_uncertainty_pct=40.0,
            return_temperature_c=return_temp,
        )

        if config.endswith("plus_heat_pump"):
            try:
                cop_trace = heatpump.heat_pump_performance(
                    source_temperature_c=source_temp,
                    supply_temperature_c=target_supply,
                    ctx=context,
                )
                heat_pump_cop = cop_trace.result
                elec_trace = heatpump.heat_pump_electricity_kw(
                    thermal_kw=thermal_kw or 0.0,
                    cop=heat_pump_cop or 1.0,
                    ctx=context,
                )
                pump_electricity_kw = elec_trace.result
            except heatpump.HeatPumpNotRequired as exc:
                # The well is hot enough to serve the circuit directly. Downgrade
                # the configuration rather than reporting a meaningless COP.
                config = (
                    GeothermalConfiguration.CLOSED_LOOP.value
                    if not inputs.requires_abstraction_licence
                    else GeothermalConfiguration.OPEN_LOOP.value
                )
                heat_pump_cop = None
                pump_electricity_kw = None
                warnings.append(f"Heat pump removed from the design. {exc}")
    else:
        temp_uncertainty = 0.0

    # ---- 4. Network ----------------------------------------------------
    network_length = params.get("network_length_m") or inputs.nearest_building_distance_m
    network_loss_kw: float | None = None
    loss_fraction: float | None = None
    annual_kwh: float | None = None

    if network_length is None:
        network_length = 1500.0
        warnings.append(
            f"No matched demand geometry available; a nominal {network_length:.0f} m "
            "route has been used. This is an assumption, not a surveyed route."
        )

    if thermal_kw is not None and network_length:
        network_mass_flow = params["flow_rate_lps"]
        # The loss must be evaluated over the temperature swing the well can
        # actually deliver. Using a nominal 20 K network differential for a well
        # that can only swing 1 K overstates delivered energy, and against a
        # small well makes the losses exceed the source entirely.
        deliverable_swing = max(usable_delta_t, 5.0)
        supply_for_loss = target_supply
        return_for_loss = max(target_supply - deliverable_swing, 10.0)
        if return_for_loss >= supply_for_loss:
            return_for_loss = supply_for_loss - 5.0

        loss_trace = network_engine.network_heat_loss(
            flow_rate_kg_s=network_mass_flow,
            supply_temperature_c=supply_for_loss,
            return_temperature_c=return_for_loss,
            pipe_length_m=network_length,
            ground_temperature_c=params["ground_temperature_c"],
            linear_loss_w_per_m_per_k=params["linear_loss_w_per_m_per_k"],
            ctx=context,
        )
        network_loss_kw = loss_trace.result
        loss_fraction = loss_trace.intermediate_values.get("loss_fraction")
        if loss_fraction and loss_fraction > 0.5:
            warnings.append(
                f"Distribution losses of {loss_fraction:.0%} consume most of the "
                "output. The route length is the dominant cost driver here."
            )
            if inputs.nearest_building_distance_m is None:
                data_gaps.append(
                    "No surveyed route length is available; network losses are "
                    "dominated by an assumed distance."
                )

        try:
            annual_trace = heatpump.annual_heat_production(
                thermal_kw=thermal_kw,
                operating_hours_per_year=params["operating_hours_per_year"],
                capacity_factor=params["capacity_factor"],
                network_heat_loss_kw=network_loss_kw,
                heat_pump_cop=heat_pump_cop,
                ctx=context,
            )
        except CalculationError as exc:
            # The route is too long or too lossy to be worth connecting. This is a
            # legitimate screening outcome, not a crash: record it, mark the
            # scheme undeliverable and let the scoring reflect that.
            annual_kwh = 0.0
            data_gaps.append(
                "Distribution losses exceed the heat the well can produce over the "
                "assumed route, so no annual output can be credited."
            )
            warnings.append(str(exc))
            annual_trace = None

        if annual_trace is not None:
            annual_kwh = annual_trace.result
        delivered_kw = max(thermal_kw - (network_loss_kw or 0.0), 0.0)

        if annual_kwh == 0.0:
            # Nothing survives distribution, so there is no output to match.
            demand_matched = None
        elif inputs.annual_demand_kwh is not None:
            demand_matched = min(
                delivered_kw or 0.0, inputs.peak_demand_kw or inputs.annual_demand_kwh / 3500.0
            )
        else:
            demand_matched = None
    else:
        demand_matched = None

    # ---- 5. Costs and financials ---------------------------------------
    capex_gbp: float | None = None
    opex_gbp: float | None = None
    lcoh: float | None = None
    npv_value: float | None = None
    irr_pct: float | None = None
    payback_years: float | None = None
    break_even_price: float | None = None

    if thermal_kw is not None and annual_kwh and annual_kwh > 0:
        integrity_multiplier = _well_cost_multiplier(inputs)
        capex_trace = cost_engine.capex(
            thermal_kw=thermal_kw,
            configuration=config,
            pipe_length_m=network_length,
            connected_load_kw=demand_matched,
            well_depth_m=inputs.total_depth_m,
            well_recompletion_multiplier=integrity_multiplier,
            ctx=context,
        )
        capex_gbp = capex_trace.result

        opex_result = opex(
            capex_gbp=capex_gbp,
            thermal_kw=thermal_kw,
            annual_heat_kwh=annual_kwh,
            pipe_length_m=network_length,
            configuration=config,
            connected_load_kw=demand_matched,
            water_mass_flow_kg_s=(
                params["flow_rate_lps"] if config.startswith("open") else None
            ),
            operating_hours_per_year=params["operating_hours_per_year"],
            ctx=context,
        )
        opex_gbp = opex_result.result

        lcoh_trace = fin_engine.lcoh(
            capex_gbp=capex_gbp,
            annual_opex_gbp=opex_gbp,
            annual_heat_kwh=annual_kwh,
            discount_rate=params["discount_rate"],
            project_lifetime_years=int(params["project_lifetime_years"]),
            ctx=context,
        )
        lcoh = lcoh_trace.result

        heat_price = params["heat_price_p_per_kwh"]
        elec_price = params["electricity_price_p_per_kwh"]

        revenue = annual_kwh * heat_price / 100.0
        years = int(params["project_lifetime_years"])
        cash_flows = [revenue - opex_gbp] * years

        npv_trace = fin_engine.npv(
            initial_capex_gbp=capex_gbp,
            cash_flows=cash_flows,
            discount_rate=params["discount_rate"],
            ctx=context,
        )
        npv_value = npv_trace.result

        irr_trace = fin_engine.irr(
            initial_capex_gbp=capex_gbp, cash_flows=cash_flows, ctx=context
        )
        irr_pct = irr_trace.result * 100.0 if irr_trace.result is not None else None
        if irr_trace.result is None:
            warnings.extend(f"IRR: {w}" for w in irr_trace.warnings)

        payback_trace = fin_engine.payback(
            initial_capex_gbp=capex_gbp,
            annual_cash_flow_gbp=cash_flows[0] if cash_flows else 0.0,
            discount_rate=params["discount_rate"],
            ctx=context,
        )
        payback_years = payback_trace.result
        if payback_trace.result is None:
            warnings.extend(f"Payback: {w}" for w in payback_trace.warnings)

        be_trace = fin_engine.break_even(
            capex_gbp=capex_gbp,
            annual_opex_gbp=opex_gbp,
            annual_heat_kwh=annual_kwh,
            discount_rate=params["discount_rate"],
            project_lifetime_years=years,
            electricity_price_p_per_kwh=elec_price,
            heat_pump_cop=heat_pump_cop,
            ctx=context,
        )
        break_even_price = be_trace.result

    # ---- 6. Scores -----------------------------------------------------
    thermal_component, thermal_notes = scoring.thermal_score(
        source_temperature_c=source_temp,
        target_supply_temperature_c=target_supply,
        usable_delta_t_c=(
            source_temp - max(target_supply + 5.0, 0.0) if source_temp else None
        ),
        flow_rate_lps=params["flow_rate_lps"],
        thermal_output_kw=thermal_kw,
        temperature_confidence=inputs.temperature_confidence,
        is_measured=inputs.temperature_status == EpistemicStatus.MEASURED.value,
    )
    integrity_component, integrity_notes = scoring.integrity_score(
        integrity_status=inputs.integrity_status,
        casing_condition_score=inputs.casing_condition_score,
        abandonment_score=inputs.abandonment_score,
        access_score=inputs.access_score,
        wellhead_condition_score=inputs.wellhead_condition_score,
        has_casing_record=inputs.has_casing_record,
    )
    demand_component, demand_notes = scoring.demand_score(
        annual_demand_kwh=inputs.annual_demand_kwh,
        peak_demand_kw=inputs.peak_demand_kw,
        thermal_output_kw=thermal_kw,
        number_of_buildings=inputs.number_of_buildings,
        demand_confidence=inputs.demand_confidence,
    )
    network_component, network_notes = scoring.network_score(
        distance_m=inputs.nearest_building_distance_m,
        pipe_length_m=network_length,
        network_heat_loss_fraction=loss_fraction,
        existing_network=inputs.existing_network,
        reinforcement_required=inputs.network_reinforcement_required,
    )
    geometry_component, geometry_notes = scoring.geometry_score(
        total_depth_m=inputs.total_depth_m,
        tvd_m=inputs.tvd_m,
        md_m=inputs.md_m,
        max_deviation_deg=inputs.max_deviation_deg,
        is_deviated=inputs.is_deviated,
    )
    economics_component, economics_notes = scoring.economics_score(
        lcoh_p_per_kwh=lcoh,
        heat_price_p_per_kwh=params["heat_price_p_per_kwh"],
        npv_gbp=npv_value,
        irr_pct=irr_pct,
        payback_years=payback_years,
    )
    regulatory_component, regulatory_notes = scoring.regulatory_score(
        requires_abstraction_licence=inputs.requires_abstraction_licence,
        requires_discharge_consent=inputs.requires_discharge_consent,
        requires_planning_permission=inputs.requires_planning_permission,
        is_spa=inputs.is_spa,
        is_conservation_area=inputs.is_conservation_area,
        is_mining_subsidence_area=inputs.is_mining_subsidence_area,
    )

    confidence_assessment = confidence_engine.assess_confidence(
        source_reliabilities=inputs.source_reliabilities,
        present_fields=inputs.present_fields(),
        integrity_assessed=inputs.integrity_status is not None,
        demand_data_present=inputs.annual_demand_kwh is not None,
        logs_available=inputs.has_logs,
        temperature_status=inputs.temperature_status,
        measurement_method=inputs.temperature_method,
        is_final_stabilised=True if source_temp is not None else None,
        temperature_variability_c=inputs.temperature_variability_c,
        measured_depth_m=inputs.temperature_depth_m,
        total_depth_m=inputs.total_depth_m,
        has_flow_test=inputs.has_flow_test,
        measurement_date=inputs.temperature_measured_at,
        well_status=inputs.status,
        temperature_values_c=inputs.temperature_measurements_c or None,
        sources=inputs.temperature_sources or None,
        unknowns=unknowns,
    )

    feasibility = scoring.composite_score(
        thermal=thermal_component,
        integrity=integrity_component,
        demand=demand_component,
        economics=economics_component,
        network=network_component,
        geometry=geometry_component,
        regulatory=regulatory_component,
        data_confidence=confidence_assessment.score,
    )

    component_scores = {
        scoring.ScoreComponent.THERMAL.value: thermal_component,
        scoring.ScoreComponent.INTEGRITY.value: integrity_component,
        scoring.ScoreComponent.DEMAND.value: demand_component,
        scoring.ScoreComponent.ECONOMICS.value: economics_component,
        scoring.ScoreComponent.NETWORK.value: network_component,
        scoring.ScoreComponent.GEOMETRY.value: geometry_component,
        scoring.ScoreComponent.REGULATORY.value: regulatory_component,
        scoring.ScoreComponent.DATA_CONFIDENCE.value: confidence_assessment.score,
    }

    # ---- 7. Risk register ----------------------------------------------
    risk_assessment = risk_engine.RiskBuilder(
        well_status=inputs.status,
        integrity_status=inputs.integrity_status,
        temperature_status=inputs.temperature_status,
        temperature_confidence=inputs.temperature_confidence,
        temperature_variability_c=inputs.temperature_variability_c,
        drilling_year=inputs.drilling_year,
        total_depth_m=inputs.total_depth_m,
        has_casing_record=inputs.has_casing_record,
        water_salinity_ppt=inputs.water_salinity_ppt,
        water_ph=inputs.water_ph,
        scaling_tendency=inputs.scaling_tendency,
        corrosion_tendency=inputs.corrosion_tendency,
        distance_to_demand_m=inputs.nearest_building_distance_m,
        annual_demand_kwh=inputs.annual_demand_kwh,
        demand_confidence=inputs.demand_confidence,
        capex_gbp=capex_gbp,
        lcoh_p_per_kwh=lcoh,
        heat_price_p_per_kwh=params["heat_price_p_per_kwh"],
        requires_abstraction_licence=inputs.requires_abstraction_licence,
        is_spa=inputs.is_spa,
        is_conservation_area=inputs.is_conservation_area,
        is_mining_subsidence_area=inputs.is_mining_subsidence_area,
        is_heritage_asset=inputs.is_heritage_asset,
        number_of_off_takers=inputs.number_of_buildings,
        is_mock_data=inputs.is_mock_data,
    ).build()

    recommendation, rationale = scoring.recommend(
        feasibility_score=feasibility,
        confidence_score=confidence_assessment.score,
        critical_risk_count=len(risk_assessment.critical_risks),
        data_gap_count=len(data_gaps),
        lcoh_p_per_kwh=lcoh,
        heat_price_p_per_kwh=params["heat_price_p_per_kwh"],
    )

    next_action = _next_action(
        inputs=inputs,
        data_gaps=data_gaps,
        risk_assessment=risk_assessment,
        feasibility=feasibility,
        confidence=confidence_assessment.score,
    )

    # Configuration decisions and their reasoning are accumulated in the local
    # `warnings` list; calculation-level warnings arrive via the context. Both
    # must reach the output, otherwise the reason a well was routed to a
    # particular configuration - and any hot-swap that happened - is lost.
    all_warnings = list(context.warnings)
    for local in warnings:
        if local not in all_warnings:
            all_warnings.insert(0, local)

    for note in (
        thermal_notes + integrity_notes + demand_notes + network_notes
        + geometry_notes + economics_notes + regulatory_notes
    ):
        all_warnings.append(note)

    return WellAssessment(
        well_id=inputs.well_id,
        configuration=config,
        source_temperature_c=source_temp,
        thermal_output_kw=thermal_kw,
        thermal_output_low_kw=thermal_low,
        thermal_output_high_kw=thermal_high,
        thermal_output_status=thermal_status,
        heat_pump_cop=heat_pump_cop,
        heat_pump_electricity_kw=pump_electricity_kw,
        network_length_m=network_length,
        network_heat_loss_kw=network_loss_kw,
        network_loss_fraction=loss_fraction,
        delivered_heat_kw=delivered_kw,
        annual_heat_kwh=annual_kwh,
        demand_matched_kw=demand_matched,
        nearest_building_distance_m=inputs.nearest_building_distance_m,
        annual_demand_kwh=inputs.annual_demand_kwh,
        peak_demand_kw=inputs.peak_demand_kw,
        number_of_buildings=inputs.number_of_buildings,
        demand_confidence=inputs.demand_confidence,
        capex_gbp=capex_gbp,
        opex_gbp_per_year=opex_gbp,
        lcoh_p_per_kwh=lcoh,
        npv_gbp=npv_value,
        irr_pct=irr_pct,
        payback_years=payback_years,
        break_even_heat_price_p_per_kwh=break_even_price,
        feasibility_score=feasibility,
        confidence_score=confidence_assessment.score,
        confidence_band=confidence_assessment.band,
        recommendation=recommendation.value,
        recommendation_rationale=list(rationale),
        component_scores=component_scores,
        risk_assessment=risk_assessment,
        confidence_assessment=confidence_assessment,
        data_gaps=data_gaps,
        unknowns=unknowns,
        warnings=all_warnings,
        next_action=next_action,
        calculation_trace=context.to_dict(),
        parameters=params.to_dict(),
        pipeline_version=PIPELINE_VERSION,
    )


def _choose_configuration(inputs: WellInputs, warnings: list[str]) -> str:
    """Pick a configuration from the well's status.

    Preference order, and the reasoning is recorded rather than assumed:

    * An accessible, non-abandoned well with good integrity is a candidate for
      a closed loop plus heat pump, which avoids abstraction licensing entirely.
    * An abandoned well with no access still favours a closed loop, since an
      open loop would require bringing the well back into production and dealing
      with the discharge question.
    * An open loop is only preferred where the well is live and water chemistry
      is known to be benign, because that is when its lower pumping cost is
      actually available.
    """
    abandoned = inputs.status in (
        WellStatus.PLUGGED_ABANDONED.value,
        WellStatus.ABANDONED.value,
        WellStatus.SUSPENDED.value,
    )
    chemistry_known = inputs.water_salinity_ppt is not None or inputs.water_ph is not None
    chemistry_benign = (
        inputs.scaling_tendency is not None
        and inputs.scaling_tendency.lower() in ("low", "none", "minimal")
    )

    if abandoned:
        warnings.append(
            "Well is abandoned or suspended. A closed loop plus heat pump is "
            "recommended because it needs no abstraction or discharge consent."
        )
        return GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP.value

    if not chemistry_known:
        warnings.append(
            "No water chemistry is available. A closed loop is preferred over an "
            "open loop because open-loop performance depends on chemistry that is "
            "not characterised."
        )
        return GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP.value

    if chemistry_benign:
        warnings.append(
            "Water chemistry is recorded as benign and the well is live, so an open "
            "loop plus heat pump is viable and has lower pumping demand."
        )
        return GeothermalConfiguration.OPEN_LOOP_PLUS_HEAT_PUMP.value

    return GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP.value


def _well_cost_multiplier(inputs: WellInputs) -> float:
    """Scale well reprocessing cost by how much work the wellbore needs."""
    multiplier = 1.0
    if inputs.status in (WellStatus.PLUGGED_ABANDONED.value, WellStatus.ABANDONED.value):
        multiplier += 0.6
    if inputs.integrity_status in ("poor_unknown", "abandoned_no_access"):
        multiplier += 0.4
    if inputs.max_deviation_deg and inputs.max_deviation_deg > 45:
        multiplier += 0.25
    if not inputs.has_casing_record:
        multiplier += 0.15
    return multiplier


def _next_action(
    *,
    inputs: WellInputs,
    data_gaps: list[str],
    risk_assessment: risk_engine.RiskAssessment,
    feasibility: float,
    confidence: float,
) -> str:
    """The single most valuable next step.

    Ordered by expected information value per pound, not by risk severity. The
    cheapest action that would resolve the largest uncertainty comes first: for
    a well with no temperature, that is always a temperature log, whatever else
    is also wrong with it.
    """
    if inputs.temperature_c is None:
        return (
            "Obtain the well's temperature record. This is a data-room request and "
            "a static survey search, not new fieldwork, and it gates every other "
            "judgement about this well."
        )

    if inputs.integrity_status is None:
        return (
            "Commission a well integrity assessment: recover the completion record "
            "and, where accessible, run a casing inspection. Integrity carries a "
            "higher score weight than economics, and an abandoned well cannot be "
            "assessed from desk study alone."
        )

    if confidence < 0.35:
        return (
            "Resolve the outstanding data gaps before spending on feasibility "
            "engineering. At this confidence level the score is not stable enough "
            "to justify project development spend."
        )

    if inputs.annual_demand_kwh is None:
        return (
            "Run a heat demand survey for the area within 2 km. Demand adequacy "
            "carries a third of the remaining economic weight and the current "
            "figure is an assumption."
        )

    if feasibility >= 55:
        return (
            "Progress to due diligence: site visit, route survey, and market "
            "sounding on achievable heat price. The case is strong enough to "
            "justify that spend."
        )

    if feasibility >= 35:
        return (
            "Complete a targeted desktop study on the two weakest score components "
            "before deciding whether to progress."
        )

    return (
        "Retain on the watch list. Do not commit further budget unless the "
        "temperature or integrity record improves materially."
    )
