"""The eleven agents.

Each agent slices the assessment context down to what it needs, calls the LLM
provider with a schema-constrained prompt, and passes the result through the
discipline gate. None of them performs arithmetic; the deterministic results are
handed to them as context and they may only describe them.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import AgentRun, BaseAgent
from app.agents.schemas import (
    EconomicAssessment,
    EngineeringAssessment,
    FeasibilityAssessment,
    GeothermalInterpretation,
    HeatDemandAnalysis,
    HeatNetworkAnalysis,
    RegulatoryAnalysis,
    ReportOutput,
    RiskAssessmentSummary,
    WellDataInterpretation,
    WellIntegrityAssessment,
)


class WellDataAgent(BaseAgent):
    name = "WellDataAgent"
    schema = WellDataInterpretation

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        well = ctx.get("well", {})
        return {
            "well": {
                "well_name": well.get("well_name"),
                "well_id": well.get("well_id"),
                "operator": well.get("operator"),
                "licence": well.get("licence"),
                "status": well.get("status"),
                "status_raw": well.get("status_raw"),
                "original_purpose": well.get("original_purpose"),
                "drilling_year": well.get("drilling_year"),
                "commissioned_date": well.get("commissioned_date"),
                "plugged_and_abandoned_date": well.get("plugged_and_abandoned_date"),
                "total_depth_m": well.get("total_depth_m"),
                "tvd_m": well.get("tvd_m"),
                "md_m": well.get("md_m"),
                "max_deviation_deg": well.get("max_deviation_deg"),
                "is_deviated": well.get("is_deviated"),
                "formation": well.get("formation"),
                "basin": well.get("basin"),
                "latitude": well.get("latitude"),
                "longitude": well.get("longitude"),
                "county": well.get("county"),
                "data_completeness": well.get("data_completeness"),
                "known_data_gaps": well.get("known_data_gaps"),
                "temperatures": ctx.get("temperatures") or [],
                "logs": ctx.get("logs") or [],
            },
            "facts": ctx.get("verified_facts") or [],
        }


class GeothermalAgent(BaseAgent):
    name = "GeothermalAgent"
    schema = GeothermalInterpretation

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "temperature_c": ctx.get("source_temperature_c"),
            "temperature_status": ctx.get("temperature_status"),
            "temperature_depth_m": ctx.get("temperature_depth_m"),
            "geology": ctx.get("geology") or {},
            "geothermal_setting": ctx.get("geothermal_setting") or {},
            "formations": ctx.get("formations") or [],
            "water_chemistry": {
                "salinity_ppt": (ctx.get("geology") or {}).get("water_salinity_ppt"),
                "ph": (ctx.get("geology") or {}).get("water_ph"),
                "scaling_tendency": (ctx.get("geology") or {}).get("scaling_tendency"),
                "corrosion_tendency": (ctx.get("geology") or {}).get("corrosion_tendency"),
                "chemistry_status": (ctx.get("geology") or {}).get("chemistry_status"),
            },
            "configuration_chosen": ctx.get("configuration"),
            "facts": ctx.get("verified_facts") or [],
        }


class WellIntegrityAgent(BaseAgent):
    name = "WellIntegrityAgent"
    schema = WellIntegrityAssessment

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "well_status": ctx.get("well_status"),
            "drilling_year": ctx.get("drilling_year"),
            "total_depth_m": ctx.get("total_depth_m"),
            "has_casing_record": ctx.get("has_casing_record"),
            "casing_string": ctx.get("casing_string"),
            "completion_type": ctx.get("completion_type"),
            "plugged_and_abandoned_date": ctx.get("plugged_and_abandoned_date"),
            "integrity": ctx.get("integrity") or {},
            "geology": {
                "water_ph": (ctx.get("geology") or {}).get("water_ph"),
                "water_salinity_ppt": (ctx.get("geology") or {}).get("water_salinity_ppt"),
                "scaling_tendency": (ctx.get("geology") or {}).get("scaling_tendency"),
                "corrosion_tendency": (ctx.get("geology") or {}).get("corrosion_tendency"),
            },
            "integrity_score": ctx.get("component_scores", {}).get("integrity"),
            "integrity_score_weight": 0.20,
            "facts": ctx.get("verified_facts") or [],
        }


class HeatDemandAgent(BaseAgent):
    name = "HeatDemandAgent"
    schema = HeatDemandAnalysis

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        demand = ctx.get("demand") or {}
        output_kw = ctx.get("thermal_output_kw")
        annual = demand.get("total_annual_demand_kwh")
        ratio = None
        if annual is not None and output_kw:
            ratio = annual / (output_kw * 8760.0)

        return {
            "demand": demand,
            "thermal_output_kw": output_kw,
            "thermal_output_status": ctx.get("thermal_output_status"),
            "demand_to_output_ratio": ratio,
            "demand_score": ctx.get("component_scores", {}).get("demand"),
            "facts": ctx.get("verified_facts") or [],
        }


class HeatNetworkAgent(BaseAgent):
    name = "HeatNetworkAgent"
    schema = HeatNetworkAnalysis

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        network = ctx.get("network") or {}
        return {
            "network": network,
            "distance_m": ctx.get("nearest_building_distance_m"),
            "pipe_length_m": ctx.get("network_length_m"),
            "loss_fraction": ctx.get("network_loss_fraction"),
            "heat_loss_kw": ctx.get("network_heat_loss_kw"),
            "delivered_heat_kw": ctx.get("delivered_heat_kw"),
            "existing_networks": ctx.get("heat_networks") or [],
            "network_score": ctx.get("component_scores", {}).get("network"),
            "facts": ctx.get("verified_facts") or [],
        }


class EngineeringAgent(BaseAgent):
    name = "EngineeringAgent"
    schema = EngineeringAssessment

    def run(self, ctx: dict[str, Any], *, max_tokens: int | None = None) -> AgentRun:
        self.expected_thermal_status = ctx.get("thermal_output_status")
        return super().run(ctx, max_tokens=max_tokens)

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "engineering": {
                "configuration": ctx.get("configuration"),
                "configuration_rationale": " ".join(ctx.get("configuration_notes") or []),
                "flow_rate_lps": (ctx.get("parameters") or {})
                .get("values", {})
                .get("flow_rate_lps"),
                "source_temperature_c": ctx.get("source_temperature_c"),
                "return_temperature_c": (ctx.get("parameters") or {})
                .get("values", {})
                .get("return_temperature_c"),
                "usable_delta_t_c": (ctx.get("parameters") or {})
                .get("values", {})
                .get("usable_delta_t_c"),
                "thermal_output_kw": ctx.get("thermal_output_kw"),
                "thermal_output_low_kw": ctx.get("thermal_output_low_kw"),
                "thermal_output_high_kw": ctx.get("thermal_output_high_kw"),
                "thermal_output_status": ctx.get("thermal_output_status"),
                "heat_pump_cop": ctx.get("heat_pump_cop"),
                "heat_pump_electricity_kw": ctx.get("heat_pump_electricity_kw"),
                "delivered_heat_kw": ctx.get("delivered_heat_kw"),
                "network_heat_loss_kw": ctx.get("network_heat_loss_kw"),
                "annual_heat_kwh": ctx.get("annual_heat_kwh"),
            },
            "engine_version": ctx.get("pipeline_version"),
            "calculation_trace_count": len(ctx.get("calculation_trace") or []),
            "facts": ctx.get("verified_facts") or [],
        }


class EconomicAgent(BaseAgent):
    name = "EconomicAgent"
    schema = EconomicAssessment

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        params = (ctx.get("parameters") or {}).get("values", {})
        return {
            "economics": {
                "capex_gbp": ctx.get("capex_gbp"),
                "opex_gbp_per_year": ctx.get("opex_gbp_per_year"),
                "lcoh_p_per_kwh": ctx.get("lcoh_p_per_kwh"),
                "npv_gbp": ctx.get("npv_gbp"),
                "irr_pct": ctx.get("irr_pct"),
                "payback_years": ctx.get("payback_years"),
                "break_even_heat_price_p_per_kwh": ctx.get("break_even_heat_price_p_per_kwh"),
                "heat_pump_cop": ctx.get("heat_pump_cop"),
                "annual_heat_kwh": ctx.get("annual_heat_kwh"),
                "heat_price_p_per_kwh": params.get("heat_price_p_per_kwh"),
                "electricity_price_p_per_kwh": params.get("electricity_price_p_per_kwh"),
                "discount_rate": params.get("discount_rate"),
                "project_lifetime_years": params.get("project_lifetime_years"),
            },
            "economics_score": ctx.get("component_scores", {}).get("economics"),
            "facts": ctx.get("verified_facts") or [],
        }


class RegulatoryAgent(BaseAgent):
    name = "RegulatoryAgent"
    schema = RegulatoryAnalysis

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "configuration": ctx.get("configuration"),
            "location": {
                "county": ctx.get("county"),
                "region": ctx.get("region"),
                "latitude": ctx.get("latitude"),
                "longitude": ctx.get("longitude"),
            },
            "requirements": ctx.get("regulatory_requirements") or [],
            "flags": {
                "requires_abstraction_licence": ctx.get("requires_abstraction_licence"),
                "requires_discharge_consent": ctx.get("requires_discharge_consent"),
                "requires_planning_permission": ctx.get("requires_planning_permission"),
                "is_spa": ctx.get("is_spa"),
                "is_conservation_area": ctx.get("is_conservation_area"),
                "is_mining_subsidence_area": ctx.get("is_mining_subsidence_area"),
                "is_heritage_asset": ctx.get("is_heritage_asset"),
            },
            "regulatory_score": ctx.get("component_scores", {}).get("regulatory"),
            "facts": ctx.get("verified_facts") or [],
        }


class RiskAgent(BaseAgent):
    name = "RiskAgent"
    schema = RiskAssessmentSummary

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        risk = ctx.get("risk") or {}
        risks = risk.get("risks") or []
        return {
            "risks": risks,
            "aggregate_score": risk.get("aggregate_score"),
            "critical_count": risk.get("critical_count"),
            "data_gaps": ctx.get("data_gaps") or [],
            "risk_score_aggregate": risk.get("aggregate_score"),
            "facts": ctx.get("verified_facts") or [],
        }


class FeasibilityAgent(BaseAgent):
    name = "FeasibilityAgent"
    schema = FeasibilityAssessment

    def run(self, ctx: dict[str, Any], *, max_tokens: int | None = None) -> AgentRun:
        # Set immediately before the run so the discipline gate has the
        # deterministic value to compare the model's answer against.
        self.expected_recommendation = ctx.get("recommendation")
        return super().run(ctx, max_tokens=max_tokens)

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "feasibility_score": ctx.get("feasibility_score"),
            "confidence_score": ctx.get("confidence_score"),
            "confidence_band": ctx.get("confidence_band"),
            "component_scores": ctx.get("component_scores") or {},
            "component_notes": ctx.get("component_notes") or {},
            "weights": ctx.get("weights") or {},
            "weakest_components": ctx.get("weakest_components") or [],
            "deterministic_recommendation": ctx.get("recommendation"),
            "deterministic_rationale": ctx.get("recommendation_rationale") or [],
            "data_gaps": ctx.get("data_gaps") or [],
            "critical_risk_count": len(ctx.get("critical_risks") or []),
            "facts": ctx.get("verified_facts") or [],
        }

    def run(self, ctx: dict[str, Any], *, max_tokens: int | None = None) -> AgentRun:
        return super().run(ctx, max_tokens=max_tokens)


class ReportAgent(BaseAgent):
    name = "ReportAgent"
    schema = ReportOutput

    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "well_name": ctx.get("well_name"),
            "well_id": ctx.get("well_id"),
            "latitude": ctx.get("latitude"),
            "longitude": ctx.get("longitude"),
            "status": ctx.get("well_status"),
            "total_depth_m": ctx.get("total_depth_m"),
            "formation": ctx.get("formation"),
            "source_temperature_c": ctx.get("source_temperature_c"),
            "temperature_status": ctx.get("temperature_status"),
            "temperature_confidence": ctx.get("temperature_confidence"),
            "configuration": ctx.get("configuration"),
            "configuration_rationale": " ".join(ctx.get("configuration_notes") or []),
            "thermal_output_kw": ctx.get("thermal_output_kw"),
            "thermal_output_status": ctx.get("thermal_output_status"),
            "capex_gbp": ctx.get("capex_gbp"),
            "opex_gbp_per_year": ctx.get("opex_gbp_per_year"),
            "lcoh_p_per_kwh": ctx.get("lcoh_p_per_kwh"),
            "npv_gbp": ctx.get("npv_gbp"),
            "irr_pct": ctx.get("irr_pct"),
            "heat_price_p_per_kwh": (ctx.get("parameters") or {})
            .get("values", {})
            .get("heat_price_p_per_kwh"),
            "feasibility_score": ctx.get("feasibility_score"),
            "confidence_score": ctx.get("confidence_score"),
            "recommendation": ctx.get("recommendation"),
            "recommendation_reasoning": " ".join(ctx.get("recommendation_rationale") or []),
            "next_action": ctx.get("next_action"),
            "data_gaps": ctx.get("data_gaps") or [],
            "geology_summary": ctx.get("geology_summary"),
            "integrity_summary": ctx.get("integrity_summary"),
            "demand_summary": ctx.get("demand_summary"),
            "network_summary": ctx.get("network_summary"),
            "risk_summary": ctx.get("risk_summary"),
            "regulatory_summary": ctx.get("regulatory_summary"),
            "validation_plan": ctx.get("validation_plan"),
            "agent_summaries": ctx.get("agent_summaries") or {},
            "evidence": ctx.get("evidence") or [],
            "facts": ctx.get("verified_facts") or [],
        }


ALL_AGENT_CLASSES = (
    WellDataAgent,
    GeothermalAgent,
    WellIntegrityAgent,
    HeatDemandAgent,
    HeatNetworkAgent,
    EngineeringAgent,
    EconomicAgent,
    RegulatoryAgent,
    RiskAgent,
    FeasibilityAgent,
    ReportAgent,
)


def build_agents(llm: Any) -> dict[str, BaseAgent]:
    """Instantiate all eleven agents against one provider."""
    return {cls.name: cls(llm) for cls in ALL_AGENT_CLASSES}
