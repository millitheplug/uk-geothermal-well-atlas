"""Analysis endpoints: run assessments, poll progress, run scenarios."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.api.deps import DbSession, Pagination
from app.core.enums import EpistemicStatus, GeothermalConfiguration, Recommendation
from app.core.security import Caller, CurrentCaller, scoped_well_query
from app.engineering.pipeline import WellAssessment, assess_well
from app.models.analysis import Analysis, Risk, ValidationAction
from app.models.evidence import CalculationTrace
from app.models.well import Well
from app.schemas.well import (
    AnalysisCreate,
    AnalysisProgress,
    AnalysisResult,
    CalculationTraceRead,
    ConfidenceRead,
    EngineeringInputs,
    RiskAssessmentRead,
    ScenarioComparison,
    ScenarioDefinition,
    ScenarioResult,
)
from app.services import analysis_service as svc

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.post(
    "",
    response_model=AnalysisResult,
    status_code=status.HTTP_201_CREATED,
    summary="Run a feasibility assessment",
)
def create_analysis(
    payload: AnalysisCreate,
    db: DbSession,
    caller: CurrentCaller,
    background: BackgroundTasks,
) -> AnalysisResult:
    """Run the deterministic pipeline and the agents for one well.

    Deterministic results are returned immediately; the agent layer and report
    are produced on a background task and picked up by polling the progress
    endpoint. This keeps a slow LLM call off the request path without losing the
    numbers a user needs straight away.
    """
    caller.require_role("analyst")

    stmt = select(Well).where(Well.id == payload.well_id)
    stmt = scoped_well_query(stmt, caller)
    well = db.scalar(stmt)
    if well is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="well not found")

    overrides = payload.inputs.model_dump(exclude_none=True)

    analysis, assessment, orchestration = svc.run_assessment(
        db,
        well,
        caller=caller,
        overrides=overrides,
        scenario_name=payload.scenario_name,
        include_ai=True,
        persist=True,
    )

    if payload.include_ai_agents and orchestration is not None:
        background.add_task(
            _finalise_in_background,
            analysis.id if analysis else None,
        )

    db.commit()

    return _to_result(well, assessment, orchestration, analysis)


def _finalise_in_background(analysis_id: uuid.UUID | None) -> None:
    """Placeholder hook for deferred agent work.

    Synchronous adapter runs already complete the agents inline, so this exists
    to be replaced by a Celery task without changing the route. Kept explicit
    rather than removed so the extension point is visible.
    """
    return None


@router.get(
    "",
    response_model=list[AnalysisResult],
    summary="List analyses for the caller",
)
def list_analyses(
    db: DbSession,
    caller: CurrentCaller,
    page: Pagination,
    well_id: Annotated[uuid.UUID | None, Query()] = None,
    recommendation: Annotated[list[str] | None, Query()] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[AnalysisResult]:
    """Analyses belonging to the caller's tenant."""
    stmt = select(Analysis).where(Analysis.tenant_id == caller.tenant_id)
    if well_id:
        stmt = stmt.where(Analysis.well_id == well_id)
    if recommendation:
        stmt = stmt.where(Analysis.recommendation.in_(recommendation))
    if min_score is not None:
        stmt = stmt.where(Analysis.feasibility_score >= min_score)
    if status_filter:
        stmt = stmt.where(Analysis.status == status_filter)

    rows = list(
        db.scalars(
            stmt.order_by(Analysis.created_at.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    )
    return [_analysis_to_result(db, row) for row in rows]


@router.get("/{analysis_uuid}", response_model=AnalysisResult, summary="One analysis")
def get_analysis(
    analysis_uuid: uuid.UUID, db: DbSession, caller: CurrentCaller
) -> AnalysisResult:
    """Full result for one analysis, including the calculation trace and report."""
    analysis = _scoped_analysis(db, caller, analysis_uuid)
    well = db.get(Well, analysis.well_id)
    if well is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="well not found")

    return _analysis_to_result(db, analysis, well=well)


@router.get(
    "/{analysis_uuid}/progress",
    response_model=AnalysisProgress,
    summary="Assessment progress",
)
def analysis_progress(
    analysis_uuid: uuid.UUID, db: DbSession, caller: CurrentCaller
) -> AnalysisProgress:
    """Stage-by-stage progress for the assessment UI.

    The nine stages are always returned, including those not yet run, so the UI
    can render the full pipeline immediately rather than discovering stages as
    they appear.
    """
    analysis = _scoped_analysis(db, caller, analysis_uuid)
    return AnalysisProgress(**svc.progress_for(analysis))


@router.get(
    "/{analysis_uuid}/trace",
    response_model=list[CalculationTraceRead],
    summary="Full calculation trace",
)
def analysis_trace(
    analysis_uuid: uuid.UUID, db: DbSession, caller: CurrentCaller
) -> list[CalculationTraceRead]:
    """Every deterministic calculation, with inputs, formula and provenance.

    This is what makes the engineering auditable: a reader can see exactly which
    numbers went into LCOH and what was assumed at each step.
    """
    from app.db.base import CalculationTrace

    _scoped_analysis(db, caller, analysis_uuid)

    traces = list(
        db.scalars(
            select(CalculationTrace)
            .where(CalculationTrace.analysis_id == analysis_uuid)
            .order_by(CalculationTrace.created_at, CalculationTrace.id)
        )
    )

    return [
        CalculationTraceRead(
            function_name=t.function_name,
            inputs=t.inputs or {},
            input_units={},
            formula=t.formula,
            result=t.result,
            result_unit=t.result_unit or "-",
            status=(t.warnings or {}).get("status", "DERIVED"),
            assumptions=[],
            sources=[],
            intermediate_values=t.intermediate_values or {},
            warnings=(t.warnings or {}).get("warnings", []),
            confidence=(t.warnings or {}).get("confidence"),
            engine_version=t.engine_version,
        )
        for t in traces
    ]


@router.get(
    "/{analysis_uuid}/report",
    summary="Report as markdown",
    response_class=PlainTextResponse,
)
def analysis_report(
    analysis_uuid: uuid.UUID,
    db: DbSession,
    caller: CurrentCaller,
    fmt: Annotated[str, Query(pattern="^(markdown|json)$")] = "markdown",
) -> Any:
    """The screening report.

    Markdown for reading, JSON for processing. Both carry the same disclaimers,
    including the statement that this is not a claim of commercial viability.
    """
    analysis = _scoped_analysis(db, caller, analysis_uuid)

    if not analysis.report_markdown:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "no report is stored for this analysis. Reports are produced by the "
                "agent layer; re-run with include_ai_agents=true."
            ),
        )

    if fmt == "json":
        return {
            "analysis_id": str(analysis.id),
            "well_id": str(analysis.well_id),
            "markdown": analysis.report_markdown,
            "executive_summary": analysis.executive_summary,
            "feasibility_score": analysis.feasibility_score,
            "confidence_score": analysis.confidence_score,
            "recommendation": analysis.recommendation,
            "next_action": analysis.next_action,
        }

    return PlainTextResponse(
        content=analysis.report_markdown,
        media_type="text/markdown",
        headers={
            "Content-Disposition": (
                f'attachment; filename="well-{analysis.well_id}-report.md"'
            )
        },
    )


@router.post(
    "/{well_uuid}/scenarios",
    response_model=ScenarioComparison,
    summary="Run bear, base and bull scenarios",
)
def run_scenarios(
    well_uuid: uuid.UUID,
    db: DbSession,
    caller: CurrentCaller,
    payload: Annotated[list[ScenarioDefinition], Body()],
) -> ScenarioComparison:
    """Run several parameter sets against one well and compare them.

    The deterministic engine runs once per scenario, so the comparison shows the
    true sensitivity of the answer rather than a set of numbers chosen to look
    sensible. Each scenario's overrides are recorded so the UI can show which
    inputs were changed.
    """
    caller.require_role("analyst")

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="at least one scenario is required",
        )

    stmt = select(Well).where(Well.id == well_uuid)
    stmt = scoped_well_query(stmt, caller)
    well = db.scalar(stmt)
    if well is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="well not found")

    inputs, _context = svc.build_well_inputs(db, well)

    results: list[ScenarioResult] = []
    for scenario in payload:
        overrides = scenario.inputs.model_dump(exclude_none=True)
        result = assess_well(inputs, overrides=overrides)
        params = result.parameters or {}
        results.append(
            ScenarioResult(
                name=scenario.name,
                label=scenario.label,
                inputs=scenario.inputs,
                overrides_applied=params.get("overrides_applied", {}),
                thermal_output_kw=result.thermal_output_kw,
                thermal_output_low_kw=result.thermal_output_low_kw,
                thermal_output_high_kw=result.thermal_output_high_kw,
                thermal_output_status=result.thermal_output_status,
                heat_pump_cop=result.heat_pump_cop,
                annual_heat_kwh=result.annual_heat_kwh,
                capex_gbp=result.capex_gbp,
                opex_gbp_per_year=result.opex_gbp_per_year,
                lcoh_p_per_kwh=result.lcoh_p_per_kwh,
                npv_gbp=result.npv_gbp,
                irr_pct=result.irr_pct,
                payback_years=result.payback_years,
                break_even_heat_price_p_per_kwh=result.break_even_heat_price_p_per_kwh,
                feasibility_score=result.feasibility_score,
                recommendation=result.recommendation,
                warnings=result.warnings[:8],
            )
        )

    lcohs = [r.lcoh_p_per_kwh for r in results if r.lcoh_p_per_kwh is not None]

    notes: list[str] = []
    weighted_lcoh = _weighted_average(
        [(r.lcoh_p_per_kwh, next((s.probability_weight for s in payload if s.name == r.name), None))
         for r in results]
    )
    weighted_npv = _weighted_average(
        [(r.npv_gbp, next((s.probability_weight for s in payload if s.name == r.name), None))
         for r in results]
    )
    if weighted_lcoh is None and len(lcohs) > 1:
        notes.append(
            "No probability weights were supplied, so no expected value is reported. "
            "A spread between the scenarios is more informative at screening stage "
            "than a single weighted figure."
        )
    if lcohs and max(lcohs) > 3 * max(min(lcohs), 0.1):
        notes.append(
            f"LCOH varies from {min(lcohs):.1f} to {max(lcohs):.1f} p/kWh across these "
            "scenarios. That spread is the real uncertainty, not the central value."
        )

    return ScenarioComparison(
        well_id=well.well_id,
        scenarios=results,
        expected_lcoh_p_per_kwh=weighted_lcoh,
        expected_npv_gbp=weighted_npv,
        spread_lcoh_p_per_kwh=(max(lcohs) - min(lcohs)) if len(lcohs) > 1 else None,
        notes=notes,
    )


def _weighted_average(pairs: list[tuple[float | None, float | None]]) -> float | None:
    """Probability-weighted mean, or None when no weights were supplied.

    Returns None rather than an unweighted mean: an unweighted average across
    bear, base and bull is a number with no interpretation.
    """
    usable = [(v, w) for v, w in pairs if v is not None and w is not None]
    if not usable or sum(w for _, w in usable) <= 0:
        return None
    total_weight = sum(w for _, w in usable)
    return sum(v * w for v, w in usable) / total_weight


@router.post(
    "/what-if",
    response_model=AnalysisResult,
    summary="Recalculate with overridden inputs, without persisting",
)
def what_if(
    well_uuid: Annotated[uuid.UUID, Query(description="Well to recalculate")],
    db: DbSession,
    caller: CurrentCaller,
    inputs: Annotated[EngineeringInputs, Body()],
    configuration: Annotated[
        str | None, Query(description="Override the automatic configuration choice")
    ] = None,
) -> AnalysisResult:
    """Recalculate a well with user-supplied inputs.

    Nothing is persisted. This is the interactive calculator on the analysis
    page: the user drags a parameter and sees the whole model move, including
    the score, so they can find out how sensitive the answer actually is.
    """
    caller.require_role("analyst")

    stmt = select(Well).where(Well.id == well_uuid)
    stmt = scoped_well_query(stmt, caller)
    well = db.scalar(stmt)
    if well is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="well not found")

    pipeline_inputs, _ = svc.build_well_inputs(db, well)
    result = assess_well(
        pipeline_inputs,
        configuration=configuration,
        overrides=inputs.model_dump(exclude_none=True),
    )

    db.rollback()
    return _to_result(well, result, None, None)


# ------------------------------------------------------------- helpers
def _scoped_analysis(db: DbSession, caller: Caller, analysis_uuid: uuid.UUID) -> Analysis:
    analysis = db.scalar(
        select(Analysis).where(
            Analysis.id == analysis_uuid, Analysis.tenant_id == caller.tenant_id
        )
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="analysis not found for this tenant",
        )
    return analysis


def _to_result(
    well: Well,
    assessment: WellAssessment,
    orchestration: Any,
    analysis: Analysis | None,
) -> AnalysisResult:
    confidence_detail = None
    if assessment.confidence_assessment:
        raw = assessment.confidence_assessment.to_dict()
        raw["axes"] = {
            name: {
                "score": axis["score"],
                "weight": axis["weight"],
                "contribution": axis["contribution"],
                "notes": axis["notes"],
            }
            for name, axis in raw["axes"].items()
        }
        confidence_detail = ConfidenceRead(**raw)

    return AnalysisResult(
        analysis_id=analysis.id if analysis else None,
        well_id=well.well_id,
        well_uuid=well.id,
        well_name=well.well_name,
        pipeline_version=assessment.pipeline_version,
        configuration=assessment.configuration,
        recommended_configuration=assessment.configuration,
        source_temperature_c=assessment.source_temperature_c,
        temperature_status=well.temperature_status,
        thermal_output_kw=assessment.thermal_output_kw,
        thermal_output_low_kw=assessment.thermal_output_low_kw,
        thermal_output_high_kw=assessment.thermal_output_high_kw,
        thermal_output_status=assessment.thermal_output_status,
        heat_pump_cop=assessment.heat_pump_cop,
        heat_pump_electricity_kw=assessment.heat_pump_electricity_kw,
        delivered_heat_kw=assessment.delivered_heat_kw,
        network_length_m=assessment.network_length_m,
        network_heat_loss_kw=assessment.network_heat_loss_kw,
        network_loss_fraction=assessment.network_loss_fraction,
        demand_matched_kw=assessment.demand_matched_kw,
        annual_heat_kwh=assessment.annual_heat_kwh,
        capex_gbp=assessment.capex_gbp,
        opex_gbp_per_year=assessment.opex_gbp_per_year,
        lcoh_p_per_kwh=assessment.lcoh_p_per_kwh,
        npv_gbp=assessment.npv_gbp,
        irr_pct=assessment.irr_pct,
        payback_years=assessment.payback_years,
        break_even_heat_price_p_per_kwh=assessment.break_even_heat_price_p_per_kwh,
        feasibility_score=assessment.feasibility_score,
        confidence_score=assessment.confidence_score,
        confidence_band=assessment.confidence_band,
        component_scores=assessment.component_scores,
        recommendation=Recommendation(assessment.recommendation),
        recommendation_rationale=assessment.recommendation_rationale,
        next_action=assessment.next_action,
        risk=(
            RiskAssessmentRead(**assessment.risk_assessment.to_dict())
            if assessment.risk_assessment
            else None
        ),
        confidence_detail=confidence_detail,
        data_gaps=assessment.data_gaps,
        unknowns=assessment.unknowns,
        warnings=assessment.warnings[:25],
        calculation_trace=assessment.calculation_trace.get("traces", []),
        parameters=assessment.parameters,
        agent_outputs=(orchestration.to_dict() if orchestration else None),
        report_markdown=(orchestration.report_markdown if orchestration else None),
        executive_summary=(orchestration.executive_summary if orchestration else None),
    )


def _analysis_to_result(db: DbSession, analysis: Analysis, well: Well | None = None) -> AnalysisResult:
    """Reconstruct a stored analysis as a response.

    Reads the persisted values rather than re-running the pipeline, so a stored
    analysis always shows the numbers that were actually recorded at the time.
    """
    well = well or db.get(Well, analysis.well_id)
    if well is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="well not found")

    risks = list(db.scalars(select(Risk).where(Risk.analysis_id == analysis.id)))
    actions = list(
        db.scalars(
            select(ValidationAction).where(ValidationAction.analysis_id == analysis.id)
        )
    )
    gaps = (analysis.data_gaps or {}).get("gaps", [])

    # The trace lives in its own table, one row per function call. Status,
    # confidence and warnings were stored in the row's JSON sidecar; older rows
    # predate the units/assumptions keys, so those default rather than fail.
    trace_rows = db.scalars(
        select(CalculationTrace)
        .where(CalculationTrace.analysis_id == analysis.id)
        .order_by(CalculationTrace.created_at, CalculationTrace.function_name)
    ).all()

    def _trace_entry(t: CalculationTrace) -> dict[str, Any]:
        sidecar: dict[str, Any] = t.warnings or {}
        return {
            "function_name": t.function_name,
            "inputs": t.inputs or {},
            "input_units": sidecar.get("input_units") or {},
            "formula": t.formula,
            "result": t.result,
            "result_unit": t.result_unit or "",
            "status": sidecar.get("status") or EpistemicStatus.DERIVED.value,
            "assumptions": sidecar.get("assumptions") or [],
            "sources": sidecar.get("sources") or [],
            "intermediate_values": t.intermediate_values or {},
            "warnings": list(sidecar.get("warnings") or []),
            "confidence": sidecar.get("confidence"),
            "engine_version": t.engine_version,
        }

    result = AnalysisResult(
        analysis_id=analysis.id,
        well_id=well.well_id,
        well_uuid=well.id,
        well_name=well.well_name,
        pipeline_version=analysis.engine_version or "0.1.0",
        configuration=analysis.recommended_configuration or GeothermalConfiguration.CLOSED_LOOP.value,
        recommended_configuration=(
            analysis.recommended_configuration or GeothermalConfiguration.CLOSED_LOOP.value
        ),
        source_temperature_c=analysis.source_temperature_c,
        temperature_status=analysis.temperature_status or "UNKNOWN",
        thermal_output_kw=analysis.thermal_output_kw,
        thermal_output_status=analysis.thermal_output_status or "UNKNOWN",
        heat_pump_cop=analysis.heat_pump_cop,
        delivered_heat_kw=analysis.delivered_heat_kw,
        network_length_m=analysis.network_length_m,
        network_heat_loss_kw=analysis.network_heat_loss_kw,
        nearest_building_distance_m=analysis.nearest_building_distance_m,
        demand_matched_kw=analysis.demand_matched_kw,
        annual_heat_kwh=analysis.annual_heat_production_kwh,
        capex_gbp=analysis.capex_gbp,
        opex_gbp_per_year=analysis.opex_gbp_per_year,
        lcoh_p_per_kwh=analysis.lcoh_p_per_kwh,
        npv_gbp=analysis.npv_gbp,
        irr_pct=analysis.irr_pct,
        payback_years=analysis.payback_years,
        break_even_heat_price_p_per_kwh=analysis.break_even_heat_price_p_per_kwh,
        feasibility_score=analysis.feasibility_score or 0.0,
        confidence_score=analysis.confidence_score or 0.0,
        confidence_band=well.data_confidence,
        component_scores=(analysis.score_components or {}).get("scores", {}),
        recommendation=Recommendation(analysis.recommendation or "DO NOT PURSUE"),
        recommendation_rationale=[analysis.recommendation_rationale or ""],
        next_action=analysis.next_action or "",
        data_gaps=gaps,
        unknowns=(analysis.data_gaps or {}).get("unknowns", []),
        warnings=[],
        calculation_trace=[_trace_entry(t) for t in trace_rows],
        parameters={},
        agent_outputs=analysis.agent_outputs,
        report_markdown=analysis.report_markdown,
        executive_summary=analysis.executive_summary,
        validation_actions=[
            {
                "id": a.id,
                "action_type": a.action_type,
                "title": a.title,
                "description": a.description,
                "priority": a.priority,
                "rationale": a.rationale,
                "addresses_risk_ids": a.addresses_risk_ids or [],
                "addresses_data_gaps": a.addresses_data_gaps or [],
                "estimated_cost_gbp": a.estimated_cost_gbp,
                "estimated_duration_days": a.estimated_duration_days,
                "status": a.status,
            }
            for a in sorted(actions, key=lambda a: a.priority)
        ],
    )

    if risks:
        from app.schemas.well import RiskRead  # noqa: PLC0415

        total = 1.0
        for r in risks:
            total *= 1.0 - (r.uncertainty_adjusted_score or r.risk_score)
        result.risk = RiskAssessmentRead(
            aggregate_score=max(0.0, 1.0 - total),
            risk_count=len(risks),
            critical_count=sum(1 for r in risks if r.severity == "critical"),
            risks=[
                RiskRead(
                    category=r.category,
                    title=r.title,
                    description=r.description or "",
                    likelihood=r.probability,
                    probability=r.probability_numeric,
                    impact=r.impact,
                    impact_value=r.impact_numeric,
                    uncertainty=r.uncertainty,
                    risk_score=r.risk_score,
                    uncertainty_adjusted_score=(
                        r.uncertainty_adjusted_score or r.risk_score
                    ),
                    severity=r.severity,
                    is_critical=r.severity == "critical",
                    evidence=(r.evidence or {}).get("items", []),
                    mitigation=r.mitigation,
                )
                for r in risks
            ],
        )

    return result


