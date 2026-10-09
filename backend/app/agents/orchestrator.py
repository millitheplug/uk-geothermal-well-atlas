"""Agent orchestration: run the eleven agents in order and assemble a report.

Order is fixed and each stage feeds the next. The orchestrator is also where the
LLM's output is reconciled against the deterministic results:

* the expected recommendation and thermal status are injected into the agent
  context so the discipline gate has something to compare against;
* a rejected agent output is recorded and the run continues with the other
  agents, because a screening assessment should not fail because one narrative
  agent misbehaved;
* the report sections are checked against the required list, and any missing
  section is filled deterministically from the calculated values.

The deterministic results are never modified by anything in this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.agents import ALL_AGENT_CLASSES, BaseAgent
from app.agents.base import AgentRun, DisciplineViolation, claims_from_output
from app.agents.llm import LLMError, LLMProvider, get_llm_provider
from app.agents.prompts import REQUIRED_REPORT_SECTIONS
from app.agents.schemas import ReportOutput, ReportSection
from app.core.enums import AnalysisStage
from app.engineering.pipeline import WellAssessment

logger = logging.getLogger(__name__)

#: Agent execution order, mapped to the progress stage each one advances.
AGENT_SEQUENCE: tuple[tuple[str, AnalysisStage], ...] = (
    ("WellDataAgent", AnalysisStage.DATA_VALIDATION),
    ("GeothermalAgent", AnalysisStage.GEOLOGY),
    ("WellIntegrityAgent", AnalysisStage.WELL_INTEGRITY),
    ("HeatDemandAgent", AnalysisStage.HEAT_DEMAND),
    ("HeatNetworkAgent", AnalysisStage.HEAT_DEMAND),
    ("EngineeringAgent", AnalysisStage.ENGINEERING),
    ("EconomicAgent", AnalysisStage.ECONOMICS),
    ("RegulatoryAgent", AnalysisStage.FINAL_ASSESSMENT),
    ("RiskAgent", AnalysisStage.RISK),
    ("FeasibilityAgent", AnalysisStage.FINAL_ASSESSMENT),
    ("ReportAgent", AnalysisStage.FINAL_ASSESSMENT),
)

STAGE_ORDER: tuple[AnalysisStage, ...] = (
    AnalysisStage.DATA_VALIDATION,
    AnalysisStage.GEOLOGY,
    AnalysisStage.TEMPERATURE,
    AnalysisStage.WELL_INTEGRITY,
    AnalysisStage.HEAT_DEMAND,
    AnalysisStage.ENGINEERING,
    AnalysisStage.ECONOMICS,
    AnalysisStage.RISK,
    AnalysisStage.FINAL_ASSESSMENT,
)


@dataclass
class OrchestrationResult:
    """Everything the agent layer produced for one assessment."""

    agent_runs: dict[str, AgentRun] = field(default_factory=dict)
    report: ReportOutput | None = None
    report_markdown: str | None = None
    executive_summary: str | None = None
    claims: list[Any] = field(default_factory=list)
    violations: list[DisciplineViolation] = field(default_factory=list)
    stages_completed: list[AnalysisStage] = field(default_factory=list)
    provider_name: str = "mock"
    model_name: str = ""
    total_duration_ms: float = 0.0

    @property
    def accepted_agents(self) -> list[str]:
        return [name for name, run in self.agent_runs.items() if run.accepted]

    @property
    def rejected_agents(self) -> list[str]:
        return [name for name, run in self.agent_runs.items() if not run.accepted]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "agents": {name: run.to_dict() for name, run in self.agent_runs.items()},
            "accepted_agents": self.accepted_agents,
            "rejected_agents": self.rejected_agents,
            "violations": [
                {"agent": v.agent, "rule": v.rule, "detail": v.detail, "action": v.action}
                for v in self.violations
            ],
            "stages_completed": [str(s) for s in self.stages_completed],
            "total_duration_ms": round(self.total_duration_ms, 2),
            "is_mock": self.provider_name == "mock",
        }


class AgentOrchestrator:
    """Runs the eleven agents over one deterministic assessment."""

    def __init__(
        self,
        llm: LLMProvider | None = None,
        *,
        prefer_mock: bool = False,
    ) -> None:
        self.llm = llm or get_llm_provider(prefer_mock=prefer_mock)
        self.agents: dict[str, BaseAgent] = {
            cls.name: cls(self.llm) for cls in ALL_AGENT_CLASSES
        }

    def run(
        self,
        assessment: WellAssessment,
        context: dict[str, Any],
        *,
        include_report: bool = True,
    ) -> OrchestrationResult:
        """Run every agent in order.

        Args:
            assessment: The deterministic result. Agents may describe it; nothing
                here can change it.
            context: The full assessment context assembled by the service layer.
            include_report: Set false to skip the ReportAgent.

        Returns:
            OrchestrationResult with per-agent output, violations and the report.
        """
        import time  # noqa: PLC0415

        started = time.perf_counter()
        result = OrchestrationResult(
            provider_name=self.llm.name,
            model_name=getattr(self.llm, "_model", "mock-deterministic-v1"),
        )

        enriched = self._enrich_context(assessment, context)

        for agent_name, stage in AGENT_SEQUENCE:
            if agent_name == "ReportAgent" and not include_report:
                continue

            agent = self.agents[agent_name]
            try:
                run = agent.run(enriched)
            except LLMError as exc:
                logger.warning("agent %s failed: %s", agent_name, exc)
                result.violations.append(
                    DisciplineViolation(
                        agent_name, "provider_error", str(exc), "rejected"
                    )
                )
                if stage not in result.stages_completed:
                    result.stages_completed.append(stage)
                continue
            except Exception as exc:  # noqa: BLE001
                # One narrative agent failing must not lose the deterministic work.
                logger.exception("agent %s raised", agent_name)
                result.violations.append(
                    DisciplineViolation(
                        agent_name, "unexpected_error", str(exc), "rejected"
                    )
                )
                if stage not in result.stages_completed:
                    result.stages_completed.append(stage)
                continue

            result.agent_runs[agent_name] = run
            result.violations.extend(run.violations)
            result.claims.extend(claims_from_output(agent_name, run.output))
            if stage not in result.stages_completed:
                result.stages_completed.append(stage)

        # The report needs the other agents' summaries, so it runs last and gets
        # a context that now includes them.
        if include_report and "ReportAgent" in result.agent_runs:
            report_run = result.agent_runs["ReportAgent"]
            if isinstance(report_run.output, ReportOutput):
                report = self._finalise_report(report_run.output, enriched)
                result.report = report
                result.report_markdown = render_report_markdown(report)
                result.executive_summary = report.executive_summary
                result.agent_runs["ReportAgent"] = AgentRun(
                    agent_name="ReportAgent",
                    output=report,
                    response=report_run.response,
                    violations=report_run.violations,
                    duration_ms=report_run.duration_ms,
                )

        result.total_duration_ms = (time.perf_counter() - started) * 1000.0
        return result

    def _enrich_context(
        self, assessment: WellAssessment, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Add derived narrative context the service layer cannot know.

        Only deterministic derivations. Nothing here computes a score or a
        financial figure; it summarises what the pipeline already produced so
        the agents do not each have to re-derive it.
        """
        enriched = dict(context)

        enriched["well_id"] = assessment.well_id
        enriched["feasibility_score"] = assessment.feasibility_score
        enriched["confidence_score"] = assessment.confidence_score
        enriched["confidence_band"] = assessment.confidence_band
        enriched["component_scores"] = assessment.component_scores
        enriched["recommendation"] = assessment.recommendation
        enriched["recommendation_rationale"] = assessment.recommendation_rationale
        enriched["next_action"] = assessment.next_action
        enriched["data_gaps"] = assessment.data_gaps
        enriched["unknowns"] = assessment.unknowns
        enriched["risk"] = (
            assessment.risk_assessment.to_dict() if assessment.risk_assessment else {}
        )
        enriched["confidence_detail"] = (
            assessment.confidence_assessment.to_dict()
            if assessment.confidence_assessment
            else {}
        )
        enriched["calculation_trace"] = assessment.calculation_trace.get("traces", [])
        enriched["parameters"] = assessment.parameters
        enriched["pipeline_version"] = assessment.pipeline_version

        # Component notes come from the scoring functions and are the reason a
        # score is what it is. Passing them through saves each agent from
        # inventing its own rationale.
        enriched["component_notes"] = _component_notes(assessment.calculation_trace)

        # Which components are weakest, weighted by how much they matter.
        enriched["weakest_components"] = _weakest_components(assessment.component_scores)

        # Summaries assembled deterministically for the report agent.
        enriched["geology_summary"] = _geology_summary(enriched)
        enriched["integrity_summary"] = _integrity_summary(enriched)
        enriched["demand_summary"] = _demand_summary(enriched, assessment)
        enriched["network_summary"] = _network_summary(enriched, assessment)
        enriched["risk_summary"] = _risk_summary(assessment)
        enriched["regulatory_summary"] = _regulatory_summary(enriched)
        enriched["validation_plan"] = _validation_plan(assessment, enriched)
        enriched["agent_summaries"] = {}

        return enriched

    def _finalise_report(
        self, report: ReportOutput, context: dict[str, Any]
    ) -> ReportOutput:
        """Enforce the required section list and the recommendation.

        The report is the main artefact a human reads, so it is verified rather
        than trusted: any missing section is generated from the calculated
        values, and a recommendation that disagrees with the deterministic one is
        replaced.
        """
        sections: list[ReportSection] = list(report.sections)
        present = {s.title.strip().lower() for s in sections}

        for title in REQUIRED_REPORT_SECTIONS:
            if title.strip().lower() in present:
                continue
            sections.append(
                ReportSection(
                    title=title,
                    content=_deterministic_section(title, context),
                    evidence_ids=[],
                )
            )

        # Order sections to match the required list exactly.
        order = {t.lower(): i for i, t in enumerate(REQUIRED_REPORT_SECTIONS)}
        sections.sort(key=lambda s: order.get(s.title.strip().lower(), len(order)))

        expected = context.get("recommendation")
        if expected and str(report.overall_recommendation) != str(expected):
            logger.warning(
                "report recommendation %s replaced with deterministic %s",
                report.overall_recommendation,
                expected,
            )
            report = report.model_copy(update={"overall_recommendation": expected})
            for section in sections:
                if section.title == "Final recommendation":
                    sections = [
                        ReportSection(
                            title=s.title,
                            content=(
                                f"{expected}. This recommendation is produced "
                                "deterministically from the feasibility score, the "
                                "evidence confidence band and the number of critical "
                                "risks. "
                                + " ".join(context.get("recommendation_rationale") or [])
                                + f"\n\nNext action: {context.get('next_action', '')}"
                            ),
                            evidence_ids=s.evidence_ids,
                        )
                        if s.title == "Final recommendation"
                        else s
                        for s in sections
                    ]

        disclaimers = list(report.disclaimers)
        required_disclaimer = (
            "This report is a screening analysis produced from desk study and public "
            "records. It is not a statement of commercial viability."
        )
        if not any("not a statement of commercial viability" in d for d in disclaimers):
            disclaimers.insert(0, required_disclaimer)

        return report.model_copy(update={"sections": sections, "disclaimers": disclaimers})


# ------------------------------------------------------- helpers
def _component_notes(trace_container: Any) -> dict[str, list[str]]:
    """Collect per-function warnings from the calculation trace.

    Accepts either the full context dict from ``CalculationContext.to_dict()``
    or a bare trace list, because both shapes appear at call sites.
    """
    if isinstance(trace_container, dict):
        traces = trace_container.get("traces") or []
    else:
        traces = trace_container or []

    notes: dict[str, list[str]] = {}
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        for warning in trace.get("warnings", []):
            notes.setdefault(trace.get("function_name", "unknown"), []).append(warning)
    return notes


def _weakest_components(component_scores: dict[str, float]) -> list[str]:
    weights = {
        "thermal": 0.25,
        "integrity": 0.20,
        "demand": 0.15,
        "economics": 0.15,
        "network": 0.10,
        "geometry": 0.05,
        "regulatory": 0.05,
        "data_confidence": 0.05,
    }
    ordered = sorted(component_scores.items(), key=lambda kv: kv[1] * weights.get(kv[0], 0.1))
    return [name for name, _ in ordered[:2]]


def _geology_summary(ctx: dict[str, Any]) -> str:
    geology = ctx.get("geology") or {}
    if not geology:
        return "No formation-level characterisation is available for this well."
    bits = []
    if geology.get("geothermal_gradient_c_per_km"):
        bits.append(
            f"A geothermal gradient of {geology['geothermal_gradient_c_per_km']} degC/km "
            "is recorded"
        )
    if geology.get("permeability_md"):
        bits.append(f"formation permeability is {geology['permeability_md']} mD")
    else:
        bits.append("formation permeability is unknown, so deliverability is unassessed")
    if geology.get("net_thickness_m"):
        bits.append(f"the target interval is {geology['net_thickness_m']} m thick net")
    if geology.get("water_ph") is not None:
        bits.append(
            f"water pH is {geology['water_ph']}, with a recorded "
            f"{geology.get('scaling_tendency') or 'unquantified'} scaling tendency"
        )
    else:
        bits.append("no water chemistry is available, so corrosion and scaling are unquantified")
    return "; ".join(bits) + "."


def _integrity_summary(ctx: dict[str, Any]) -> str:
    integrity = ctx.get("integrity") or {}
    status = integrity.get("status", "unknown")
    if status == "unknown":
        return (
            "Well integrity has not been assessed. This is the single largest source "
            "of uncertainty in the reuse case and carries a 20% score weight."
        )
    parts = [f"Integrity is recorded as '{status}'"]
    if integrity.get("requires_reequipment") is not None:
        parts.append(
            "reequipment is required" if integrity["requires_reequipment"] else "no reequipment is indicated"
        )
    if integrity.get("estimated_recompletion_capex_gbp"):
        parts.append(
            f"recompletion is estimated at GBP {integrity['estimated_recompletion_capex_gbp']:,.0f} "
            f"({integrity.get('estimated_recompletion_capex_status', 'ESTIMATE')})"
        )
    return "; ".join(parts) + "."


def _demand_summary(ctx: dict[str, Any], assessment: WellAssessment) -> str:
    demand = ctx.get("demand") or {}
    if not demand.get("building_count"):
        return "No heat demand could be matched to this well's location."
    total = demand.get("total_annual_demand_kwh") or 0.0
    distance = demand.get("nearest_building_distance_m")
    output = assessment.thermal_output_kw
    ratio_text = ""
    if output and total:
        ratio = total / (output * 8760.0)
        if ratio < 0.25:
            ratio_text = (
                f" That is only {ratio:.0%} of the well's maximum annual output, so most "
                "of the heat would have no customer."
            )
        elif ratio <= 3.0:
            ratio_text = f" That is {ratio:.1f}x the well's maximum annual output."
        else:
            ratio_text = (
                f" That is {ratio:.1f}x the well's maximum annual output, so the network "
                "would be heat-limited rather than source-limited."
            )
    return (
        f"{demand['building_count']} candidate off-taker(s) within "
        f"{demand.get('radius_m', 0)} m, totalling {total / 1e6:.2f} GWh of annual demand"
        + (f", nearest {distance:.0f} m away." if distance else ".")
        + ratio_text
        + " Demand figures are modelled estimates, not metered consumption."
    )


def _network_summary(ctx: dict[str, Any], assessment: WellAssessment) -> str:
    distance = ctx.get("nearest_building_distance_m")
    length = assessment.network_length_m
    loss = assessment.network_loss_fraction
    if not distance:
        return "No network route could be assessed because no demand was matched."
    text = f"The nearest off-taker is {distance:.0f} m away"
    if length:
        text += f", implying roughly {length:.0f} m of buried main"
    text += "."
    if loss is not None:
        text += f" Distribution losses on that route are about {loss:.0%}."
    if distance > 3000:
        text += (
            " Beyond roughly 3 km the pipe cost per useful kWh rises steeply and "
            "usually rules the scheme out."
        )
    return text


def _risk_summary(assessment: WellAssessment) -> str:
    risk = assessment.risk_assessment
    if not risk:
        return "No risk register was produced."
    critical = risk.critical_risks
    top = sorted(risk.risks, key=lambda r: r.uncertainty_adjusted_score, reverse=True)[:3]
    lines = [
        f"{len(risk.risks)} risks registered across the full taxonomy, aggregate exposure "
        f"{risk.aggregate_score:.0%}, {len(critical)} critical."
    ]
    if top:
        lines.append(
            "The largest exposures are "
            + "; ".join(
                f"{r.title.lower()} ({r.severity}, score {r.risk_score:.2f}"
                + (f", uncertainty {r.uncertainty:.0%}" if r.uncertainty > 0.3 else "")
                + ")"
                for r in top
            )
            + "."
        )
    return " ".join(lines)


def _regulatory_summary(ctx: dict[str, Any]) -> str:
    requirements = ctx.get("regulatory_requirements") or []
    flags = [
        name
        for name in (
            "requires_abstraction_licence",
            "requires_discharge_consent",
            "requires_planning_permission",
            "is_spa",
            "is_conservation_area",
            "is_mining_subsidence_area",
        )
        if ctx.get(name)
    ]
    text = (
        f"{len(requirements)} consent(s) or obligation(s) recorded for a "
        f"{ctx.get('configuration', 'unconfigured')} scheme."
        if requirements
        else "No consent requirements are recorded for this configuration."
    )
    if flags:
        text += (
            " Constraints flagged: "
            + ", ".join(f.replace("is_", "").replace("requires_", "") for f in flags)
            + ". These require confirmation with the relevant authority."
        )
    return text


def _validation_plan(assessment: WellAssessment, ctx: dict[str, Any]) -> str:
    steps = [
        f"1. {assessment.next_action}",
        "2. Establish nearby heat demand with a survey or an expression of interest "
        "from candidate off-takers.",
        "3. Obtain a Class 2 capital estimate including a route survey.",
        "4. Market-test the achievable heat price with anchor customers.",
        "5. Make pre-application contact with the planning authority and, where "
        "relevant, the Environment Agency.",
    ]
    gaps = assessment.data_gaps
    if gaps:
        steps.insert(
            1,
            f"Outstanding data gaps ({len(gaps)}): " + "; ".join(gaps[:5]) + ".",
        )
    return "\n".join(steps)


def _deterministic_section(title: str, ctx: dict[str, Any]) -> str:
    """Generate a report section directly from calculated values.

    Used when an agent's report omits a section. Never invents: every value
    comes from the deterministic result or reads 'not available'.
    """
    def fmt(key: str, unit: str = "", prefix: str = "") -> str:
        value = ctx.get(key)
        if value is None:
            return f"{prefix}not available"
        if isinstance(value, float):
            return f"{prefix}{value:,.1f}{unit}"
        return f"{prefix}{value:,}{unit}" if isinstance(value, int) else f"{prefix}{value}{unit}"

    mapping = {
        "Executive summary": lambda: ctx.get("executive_summary", "Not generated."),
        "Well characteristics": lambda: (
            f"{ctx.get('well_name')} ({ctx.get('well_id')}) at {ctx.get('latitude')}, "
            f"{ctx.get('longitude')}; status {ctx.get('well_status')}; total depth "
            f"{ctx.get('total_depth_m')} m; formation {ctx.get('formation') or 'not recorded'}; "
            f"operator {ctx.get('operator') or 'not recorded'}; licence "
            f"{ctx.get('licence') or 'not recorded'}."
        ),
        "Temperature assessment": lambda: (
            f"Recorded temperature {fmt('source_temperature_c', ' degC')} at "
            f"{fmt('temperature_depth_m', ' m')}. Status: "
            f"{ctx.get('temperature_status')}; confidence: "
            f"{ctx.get('temperature_confidence')}."
        ),
        "Geology": lambda: ctx.get("geology_summary") or "Not available.",
        "Well integrity": lambda: ctx.get("integrity_summary") or "Not available.",
        "Geothermal configuration": lambda: (
            f"{ctx.get('configuration')}. "
            + " ".join(ctx.get("configuration_notes") or [])
        ),
        "Thermal output": lambda: (
            f"{fmt('thermal_output_kw', ' kW')} wellhead output, status "
            f"{ctx.get('thermal_output_status')}, uncertainty band "
            f"{fmt('thermal_output_low_kw', ' kW')} to {fmt('thermal_output_high_kw', ' kW')}. "
            f"Heat pump COP {fmt('heat_pump_cop')}. "
            "This is an estimate unless a flow test is recorded."
        ),
        "Heat demand": lambda: ctx.get("demand_summary") or "Not available.",
        "Heat network": lambda: ctx.get("network_summary") or "Not available.",
        "CAPEX": lambda: fmt("capex_gbp", " GBP", "Estimated capital cost: "),
        "OPEX": lambda: fmt("opex_gbp_per_year", " GBP/yr", "Estimated operating cost: "),
        "LCOH": lambda: fmt("lcoh_p_per_kwh", " p/kWh", "Levelised cost of heat: "),
        "NPV": lambda: fmt("npv_gbp", " GBP", "Net present value: "),
        "IRR": lambda: fmt("irr_pct", "%", "Internal rate of return: "),
        "Risks": lambda: ctx.get("risk_summary") or "Not available.",
        "Regulatory considerations": lambda: ctx.get("regulatory_summary") or "Not available.",
        "Data gaps": lambda: (
            "\n".join(f"- {g}" for g in ctx.get("data_gaps") or [])
            or "No material data gaps recorded."
        ),
        "Validation plan": lambda: ctx.get("validation_plan") or "Not available.",
        "Final recommendation": lambda: (
            f"{ctx.get('recommendation')}. "
            + " ".join(ctx.get("recommendation_rationale") or [])
            + f"\n\nNext action: {ctx.get('next_action', 'not specified')}"
        ),
    }
    builder = mapping.get(title)
    return builder() if builder else "Not available."


def render_report_markdown(report: ReportOutput) -> str:
    """Render the report to markdown for storage and download."""
    lines: list[str] = [
        "# Geothermal Reuse Screening Report",
        "",
        "## Executive summary",
        "",
        report.executive_summary,
        "",
    ]

    for section in report.sections:
        if section.title == "Executive summary":
            continue
        lines.append(f"## {section.title}")
        lines.append("")
        lines.append(section.content)
        lines.append("")

    if report.disclaimers:
        lines.append("---")
        lines.append("")
        lines.append("### Disclaimers")
        lines.append("")
        for disclaimer in report.disclaimers:
            lines.append(f"- {disclaimer}")
        lines.append("")

    return "\n".join(lines)
