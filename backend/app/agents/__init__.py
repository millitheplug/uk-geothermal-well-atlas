"""AI agent layer.

Eleven agents, structured JSON output, evidence discipline enforced in code
rather than requested in a prompt. Deterministic results are computed in
:mod:`app.engineering` and passed to the agents as context; the agents may
describe those results but never compute or alter them.
"""

from app.agents.agents import ALL_AGENT_CLASSES, build_agents
from app.agents.base import AgentRun, BaseAgent, DisciplineViolation, enforce_discipline
from app.agents.llm import (
    AnthropicProvider,
    LLMError,
    LLMProvider,
    LLMResponse,
    MockProvider,
    get_llm_provider,
)
from app.agents.orchestrator import (
    AGENT_SEQUENCE,
    STAGE_ORDER,
    AgentOrchestrator,
    OrchestrationResult,
    render_report_markdown,
)
from app.agents.schemas import (
    AGENT_NAMES,
    EconomicAssessment,
    EngineeringAssessment,
    FactRecord,
    FeasibilityAssessment,
    GeothermalInterpretation,
    HeatDemandAnalysis,
    HeatNetworkAnalysis,
    RegulatoryAnalysis,
    ReportOutput,
    RiskAssessmentSummary,
    UnknownRecord,
    WellDataInterpretation,
    WellIntegrityAssessment,
)

__all__ = [
    "AGENT_NAMES",
    "AGENT_SEQUENCE",
    "ALL_AGENT_CLASSES",
    "STAGE_ORDER",
    "AgentOrchestrator",
    "AgentRun",
    "AnthropicProvider",
    "BaseAgent",
    "DisciplineViolation",
    "EconomicAssessment",
    "EngineeringAssessment",
    "FactRecord",
    "FeasibilityAssessment",
    "GeothermalInterpretation",
    "HeatDemandAnalysis",
    "HeatNetworkAnalysis",
    "LLMError",
    "LLMProvider",
    "LLMResponse",
    "MockProvider",
    "OrchestrationResult",
    "RegulatoryAnalysis",
    "ReportOutput",
    "RiskAssessmentSummary",
    "STAGE_ORDER",
    "UnknownRecord",
    "WellDataInterpretation",
    "WellIntegrityAssessment",
    "build_agents",
    "enforce_discipline",
    "get_llm_provider",
    "render_report_markdown",
]
