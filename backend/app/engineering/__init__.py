"""Deterministic engineering engine.

Every function that performs arithmetic lives in this package. The LLM layer
imports from here and is forbidden from doing calculations of its own.
"""

from app.engineering.base import (
    ENGINE_VERSION,
    AssumptionRef,
    CalcResult,
    CalculationContext,
    CalculationError,
    SourceRef,
    Unit,
)
from app.engineering.confidence import (
    ConfidenceAssessment,
    assess_confidence,
    band_for,
)
from app.engineering.cost import capex
from app.engineering.financial import (
    CashFlow,
    IrrResult,
    break_even,
    discounted_payback,
    irr,
    lcoh,
    npv,
    payback,
)
from app.engineering.heatpump import (
    annual_heat_production,
    carnot_cop,
    heat_pump_electricity_kw,
    heat_pump_performance,
)
from app.engineering.network import network_heat_loss, supply_temperature_penalty
from app.engineering.opex import opex
from app.engineering.parameters import (
    DEFAULTS,
    ParameterSet,
    ParameterSpec,
    parameters_for_configuration,
)
from app.engineering.pipeline import (
    PIPELINE_VERSION,
    WellAssessment,
    WellInputs,
    assess_well,
)
from app.engineering.risk import RiskAssessment, RiskBuilder, RiskItem
from app.engineering.scoring import (
    SCORE_VERSION,
    WEIGHTS,
    FeasibilityScore,
    composite_score,
    demand_score,
    economics_score,
    geometry_score,
    integrity_score,
    network_score,
    recommend,
    regulatory_score,
    thermal_score,
)
from app.engineering.thermal import (
    ThermalOutput,
    heat_extraction,
    thermal_power,
)

__all__ = [
    "DEFAULTS",
    "ENGINE_VERSION",
    "PIPELINE_VERSION",
    "SCORE_VERSION",
    "WEIGHTS",
    "AssumptionRef",
    "CalcResult",
    "CalculationContext",
    "CalculationError",
    "CashFlow",
    "ConfidenceAssessment",
    "FeasibilityScore",
    "IrrResult",
    "ParameterSet",
    "ParameterSpec",
    "RiskAssessment",
    "RiskBuilder",
    "RiskItem",
    "SourceRef",
    "ThermalOutput",
    "Unit",
    "WellAssessment",
    "WellInputs",
    "annual_heat_production",
    "assess_confidence",
    "assess_well",
    "band_for",
    "break_even",
    "carnot_cop",
    "capex",
    "composite_score",
    "demand_score",
    "discounted_payback",
    "economics_score",
    "geometry_score",
    "heat_extraction",
    "heat_pump_electricity_kw",
    "heat_pump_performance",
    "integrity_score",
    "irr",
    "lcoh",
    "network_heat_loss",
    "npv",
    "opex",
    "parameters_for_configuration",
    "payback",
    "recommend",
    "regulatory_score",
    "supply_temperature_penalty",
    "thermal_power",
    "thermal_score",
]
