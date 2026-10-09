"""Agent base class and the validation gate.

The gate is the important part of this module. Prompts instructing a model not
to claim viability are a request; the checks below are the enforcement. Every
agent output passes through :func:`enforce_discipline` before the orchestrator
accepts it, and a violation is either corrected deterministically or the run is
failed with a recorded reason.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.agents.llm import LLMProvider, LLMResponse
from app.agents.prompts import (
    FORBIDDEN_PHRASES,
    system_prompt_for,
)
from app.agents.schemas import AgentBase, FactRecord
from app.schemas.well import ClaimRead


@dataclass
class DisciplineViolation:
    """One rule the output broke, and what was done about it."""

    agent: str
    rule: str
    detail: str
    action: str = "rejected"

    def __str__(self) -> str:
        return f"[{self.agent}] {self.rule}: {self.detail} ({self.action})"


@dataclass
class AgentRun:
    """Result of running one agent."""

    agent_name: str
    output: BaseModel
    response: LLMResponse | None = None
    violations: list[DisciplineViolation] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def accepted(self) -> bool:
        return not any(v.action == "rejected" for v in self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent_name,
            "accepted": self.accepted,
            "violations": [
                {
                    "rule": v.rule,
                    "detail": v.detail,
                    "action": v.action,
                }
                for v in self.violations
            ],
            "duration_ms": round(self.duration_ms, 2),
            "provider": self.response.provider if self.response else None,
            "model": self.response.model if self.response else None,
            "is_mock": self.response.is_mock if self.response else False,
            "output": self.output.model_dump(mode="json"),
        }


def enforce_discipline(
    agent_name: str,
    output: BaseModel,
    *,
    expected_recommendation: str | None = None,
    expected_thermal_status: str | None = None,
) -> tuple[BaseModel, list[DisciplineViolation]]:
    """Check one agent's output against the non-negotiable rules.

    The deterministic expectations are passed in as arguments rather than read
    from the model. The schemas are strict about extra fields, and smuggling
    expected values through the payload would mean an agent could see - and
    echo back - the very values it is meant to be checked against.

    Returns the (possibly repaired) output and the list of violations found.

    Two classes of violation are handled differently:

    * **Repairable** - a missing source citation on an ESTIMATE, for example. The
      fact is relabelled ASSUMPTION, which is a true statement about its own
      provenance, rather than the run being failed over a formatting detail.
    * **Fatal** - a claim of commercial viability, or a recommendation that
      disagrees with the deterministic one. These cannot be repaired, because the
      whole value of the system is that it does not make those claims. The run is
      rejected and recorded.
    """
    violations: list[DisciplineViolation] = []

    text = _all_text(output)

    # ---- Rule 4: no commercial viability claims -----------------------
    lowered = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase == "proven technology":
            # Legitimate as a general statement about ground source heat pumps.
            # Only a problem when the text narrows it to this well or this
            # scheme, because then it is claiming a track record that does not
            # exist.
            if phrase in lowered and any(
                marker in lowered for marker in _NARROWING_MARKERS
            ):
                violations.append(
                    DisciplineViolation(
                        agent_name,
                        "no_guaranteed_viability",
                        f"output asserts '{phrase}' of this specific well or scheme",
                        "rejected",
                    )
                )
            continue
        if phrase in lowered:
            violations.append(
                DisciplineViolation(
                    agent_name,
                    "no_guaranteed_viability",
                    f"output contains the prohibited phrase '{phrase}'",
                    "rejected",
                )
            )

    # ---- Rule 1 and 8: every non-assumption fact must cite a source ----
    facts = getattr(output, "facts", None)
    if isinstance(facts, list):
        repaired: list[FactRecord] = []
        for fact in facts:
            # Output that bypassed validation can arrive as a plain dict. Coerce
            # with `model_construct` rather than `model_validate`, because
            # FactRecord's own validator is the rule this loop exists to repair:
            # validating first would reject every unsourced ESTIMATE as invalid
            # instead of relabelling it, making the repair unreachable.
            if isinstance(fact, dict):
                if "statement" not in fact or "fact_type" not in fact:
                    violations.append(
                        DisciplineViolation(
                            agent_name,
                            "malformed_fact",
                            f"fact record is missing required keys: {str(fact)[:120]}",
                            "dropped",
                        )
                    )
                    continue
                fact = FactRecord.model_construct(
                    **{
                        "statement": fact.get("statement"),
                        "fact_type": fact.get("fact_type"),
                        "source": fact.get("source"),
                        "source_url": fact.get("source_url"),
                        "field_name": fact.get("field_name"),
                        "confidence": fact.get("confidence"),
                    }
                )

            if fact.fact_type in ("FACT", "MEASURED", "DERIVED", "ESTIMATE") and not fact.source:
                violations.append(
                    DisciplineViolation(
                        agent_name,
                        "evidence_required",
                        f"assertion '{fact.statement[:60]}' has no source but is labelled "
                        f"{fact.fact_type}",
                        "relabelled as ASSUMPTION",
                    )
                )
                fact = fact.model_copy(update={"fact_type": "ASSUMPTION"})
            if fact.fact_type == "MEASURED" and not fact.source:
                violations.append(
                    DisciplineViolation(
                        agent_name,
                        "evidence_required",
                        "a MEASURED assertion has no source",
                        "relabelled as UNKNOWN",
                    )
                )
                fact = fact.model_copy(update={"fact_type": "UNKNOWN"})
            repaired.append(fact)
        if isinstance(output, AgentBase):
            output = output.model_copy(update={"facts": repaired})

    # ---- Rule 6: the recommendation must match the deterministic one ----
    actual = getattr(output, "recommendation", None)
    if expected_recommendation and actual is not None:
        if str(actual) != str(expected_recommendation):
            violations.append(
                DisciplineViolation(
                    agent_name,
                    "recommendation_must_be_deterministic",
                    f"agent produced {actual} but the deterministic engine produced "
                    f"{expected_recommendation}",
                    "rejected",
                )
            )

    # ---- Rule 3: thermal output status must not be upgraded ------------
    actual_status = getattr(output, "thermal_output_status", None)
    if expected_thermal_status and actual_status:
        if _status_rank(actual_status) > _status_rank(expected_thermal_status):
            violations.append(
                DisciplineViolation(
                    agent_name,
                    "no_status_upgrade",
                    f"agent upgraded thermal output status from {expected_thermal_status} "
                    f"to {actual_status}",
                    "reverted",
                )
            )
            output = output.model_copy(update={"thermal_output_status": expected_thermal_status})

    if violations and isinstance(output, BaseModel):
        output = output.model_copy(
            update={"confidence_notes": _append_notes(output, violations)}
        )

    return output, violations


#: Phrases that narrow a general statement to the well under assessment. Used
#: only for phrases that are legitimate in general but not of this well.
_NARROWING_MARKERS: tuple[str, ...] = (
    "this well",
    "this scheme",
    "this project",
    "this site",
    "this candidate",
    "the well is",
    "the scheme is",
)

_STATUS_ORDER = {
    "UNKNOWN": 0,
    "ASSUMPTION": 1,
    "ESTIMATE": 2,
    "DERIVED": 3,
    "MEASURED": 4,
    "FACT": 5,
}

#: Lower bound each confidence band must reach, tested in the order the bands
#: are listed where the lookup happens. "unknown" has to be present because the
#: loop runs over every band name, but its threshold sits above any real
#: confidence value so that it is never selected and stays the fallback.
_CONFIDENCE_BANDS: dict[str, float] = {
    "high": 0.75,
    "medium": 0.55,
    "low": 0.35,
    "very_low": 0.0,
    "unknown": 1.01,
}


def _status_rank(status: str) -> int:
    return _STATUS_ORDER.get(str(status).upper(), 0)


def _append_notes(output: BaseModel, violations: list[DisciplineViolation]) -> str:
    """Record the corrections in the output so they are visible downstream."""
    existing = getattr(output, "confidence_notes", None) or ""
    correction = "Corrected by the discipline gate: " + "; ".join(
        f"{v.rule} ({v.action})" for v in violations
    )
    return f"{existing}\n\n{correction}".strip()


def _all_text(output: BaseModel) -> str:
    """Flatten every string in the output for rule scanning."""
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v)

    walk(output.model_dump(mode="json") if isinstance(output, BaseModel) else output)
    return " ".join(parts)


class BaseAgent(ABC):
    """One agent: a system prompt, a schema, and a context builder."""

    name: str
    schema: type[BaseModel]

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    @abstractmethod
    def build_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Extract this agent's slice of the assessment context."""

    def system_prompt(self) -> str:
        return system_prompt_for(self.name)

    def user_prompt(self, context: dict[str, Any]) -> str:
        return (
            "Assess the well described below. Use only the facts provided in the "
            "context. Anything not present in the context is unknown to you.\n\n"
            "CONTEXT_JSON:\n" + json.dumps(context, indent=2, default=str)
        )

    #: Values from the deterministic result this agent's output must agree with.
    #: Subclasses override where relevant.
    expected_recommendation: str | None = None
    expected_thermal_status: str | None = None

    def run(self, ctx: dict[str, Any], *, max_tokens: int | None = None) -> AgentRun:
        import time  # noqa: PLC0415

        started = time.perf_counter()
        context = self.build_context(ctx)
        result, response = self.llm.complete_model(
            system=self.system_prompt(),
            user=self.user_prompt(context),
            schema=self.schema,
            max_tokens=max_tokens,
        )
        output, violations = enforce_discipline(
            self.name,
            result,
            expected_recommendation=self.expected_recommendation,
            expected_thermal_status=self.expected_thermal_status,
        )
        return AgentRun(
            agent_name=self.name,
            output=output,
            response=response,
            violations=violations,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )


def claims_from_output(agent_name: str, output: BaseModel) -> list[ClaimRead]:
    """Convert an agent's facts into persistable claim records."""
    facts = getattr(output, "facts", None)
    if not isinstance(facts, list):
        return []

    claims: list[ClaimRead] = []
    for fact in facts:
        claims.append(
            ClaimRead(
                id=__import__("uuid").uuid4(),
                field_name=fact.field_name or "general",
                claim=fact.statement,
                value=None,
                status=fact.fact_type,
                confidence=(
                    str(
                        next(
                            (
                                b
                                for b in ("high", "medium", "low", "very_low", "unknown")
                                if (fact.confidence or 0) >= _CONFIDENCE_BANDS[b]
                            ),
                            "unknown",
                        )
                    )
                    if fact.confidence is not None
                    else None
                ),
                agent=agent_name,
                is_critical=fact.field_name in ("temperature_c", "well_integrity", "lcoh_p_per_kwh"),
                evidence=None,
            )
        )
    return claims
