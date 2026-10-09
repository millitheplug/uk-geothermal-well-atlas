"""Analysis service: run the deterministic pipeline and the agents, persist both.

The division of responsibility is strict:

* :mod:`app.engineering` decides everything numeric. Nothing here overrides it.
* :mod:`app.agents` produces narrative and structured claims, which are stored
  alongside but never merged into the score fields.
* this module orchestrates, persists and assembles the API response.

A caller who wants no LLM at all gets byte-identical deterministic results; the
only difference is the presence of ``agent_outputs`` and the report.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.orchestrator import AgentOrchestrator, OrchestrationResult
from app.core.enums import (
    AnalysisStage,
    AnalysisStatus,
    EpistemicStatus,
    ValidationActionPriority,
)
from app.core.security import Caller
from app.engineering.pipeline import PIPELINE_VERSION, WellAssessment, WellInputs, assess_well
from app.engineering.scoring import WEIGHTS
from app.models.analysis import Analysis, Risk, Scenario, ValidationAction
from app.models.evidence import CalculationTrace, Claim
from app.models.well import Well
from app.services import query_service as qs

logger = logging.getLogger(__name__)

#: Stage labels for the progress UI, in execution order.
STAGE_LABELS: dict[AnalysisStage, str] = {
    AnalysisStage.DATA_VALIDATION: "Validating well record",
    AnalysisStage.GEOLOGY: "Interpreting geology",
    AnalysisStage.TEMPERATURE: "Assessing temperature",
    AnalysisStage.WELL_INTEGRITY: "Assessing well integrity",
    AnalysisStage.HEAT_DEMAND: "Matching heat demand",
    AnalysisStage.ENGINEERING: "Running engineering model",
    AnalysisStage.ECONOMICS: "Running financial model",
    AnalysisStage.RISK: "Building risk register",
    AnalysisStage.FINAL_ASSESSMENT: "Finalising assessment",
}


def build_well_inputs(
    db: Session,
    well: Well,
    *,
    demand_radius_m: float = 2000.0,
) -> tuple[WellInputs, dict[str, Any]]:
    """Assemble the pipeline input and the agent context from the database.

    Returns both because they come from the same reads: fetching a well's
    temperatures once and using them for the deterministic pipeline and the agent
    context avoids the two disagreeing.
    """
    integrity = qs.well_integrity(db, well.id)
    geology = qs.well_geology(db, well.id)
    temperatures = qs.well_temperatures(db, well.id)
    latest = qs.latest_temperature(db, well.id)
    demand = qs.match_demand_to_well(db, well, radius_m=demand_radius_m)

    source_reliabilities = [
        e.reliability for e in qs.well_evidence(db, well.id, limit=20)
    ]
    if not source_reliabilities:
        # No evidence rows yet: fall back to the adapter's declared reliability
        # rather than defaulting to zero, which would be unfair to a well whose
        # sources are simply not linked yet.
        from app.core.enums import EvidenceReliability  # noqa: PLC0415

        source_reliabilities = [
            EvidenceReliability.for_source_type(well.source)
        ]

    temp_values = [t.temperature_c for t in temperatures]
    temp_sources = sorted({t.source for t in temperatures if t.source})

    inputs = WellInputs(
        well_id=well.well_id,
        well_name=well.well_name,
        latitude=well.latitude,
        longitude=well.longitude,
        status=well.status,
        original_purpose=well.original_purpose,
        operator=well.operator,
        licence=well.licence,
        drilling_year=well.drilling_year,
        total_depth_m=well.total_depth_m,
        tvd_m=well.tvd_m,
        md_m=well.md_m,
        max_deviation_deg=well.max_deviation_deg,
        is_deviated=bool(well.is_deviated),
        formation=well.formation,
        basin=well.basin,
        has_casing_record=well.has_reusable_casing,
        has_wellhead=well.has_wellhead,
        completion_type=well.completion_type,
        temperature_c=well.temperature_c,
        temperature_depth_m=well.temperature_depth_m,
        temperature_status=well.temperature_status,
        temperature_confidence=well.temperature_confidence,
        temperature_variability_c=well.temperature_variability_c,
        temperature_method=latest.measurement_method if latest else None,
        temperature_measured_at=latest.measured_at if latest else None,
        temperature_measurements_c=temp_values,
        temperature_sources=temp_sources,
        has_flow_test=any(
            t.measurement_method in ("circulation_test", "flow_test") for t in temperatures
        ),
        integrity_status=integrity.status if integrity else None,
        casing_condition_score=integrity.casing_condition_score if integrity else None,
        wellhead_condition_score=integrity.wellhead_condition_score if integrity else None,
        access_score=integrity.access_score if integrity else None,
        abandonment_score=integrity.abandonment_score if integrity else None,
        water_salinity_ppt=geology.water_salinity_ppt if geology else None,
        water_ph=geology.water_ph if geology else None,
        scaling_tendency=geology.scaling_tendency if geology else None,
        corrosion_tendency=geology.corrosion_tendency if geology else None,
        geothermal_gradient_c_per_km=(
            geology.geothermal_gradient_c_per_km if geology else None
        ),
        annual_demand_kwh=demand.total_annual_demand_kwh or None,
        peak_demand_kw=demand.total_peak_demand_kw or None,
        number_of_buildings=demand.building_count or None,
        nearest_building_distance_m=demand.nearest_building_distance_m,
        demand_confidence=demand.confidence,
        required_supply_temperature_c=demand.average_supply_temperature_c,
        existing_network=False,
        source_reliabilities=source_reliabilities,
        has_logs=bool(well.logs),
        is_mock_data=well.source.startswith("mock_"),
    )

    context: dict[str, Any] = {
        "well": {
            "well_id": well.well_id,
            "well_name": well.well_name,
            "operator": well.operator,
            "licence": well.licence,
            "status": well.status,
            "status_raw": well.status_raw,
            "original_purpose": well.original_purpose,
            "drilling_year": well.drilling_year,
            "commissioned_date": str(well.commissioned_date) if well.commissioned_date else None,
            "plugged_and_abandoned_date": (
                str(well.plugged_and_abandoned_date) if well.plugged_and_abandoned_date else None
            ),
            "total_depth_m": well.total_depth_m,
            "tvd_m": well.tvd_m,
            "md_m": well.md_m,
            "max_deviation_deg": well.max_deviation_deg,
            "is_deviated": well.is_deviated,
            "formation": well.formation,
            "basin": well.basin,
            "latitude": well.latitude,
            "longitude": well.longitude,
            "county": well.county,
            "region": well.region,
            "data_completeness": well.data_completeness,
            "known_data_gaps": well.known_data_gaps,
        },
        "well_name": well.well_name,
        "latitude": well.latitude,
        "longitude": well.longitude,
        "county": well.county,
        "region": well.region,
        "well_status": well.status,
        "operator": well.operator,
        "licence": well.licence,
        "total_depth_m": well.total_depth_m,
        "formation": well.formation,
        "drilling_year": well.drilling_year,
        "has_casing_record": well.has_reusable_casing,
        "casing_string": well.casing_string,
        "completion_type": well.completion_type,
        "source_temperature_c": well.temperature_c,
        "temperature_depth_m": well.temperature_depth_m,
        "temperature_status": well.temperature_status,
        "temperature_confidence": well.temperature_confidence,
        "thermal_output_kw": None,
        "thermal_output_status": well.temperature_status,
        "nearest_building_distance_m": demand.nearest_building_distance_m,
        "temperatures": [
            {
                "temperature_c": t.temperature_c,
                "depth_m": t.depth_m,
                "measurement_method": t.measurement_method,
                "status": t.status,
                "confidence": t.confidence,
                "measured_at": str(t.measured_at) if t.measured_at else None,
                "source": t.source,
                "source_url": t.source_url,
                "is_final_stabilised": t.is_final_stabilised,
            }
            for t in temperatures
        ],
        "logs": [
            {
                "log_type": log.log_type,
                "logged_at": str(log.logged_at) if log.logged_at else None,
                "has_temperature_curve": log.has_temperature_curve,
                "source": log.source,
            }
            for log in well.logs
        ],
        "integrity": (
            {
                "status": integrity.status,
                "status_status": integrity.status_status,
                "confidence": integrity.confidence,
                "casing_condition_score": integrity.casing_condition_score,
                "requires_reequipment": integrity.requires_reequipment,
                "estimated_recompletion_capex_gbp": integrity.estimated_recompletion_capex_gbp,
                "estimated_recompletion_capex_status": integrity.estimated_recompletion_capex_status,
                "corrosion_evidence": integrity.corrosion_evidence,
                "scaling_evidence": integrity.scaling_evidence,
                "unknown_reasons": integrity.unknown_reasons,
            }
            if integrity
            else {}
        ),
        "geology": (
            {
                "geothermal_gradient_c_per_km": geology.geothermal_gradient_c_per_km,
                "permeability_md": geology.permeability_md,
                "net_thickness_m": geology.net_thickness_m,
                "reservoir_lithology": geology.reservoir_lithology,
                "water_salinity_ppt": geology.water_salinity_ppt,
                "water_ph": geology.water_ph,
                "scaling_tendency": geology.scaling_tendency,
                "corrosion_tendency": geology.corrosion_tendency,
                "chemistry_status": geology.chemistry_status,
            }
            if geology
            else {}
        ),
        "demand": {
            "radius_m": demand.radius_m,
            "building_count": demand.building_count,
            "total_annual_demand_kwh": demand.total_annual_demand_kwh,
            "total_peak_demand_kw": demand.total_peak_demand_kw,
            "nearest_building_distance_m": demand.nearest_building_distance_m,
            "dominant_building_type": demand.dominant_building_type,
            "average_required_supply_temperature_c": demand.average_supply_temperature_c,
            "weighted_centre_latitude": demand.weighted_latitude,
            "weighted_centre_longitude": demand.weighted_longitude,
        },
        "verified_facts": _verified_facts(db, well),
        "evidence": [
            {
                "id": str(e.id),
                "source": e.source,
                "source_url": e.source_url,
                "source_title": e.source_title,
                "document_type": e.document_type,
                "reliability": e.reliability,
                "status": e.status,
            }
            for e in qs.well_evidence(db, well.id, limit=25)
        ],
    }

    return inputs, context


def _verified_facts(db: Session, well: Well) -> list[dict[str, Any]]:
    """Facts an agent may assert without inventing a source.

    Only fields that can be traced to a stored source are included. An agent
    that wants to say something must point at one of these, which is what stops
    "the operator reported high flow rates" appearing from nowhere.
    """
    facts: list[dict[str, Any]] = []
    for evidence in qs.well_evidence(db, well.id, limit=25):
        facts.append(
            {
                "statement": evidence.excerpt
                or f"Document held: {evidence.source_title or evidence.source}",
                "fact_type": evidence.status,
                "source": evidence.source,
                "source_url": evidence.source_url,
                "field_name": evidence.document_type,
                "confidence": min(
                    evidence.reliability * evidence.quality, 1.0
                ),
            }
        )
    return facts


# ----------------------------------------------------------- running
def run_assessment(
    db: Session,
    well: Well,
    *,
    caller: Caller | None = None,
    overrides: dict[str, Any] | None = None,
    scenario_name: str | None = None,
    include_ai: bool = True,
    prefer_mock_llm: bool = False,
    tenant_id: uuid.UUID | None = None,
    persist: bool = True,
) -> tuple[Analysis | None, WellAssessment, OrchestrationResult | None]:
    """Run the full assessment for one well.

    Returns the analysis row (when persisted), the deterministic result, and the
    agent result. All three are returned rather than only the row so callers can
    use the result without a database round trip.
    """
    started = datetime.now(UTC)
    tid = tenant_id or (caller.tenant_id if caller else uuid.UUID(int=0))

    inputs, context = build_well_inputs(db, well)
    assessment = assess_well(inputs, overrides=overrides)

    context["thermal_output_kw"] = assessment.thermal_output_kw
    context["thermal_output_status"] = assessment.thermal_output_status
    context["network_length_m"] = assessment.network_length_m
    context["network_loss_fraction"] = assessment.network_loss_fraction
    context["network_heat_loss_kw"] = assessment.network_heat_loss_kw
    context["delivered_heat_kw"] = assessment.delivered_heat_kw
    context["annual_heat_kwh"] = assessment.annual_heat_kwh
    context["configuration_notes"] = [
        w for w in assessment.warnings if "Configuration" in w or "open loop" in w
    ]
    context["weights"] = dict(WEIGHTS)

    orchestration: OrchestrationResult | None = None
    if include_ai:
        try:
            orchestrator = AgentOrchestrator(prefer_mock=prefer_mock_llm)
            orchestration = orchestrator.run(assessment, context)
        except Exception as exc:  # noqa: BLE001 - AI must never lose the result
            logger.exception("agent orchestration failed")
            orchestration = OrchestrationResult(provider_name="failed")
            orchestration.violations.append(
                type("V", (), {"agent": "orchestrator", "rule": "orchestration_error",
                               "detail": str(exc), "action": "rejected"})()
            )

    analysis: Analysis | None = None
    if persist:
        analysis = _persist_assessment(
            db,
            well=well,
            assessment=assessment,
            orchestration=orchestration,
            tenant_id=tid,
            scenario_name=scenario_name,
            overrides=overrides,
            started=started,
        )

    return analysis, assessment, orchestration


def _persist_assessment(
    db: Session,
    *,
    well: Well,
    assessment: WellAssessment,
    orchestration: OrchestrationResult | None,
    tenant_id: uuid.UUID,
    scenario_name: str | None,
    overrides: dict[str, Any] | None,
    started: datetime,
) -> Analysis:
    """Write the analysis, its traces, risks, claims and validation actions."""
    risk = assessment.risk_assessment
    completed = datetime.now(UTC)

    analysis = Analysis(
        tenant_id=tenant_id,
        well_id=well.id,
        scenario_id=_resolve_scenario(db, well.id, scenario_name),
        status=AnalysisStatus.COMPLETE.value,
        engine_version=PIPELINE_VERSION,
        agent_model=(orchestration.model_name if orchestration else None),
        agent_provider=(orchestration.provider_name if orchestration else None),
        feasibility_score=assessment.feasibility_score,
        confidence_score=assessment.confidence_score,
        recommendation=assessment.recommendation,
        recommendation_rationale=" ".join(assessment.recommendation_rationale),
        score_components={
            "scores": assessment.component_scores,
            "weights": dict(WEIGHTS),
        },
        recommended_configuration=assessment.configuration,
        source_temperature_c=assessment.source_temperature_c,
        temperature_status=(
            EpistemicStatus.MEASURED.value
            if well.temperature_status == EpistemicStatus.MEASURED.value
            else well.temperature_status
        ),
        flow_rate_lps=assessment.parameters.get("values", {}).get("flow_rate_lps"),
        thermal_output_kw=assessment.thermal_output_kw,
        thermal_output_mw=(
            assessment.thermal_output_kw / 1000.0 if assessment.thermal_output_kw else None
        ),
        thermal_output_status=assessment.thermal_output_status,
        heat_pump_cop=assessment.heat_pump_cop,
        delivered_heat_kw=assessment.delivered_heat_kw,
        network_length_m=assessment.network_length_m,
        network_heat_loss_kw=assessment.network_heat_loss_kw,
        demand_matched_kw=assessment.demand_matched_kw,
        nearest_building_distance_m=None,
        annual_heat_production_kwh=assessment.annual_heat_kwh,
        capex_gbp=assessment.capex_gbp,
        opex_gbp_per_year=assessment.opex_gbp_per_year,
        lcoh_p_per_kwh=assessment.lcoh_p_per_kwh,
        npv_gbp=assessment.npv_gbp,
        irr_pct=assessment.irr_pct,
        payback_years=assessment.payback_years,
        break_even_heat_price_p_per_kwh=assessment.break_even_heat_price_p_per_kwh,
        risk_score=(risk.aggregate_score if risk else None),
        risk_count=(len(risk.risks) if risk else 0),
        critical_risk_count=(len(risk.critical_risks) if risk else 0),
        agent_outputs=(orchestration.to_dict() if orchestration else None),
        report_markdown=(orchestration.report_markdown if orchestration else None),
        executive_summary=(orchestration.executive_summary if orchestration else None),
        next_action=assessment.next_action,
        data_gaps={"gaps": assessment.data_gaps, "unknowns": assessment.unknowns},
        progress_stage=AnalysisStage.FINAL_ASSESSMENT.value,
        started_at=started,
        completed_at=completed,
        duration_seconds=(completed - started).total_seconds(),
    )
    db.add(analysis)
    db.flush()

    # Calculation traces: the audit trail that lets a stored financial model be
    # re-derived input by input without re-running the pipeline.
    for trace in assessment.calculation_trace.get("traces", []):
        db.add(
            CalculationTrace(
                well_id=well.id,
                analysis_id=analysis.id,
                function_name=trace["function_name"],
                inputs=trace.get("inputs", {}),
                formula=trace["formula"],
                result=trace.get("result"),
                result_unit=trace.get("result_unit"),
                intermediate_values=trace.get("intermediate_values", {}),
                warnings={
                    "warnings": list(trace.get("warnings", [])),
                    "status": trace.get("status"),
                    "confidence": trace.get("confidence"),
                },
                engine_version=trace.get("engine_version", PIPELINE_VERSION),
            )
        )

    if risk:
        for item in risk.risks:
            db.add(
                Risk(
                    well_id=well.id,
                    analysis_id=analysis.id,
                    category=item.category,
                    title=item.title,
                    description=item.description,
                    probability=item.likelihood,
                    probability_numeric=item.probability,
                    impact=item.impact,
                    impact_numeric=item.impact_value,
                    uncertainty=item.uncertainty,
                    risk_score=item.risk_score,
                    uncertainty_adjusted_score=item.uncertainty_adjusted_score,
                    severity=item.severity,
                    evidence={"items": list(item.evidence)},
                    mitigation=item.mitigation,
                    status="open",
                )
            )

    if orchestration:
        for claim in orchestration.claims:
            db.add(
                Claim(
                    well_id=well.id,
                    field_name=claim.field_name,
                    claim=claim.claim,
                    status=claim.status,
                    confidence=claim.confidence,
                    agent=claim.agent,
                    is_critical=claim.is_critical,
                )
            )

    for action in build_validation_actions(assessment):
        db.add(
            ValidationAction(
                well_id=well.id,
                analysis_id=analysis.id,
                action_type=action["action_type"],
                title=action["title"],
                description=action["description"],
                priority=action["priority"],
                rationale=action["rationale"],
                addresses_risk_ids=action.get("addresses_risk_ids", []),
                addresses_data_gaps=action.get("addresses_data_gaps", []),
                estimated_cost_gbp=action.get("estimated_cost_gbp"),
                estimated_duration_days=action.get("estimated_duration_days"),
                status="pending",
            )
        )

    # Refresh the well's cached scores so map colouring and ranking stay cheap.
    well.feasibility_score = assessment.feasibility_score
    well.confidence_score = assessment.confidence_score
    well.recommendation = assessment.recommendation
    well.data_confidence = assessment.confidence_band
    well.data_confidence_score = assessment.confidence_score
    well.data_completeness = _completeness(assessment)
    well.analysed_at = completed
    well.analysis_version = PIPELINE_VERSION

    db.flush()
    return analysis


def _completeness(assessment: WellAssessment) -> float:
    """Share of required fields that are populated, for the completeness axis."""
    from app.engineering.confidence import REQUIRED_FIELDS  # noqa: PLC0415

    populated = sum(
        1
        for gap in assessment.data_gaps
        if gap.split()[0].lower() in {f.lower() for f in REQUIRED_FIELDS}
    )
    # data_gaps counts gaps, so completeness is the inverse of the gap share.
    gap_penalty = min(1.0, populated / len(REQUIRED_FIELDS))
    return round(max(0.0, 1.0 - gap_penalty), 3)


def _resolve_scenario(
    db: Session, well_uuid: uuid.UUID, scenario_name: str | None
) -> uuid.UUID | None:
    if not scenario_name:
        return None
    return db.scalar(
        select(Scenario.id).where(
            Scenario.well_id == well_uuid, Scenario.name == scenario_name
        )
    )


# ------------------------------------------------- validation actions
def build_validation_actions(assessment: WellAssessment) -> list[dict[str, Any]]:
    """Turn the assessment's gaps into concrete, costed next steps.

    Ordered by information gained per pound rather than by risk severity. The
    cheapest action that retires the largest uncertainty comes first, because that
    is the action most likely to change the decision.
    """
    actions: list[dict[str, Any]] = []
    gaps = {g.lower() for g in assessment.data_gaps}

    if assessment.source_temperature_c is None or "temperature" in gaps:
        actions.append(
            {
                "action_type": "temperature_logging",
                "title": "Obtain the temperature record for this well",
                "description": (
                    "Search the historical well file for a static bottom-hole survey, "
                    "and if none exists and the well is accessible, run a temperature "
                    "log."
                ),
                "priority": ValidationActionPriority.CRITICAL.value,
                "rationale": (
                    "Every downstream figure - thermal output, COP, LCOH - scales with "
                    "the source temperature. Until it is known, nothing else can be "
                    "concluded, and the score is provisional."
                ),
                "addresses_data_gaps": ["temperature_c"],
                "estimated_cost_gbp": 18_000.0 if "integrity" not in gaps else 12_000.0,
                "estimated_duration_days": 30.0,
            }
        )

    if "well_integrity" in gaps or "casing" in gaps:
        actions.append(
            {
                "action_type": "casing_inspection",
                "title": "Recover the completion record and assess well integrity",
                "description": (
                    "Request the completion and casing record from the operator. Where "
                    "the well is accessible, run a wireline casing inspection."
                ),
                "priority": ValidationActionPriority.CRITICAL.value,
                "rationale": (
                    "Integrity carries a 20% score weight and cannot be established "
                    "from desk study. A records request may resolve it for no field cost."
                ),
                "addresses_data_gaps": ["well_integrity", "casing_string"],
                "estimated_cost_gbp": 45_000.0,
                "estimated_duration_days": 60.0,
            }
        )

    if "heat_demand" in gaps or "demand" in gaps:
        actions.append(
            {
                "action_type": "heat_demand_survey",
                "title": "Survey heat demand within 2 km",
                "description": (
                    "Identify candidate off-takers, record their existing heating "
                    "system and required supply temperature, and test willingness to "
                    "switch."
                ),
                "priority": ValidationActionPriority.HIGH.value,
                "rationale": (
                    "District schemes fail commercially on demand far more often than "
                    "on the resource. Demand carries a 15% score weight and the "
                    "current figure is modelled."
                ),
                "addresses_data_gaps": ["heat_demand"],
                "estimated_cost_gbp": 25_000.0,
                "estimated_duration_days": 90.0,
            }
        )

    if "water_chemistry" in gaps:
        actions.append(
            {
                "action_type": "geochemistry_sampling",
                "title": "Obtain formation water chemistry",
                "description": (
                    "Request the drilling report water analysis, or sample the "
                    "producing fluid if the well is live."
                ),
                "priority": ValidationActionPriority.HIGH.value,
                "rationale": (
                    "Scaling and corrosion are the most common causes of geothermal "
                    "plant underperformance, and both are predictable from water "
                    "chemistry."
                ),
                "addresses_data_gaps": ["water_chemistry"],
                "estimated_cost_gbp": 8_000.0,
                "estimated_duration_days": 30.0,
            }
        )

    if assessment.nearest_building_distance_m and assessment.nearest_building_distance_m > 1000:
        actions.append(
            {
                "action_type": "network_cost_study",
                "title": "Carry out a route survey and network cost study",
                "description": (
                    "Survey a realistic pipe alignment, identify easements and utility "
                    "crossings, and cost the connection."
                ),
                "priority": ValidationActionPriority.MEDIUM.value,
                "rationale": (
                    f"The nearest demand is "
                    f"{assessment.nearest_building_distance_m/1000:.1f} km away, so "
                    "pipe cost is a material and currently understated line item."
                ),
                "addresses_data_gaps": ["network_route"],
                "estimated_cost_gbp": 22_000.0,
                "estimated_duration_days": 120.0,
            }
        )

    if not actions:
        actions.append(
            {
                "action_type": "commercial_terms",
                "title": "Market-test the achievable heat price",
                "description": (
                    "Run a market sounding with anchor commercial and institutional "
                    "customers, and test willingness to pay against the modelled LCOH."
                ),
                "priority": ValidationActionPriority.HIGH.value,
                "rationale": (
                    "The engineering case is complete. The remaining uncertainty is "
                    "commercial, and it cannot be resolved by any amount of "
                    "engineering work."
                ),
                "addresses_data_gaps": ["heat_price"],
                "estimated_cost_gbp": 15_000.0,
                "estimated_duration_days": 90.0,
            }
        )

    return actions


# ------------------------------------------------------------- reading
def latest_analysis(db: Session, well_uuid: uuid.UUID) -> Analysis | None:
    return db.scalar(
        select(Analysis)
        .where(Analysis.well_id == well_uuid)
        .where(Analysis.status == AnalysisStatus.COMPLETE.value)
        .order_by(Analysis.created_at.desc())
        .limit(1)
    )


def progress_for(analysis: Analysis) -> dict[str, Any]:
    """Progress payload for the staged assessment UI."""
    from app.agents.orchestrator import STAGE_ORDER  # noqa: PLC0415

    completed = (
        [s for s in STAGE_ORDER] if analysis.status == AnalysisStatus.COMPLETE.value else []
    )
    return {
        "analysis_id": analysis.id,
        "status": AnalysisStatus(analysis.status),
        "stage": AnalysisStage(
            analysis.progress_stage or AnalysisStage.DATA_VALIDATION.value
        ),
        "completed_stages": completed,
        "stage_messages": {str(s): STAGE_LABELS[s] for s in STAGE_ORDER},
        "percent_complete": (
            100 if analysis.status == AnalysisStatus.COMPLETE.value else 10
        ),
        "error_message": analysis.error_message,
    }
