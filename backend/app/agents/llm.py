"""LLM provider abstraction with a deterministic mock fallback.

Two implementations of one interface:

``AnthropicProvider``
    Calls Claude and forces a JSON schema via tool use. The schema is the
    contract; if the model returns something that does not validate, that is an
    error, not something to paper over.

``MockProvider``
    Returns schema-valid structured output derived deterministically from the
    supplied context. No network, no key, no variance. This is what makes the
    agent pipeline testable and what lets the platform run without a key.

The agent layer receives text-only instructions and a typed context object. It
never receives the ability to compute: see :mod:`app.agents.agents`.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.enums import EpistemicStatus, Recommendation

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the provider cannot produce schema-valid output."""


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    is_mock: bool = False


class LLMProvider(ABC):
    """Minimal interface: system prompt, user content, output schema."""

    name: str = "base"

    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Return structured output validating against ``schema``."""

    def complete_model(
        self, *, system: str, user: str, schema: type[T], max_tokens: int | None = None
    ) -> tuple[T, LLMResponse]:
        """Complete and validate against ``schema``.

        Retries once with the validation error appended, because a single
        recoverable schema miss should not fail an assessment. Retries are
        capped rather than looping, and a second failure raises: silently
        accepting malformed output is exactly what this platform forbids.
        """
        response = self.complete(
            system=system, user=user, schema=schema, max_tokens=max_tokens
        )
        try:
            payload = json.loads(response.text)
            return schema.model_validate(payload), response
        except (json.JSONDecodeError, ValidationError) as first_error:
            retry = self.complete(
                system=system,
                user=(
                    f"{user}\n\nYour previous response failed validation with:\n"
                    f"{first_error}\n\nReturn only valid JSON matching the required "
                    "schema. Do not add commentary outside the JSON."
                ),
                schema=schema,
                max_tokens=max_tokens,
            )
            try:
                return schema.model_validate(json.loads(retry.text)), retry
            except (json.JSONDecodeError, ValidationError) as second_error:
                raise LLMError(
                    f"{self.name} failed to produce schema-valid output for "
                    f"{schema.__name__}: {second_error}"
                ) from second_error


class AnthropicProvider(LLMProvider):
    """Claude via the Messages API, constrained by a forced tool call."""

    name = "anthropic"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not configured")
        import anthropic  # noqa: PLC0415

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    def complete(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int | None = None,
    ) -> LLMResponse:
        # Forcing a tool call with an input_schema is what guarantees structured
        # output: the model must fill the schema or the call fails.
        tool: dict[str, Any] = {
            "name": "submit",
            "description": f"Submit the structured result as {schema.__name__}.",
            "input_schema": schema.model_json_schema(),
        }

        message = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or settings.ai_max_tokens,
            temperature=settings.ai_temperature,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": "submit"},
            messages=[{"role": "user", "content": user}],
        )

        if message.stop_reason == "max_tokens":
            raise LLMError(
                "response hit the token limit before completing the schema; raise "
                "AI_MAX_TOKENS or reduce the requested detail"
            )

        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit":
                usage = message.usage
                return LLMResponse(
                    text=json.dumps(block.input),
                    model=self._model,
                    provider=self.name,
                    input_tokens=getattr(usage, "input_tokens", 0),
                    output_tokens=getattr(usage, "output_tokens", 0),
                    stop_reason=message.stop_reason,
                )

        raise LLMError("model returned no tool_use block despite a forced tool choice")


class MockProvider(LLMProvider):
    """Deterministic structured output derived from the supplied context.

    Not a stub that returns lorem ipsum: it reads the real assessment numbers
    and produces genuinely useful, correctly-labelled text. That means the whole
    report and evidence chain can be exercised, reviewed and tested without an
    API key, and it gives a stable baseline to diff real model output against.
    """

    name = "mock"

    def complete(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int | None = None,
    ) -> LLMResponse:
        context = _extract_context(user)
        builder = _MOCK_BUILDERS.get(schema.__name__)

        if builder is None:
            payload: dict[str, Any] = _minimal_payload(schema)
        else:
            payload = builder(context)

        try:
            schema.model_validate(payload)
        except ValidationError as exc:  # pragma: no cover - guards a builder bug
            raise LLMError(
                f"mock builder for {schema.__name__} produced invalid output: {exc}"
            ) from exc

        return LLMResponse(
            text=json.dumps(payload),
            model="mock-deterministic-v1",
            provider=self.name,
            is_mock=True,
            stop_reason="end_turn",
        )


def _extract_context(user: str) -> dict[str, Any]:
    """Pull the JSON context block the agents embed in their user message."""
    marker = "CONTEXT_JSON:"
    if marker not in user:
        return {}
    blob = user.split(marker, 1)[1]
    # The context is the last balanced JSON object in the message.
    start = blob.find("{")
    if start == -1:
        return {}
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(blob[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(blob[start : i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def _minimal_payload(schema: type[BaseModel]) -> dict[str, Any]:
    """Build a payload satisfying only the required fields of a schema."""
    payload: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        if not field.is_required():
            continue
        annotation = str(field.annotation)
        if "list" in annotation:
            payload[name] = []
        elif "bool" in annotation:
            payload[name] = False
        elif "int" in annotation or "float" in annotation:
            payload[name] = 0
        elif "dict" in annotation:
            payload[name] = {}
        else:
            payload[name] = ""
    return payload


def _facts(context: dict[str, Any], *path: str) -> list[dict[str, Any]]:
    return list(context.get("facts") or [])


def _next_step(
    action: str, rationale: str, priority: str = "medium"
) -> dict[str, Any]:
    """Build a structured next step.

    Priority is not decorative: the orchestrator sorts validation actions by it,
    and the whole point of the field is that a reader can see which action to do
    first without reading every rationale.
    """
    return {
        "action": action,
        "rationale": rationale,
        "priority": priority,
    }


def _capex_note(value: Any) -> str:
    """Describe a capital cost, or say plainly that there is none.

    Guards against formatting ``None`` into the output, which would produce
    "GBP None" in a report a reader might act on.
    """
    if value is None:
        return "Capital cost was not estimated, because no thermal output could be calculated."
    return (
        f"Estimated capital cost GBP {value:,.0f} is a Class 3 estimate carrying "
        "roughly 20% contingency."
    )


def _u(item: str, reason: str, impact: str, resolution: str | None = None) -> dict[str, Any]:
    """Build a structured unknown record.

    Every unknown names why it is unknown and what it prevents being concluded.
    An unknown that only says "unknown" gives the reader nothing to act on.
    """
    return {
        "item": item,
        "reason": reason,
        "impact": impact,
        "resolution_action": resolution,
    }


# ------------------------------------------------------------ builders
def _build_well_data_interpretation(ctx: dict[str, Any]) -> dict[str, Any]:
    well = ctx.get("well", {})
    temps = well.get("temperatures") or []
    summary = (
        f"{well.get('well_name', 'The well')} is recorded as "
        f"{well.get('status', 'unknown')} status"
        + (f", drilled in {well['drilling_year']}" if well.get("drilling_year") else "")
        + f", reaching {well['total_depth_m']} m."
        if well.get("total_depth_m")
        else f"{well.get('well_name', 'The well')} has no recorded total depth."
    )
    unknowns = [
        _u(
            "Temperature at depth" if not temps else "Formation pressure",
            "No static bottom-hole survey or pressure record is held in the dataset."
            if not temps
            else "No pressure record accompanies the temperature measurements.",
            "Thermal output and driveability cannot both be characterised."
            if not temps
            else "Productivity and inflow cannot be estimated.",
            "Search the well file for a static survey, then request any pressure data "
            "from the operator.",
        ),
        _u(
            "Casing condition",
            "No casing inspection or completion record is available.",
            "Whether the wellbore can be worked and reused is not established.",
            "Recover the completion record, then inspect if accessible.",
        ),
        _u(
            "Production history",
            "No production figures are held for this well.",
            "Thermal depletion from prior production cannot be assessed.",
            "Request production history under the NSTA data-sharing provisions.",
        ),
    ]
    well = ctx.get("well", {})
    name_confirmed = bool(well.get("well_id")) and bool(well.get("operator") is not None)

    return {
        "summary": summary,
        "facts": _facts(ctx),
        "unknowns": unknowns,
        "data_quality": "poor" if not temps else "partial",
        "well_name_confirmed": name_confirmed,
        "confidence_notes": (
            "Only the fields listed as facts could be traced to a source record."
        ),
        "recommended_next_steps": [
            _next_step(
                "Obtain the well completion record from the operator",
                "Without it, casing condition and abandonment status cannot be assessed, "
                "and integrity carries a 20% score weight.",
                "critical" if not temps else "high",
            ),
            _next_step(
                "Search the historical well file for a static bottom-hole survey",
                "This is a records request rather than fieldwork, and it gates every "
                "downstream judgement about the well.",
                "critical" if not temps else "high",
            ),
        ],
    }


def _build_geothermal_interpretation(ctx: dict[str, Any]) -> dict[str, Any]:
    geology = ctx.get("geology", {})
    temp = ctx.get("temperature_c")
    setting = ctx.get("geothermal_setting") or {}
    permeability = geology.get("permeability_md")
    notes = []
    if temp is not None:
        notes.append(
            f"The recorded temperature of {temp} degC is a property of this well's "
            "history and cannot be transferred to a neighbouring well."
        )
    if setting:
        notes.append(
            f"Regional context for {setting.get('name', 'the area')} indicates a "
            f"typical gradient of {setting.get('typical_gradient_c_per_km')} degC/km, "
            "which is background information only."
        )
    return {
        "summary": (
            "Geological assessment is limited by the absence of formation-level "
            "characterisation. Temperature alone does not indicate deliverability."
        ),
        "facts": _facts(ctx),
        "unknowns": [
            _u(
                "Permeability of the target interval",
                "No core description, well test or production history is held.",
                "Whether the formation can deliver water at rate is unknown, so no "
                "flow rate can be justified.",
                "Request a well test, or a pressure transient test if the well is live.",
            ),
            _u(
                "Net thickness of the productive zone",
                "No log suite or drilling record is available for this well.",
                "The volume of heat in place cannot be estimated.",
                "Obtain the log suite from the original operator.",
            ),
            _u(
                "Natural fracture network",
                "No image log or flow-meter survey exists.",
                "Secondary porosity, which may dominate deliverability, is unquantified.",
                "Run an image log if the well is accessible.",
            ),
        ],
        "suitability_notes": notes,
        "recommended_configurations": ["closed_loop_plus_heat_pump"],
        "permeability_status": (
            f"Formation permeability is recorded as {permeability} mD."
            if permeability is not None
            else "Unknown: no permeability, well test or production data is held, so "
            "deliverability is unassessed."
        ),
        "confidence_notes": "No core, log or test data was available to this agent.",
        "recommended_next_steps": [
            _next_step(
                "Obtain a water chemistry analysis from the original drilling reports",
                "Chemistry drives both corrosion and scaling, which are the most "
                "common causes of geothermal plant underperformance.",
                "high",
            ),
            _next_step(
                "Request any well test or pressure transient data",
                "Deliverability cannot be justified from temperature alone.",
                "high",
            ),
        ],
    }


def _build_integrity_assessment(ctx: dict[str, Any]) -> dict[str, Any]:
    integrity = ctx.get("integrity") or {}
    geology = ctx.get("geology") or {}
    status = integrity.get("status", "unknown")

    scaling = geology.get("scaling_tendency")
    corrosion = geology.get("corrosion_tendency")
    ph = geology.get("water_ph")

    if scaling in ("high", "severe"):
        scaling_risk = "high"
    elif scaling in ("moderate", "medium"):
        scaling_risk = "moderate"
    elif scaling in ("low", "none", "minimal"):
        scaling_risk = "low"
    else:
        scaling_risk = "unknown"

    if corrosion in ("high", "severe"):
        corrosion_risk = "high"
    elif corrosion in ("moderate", "medium"):
        corrosion_risk = "moderate"
    elif corrosion in ("low", "none", "minimal"):
        corrosion_risk = "low"
    elif ph is not None and ph < 5.5:
        corrosion_risk = "high"
    elif ph is not None and ph < 7.0:
        corrosion_risk = "moderate"
    else:
        corrosion_risk = "unknown"

    return {
        "summary": (
            f"Well integrity is recorded as '{status}'. "
            + (
                "This assessment is based on documentation, not on physical inspection."
                if status != "good_condition"
                else "The available records indicate the well is in serviceable condition."
            )
        ),
        "facts": _facts(ctx),
        "unknowns": (
            [
                _u(
                    "Casing corrosion state",
                    "No casing inspection or corrosion log exists.",
                    "Whether the casing can survive thermal cycling is unestablished.",
                    "Commission a wireline casing inspection or caliper survey.",
                ),
                _u(
                    "Wellhead integrity",
                    "The wellhead has not been inspected.",
                    "A re-use scheme depends on a serviceable wellhead and valve stack.",
                    "Inspect the wellhead on any site visit.",
                ),
                _u(
                    "Whether the well is suspended or fully abandoned",
                    "The recorded status does not distinguish the two.",
                    "Cost and programme differ substantially between them.",
                    "Confirm the current status with the operator and the NSTA.",
                ),
            ]
            if status == "unknown"
            else []
        ),
        "reuse_viability": "unknown" if status == "unknown" else "plausible",
        "requires_intervention": status
        in {"abandoned_no_access", "poor_unknown", "partially_mechanical"},
        "corrosion_risk": corrosion_risk,
        "scaling_risk": scaling_risk,
        "recommended_next_steps": [
            _next_step(
                "Recover the completion and casing record from the operator",
                "A records request that determines whether any fieldwork is needed.",
                "critical" if status == "unknown" else "high",
            ),
            _next_step(
                "Commission a wireline casing inspection if the well is accessible",
                "Documentation cannot establish whether the casing will survive "
                "thermal cycling.",
                "high" if status == "unknown" else "medium",
            ),
        ],
        "confidence_notes": (
            "Integrity carries a 20% score weight, second only to thermal. It is "
            "the most valuable thing to verify before any capital commitment. "
            "Ground source heat pumping is established practice generally, but "
            "reuse of an individual legacy wellbore has to be demonstrated at that "
            "well and is not established anywhere on the strength of published "
            "aggregate performance."
        ),
        "recommended_next_steps": [
            _next_step(
                "Recover the completion and casing record from the operator",
                "A records request that may resolve the question without fieldwork.",
                "critical" if status == "unknown" else "high",
            ),
            _next_step(
                "Commission a wireline casing inspection if the well is accessible",
                "Documentation cannot establish whether the casing survives thermal cycling.",
                "high",
            ),
            _next_step(
                "Inspect the wellhead on the first site visit",
                "A re-use scheme depends on a serviceable wellhead and valve stack.",
                "medium",
            ),
        ],
    }


def _build_heat_demand_analysis(ctx: dict[str, Any]) -> dict[str, Any]:
    demand = ctx.get("demand") or {}
    count = demand.get("building_count", 0)
    total = demand.get("total_annual_demand_kwh") or 0.0
    distance = demand.get("nearest_building_distance_m")
    return {
        "summary": (
            f"{count} candidate off-taker(s) were found within "
            f"{demand.get('radius_m', 0)} m, representing {total / 1e6:.2f} GWh of annual "
            f"heat demand. The nearest is {distance:.0f} m away."
            if distance
            else "No heat demand could be matched to this well's location."
        ),
        "facts": _facts(ctx),
        "unknowns": [
            _u(
                "Actual customer willingness to pay",
                "No market sounding or offtake offer exists.",
                "The revenue side of the model is entirely assumed.",
                "Run a market sounding, ideally with an anchor commercial customer.",
            ),
            _u(
                "Whether existing buildings will actually connect",
                "Modelled demand is not a connection commitment.",
                "Annual output and therefore LCOH may be overstated.",
                "Survey the buildings and obtain expressions of interest.",
            ),
            _u(
                "Peak coincident demand across the cluster",
                "Only annual demand is available per address.",
                "Pipe and plant sizing cannot be optimised against the real peak.",
                "Obtain half-hourly demand profiles for candidate off-takers.",
            ),
        ],
        "total_annual_demand_kwh": total or None,
        "nearest_building_distance_m": distance,
        "demand_to_output_ratio": ctx.get("demand_to_output_ratio"),
        "assessment_notes": [
            "Demand figures at this stage are modelled estimates derived from "
            "building attributes, not metered consumption.",
            "A single candidate off-taker would concentrate the entire revenue case, "
            "so the count of off-takers matters as much as the total demand.",
            "Required supply temperature can disqualify a well entirely or require a "
            "heat pump that consumes the margin.",
        ],
        "confidence_notes": "Demand confidence is capped until a survey or offtake is agreed.",
        "recommended_next_steps": [
            _next_step(
                "Run a heat demand survey for buildings within 2 km",
                "Demand carries a 15% score weight and the current figure is modelled, "
                "not measured.",
                "high",
            ),
            _next_step(
                "Obtain an expression of interest or letter of intent from anchor customers",
                "Anchoring on commercial or institutional offtake is what makes a "
                "scheme bankable.",
                "medium",
            ),
        ],
    }


def _build_heat_network_analysis(ctx: dict[str, Any]) -> dict[str, Any]:
    network = ctx.get("network") or {}
    distance = network.get("distance_m")
    length = network.get("pipe_length_m")
    loss_fraction = network.get("loss_fraction")
    return {
        "summary": (
            f"The nearest off-taker is {distance:.0f} m away"
            + (f", implying roughly {length:.0f} m of buried pipe." if length else ".")
            + (
                f" Distribution losses on that route are about {loss_fraction:.0%}."
                if loss_fraction
                else ""
            )
            if distance
            else "No route could be assessed because no demand was matched."
        ),
        "facts": _facts(ctx),
        "unknowns": [
            _u(
                "Ground conditions along the route",
                "No ground investigation has been carried out.",
                "Trench cost and programme cannot be estimated with confidence.",
                "Obtain utility records and a desk-based ground assessment.",
            ),
            _u(
                "Third-party utilities and easements",
                "No utility search has been undertaken.",
                "Diversion or easements could add both cost and months to the programme.",
                "Commission a utility search along the proposed alignment.",
            ),
            _u(
                "Actual route length as opposed to straight-line distance",
                "Only the straight-line distance to the nearest demand is known.",
                "Pipe cost and distribution losses are understated.",
                "Carry out a route survey before the capital estimate is firmed up.",
            ),
        ],
        "estimated_pipe_length_m": length,
        "estimated_loss_fraction": loss_fraction,
        "feasibility_notes": [
            "Beyond roughly 3 km the pipe cost per useful kWh rises steeply and "
            "usually rules a scheme out.",
            "Straight-line distance understates the real route, so both cost and "
            "distribution losses are understated here.",
            "Easements, third-party utilities and landowner agreement are schedule as "
            "much as cost risks.",
        ],
        "alternative_approaches": [
            "Aggregate several wells behind one heat centre",
            "Consider a shared network with an adjacent development",
            "Reduce the network supply temperature so a lower-grade well can serve it",
        ],
        "confidence_notes": "Straight-line distance understates the real pipe route.",
        "recommended_next_steps": [
            _next_step(
                "Carry out a route survey and a utility search",
                "Pipe cost is the dominant capex line once drilling is sunk, and the "
                "survey is what firms it up.",
                "high" if (distance or 0) > 1000 else "medium",
            ),
        ],
    }


def _build_engineering_assessment(ctx: dict[str, Any]) -> dict[str, Any]:
    eng = ctx.get("engineering") or {}
    output_kw = eng.get("thermal_output_kw")

    if output_kw is None:
        summary = (
            "No thermal output could be calculated because the well has no usable "
            "source temperature. Every downstream figure is therefore unknown rather "
            "than zero."
        )
        sensitivity = (
            "No uncertainty band can be given: with no temperature there is nothing to "
            "bound."
        )
    else:
        flow = eng.get("flow_rate_lps")
        swing = eng.get("usable_delta_t_c")
        summary = (
            f"Using {flow} L/s"
            + (f" and a {swing} K usable temperature swing" if swing else "")
            + f", the estimated wellhead output is {output_kw:.0f} kW. This figure is "
            "an ESTIMATE: the flow rate is assumed and no flow test has been performed."
        )
        low = eng.get("thermal_output_low_kw")
        high = eng.get("thermal_output_high_kw")
        if low is not None and high is not None:
            sensitivity = (
                f"The uncertainty band on output is {low:.0f} to {high:.0f} kW, driven "
                "mainly by temperature confidence and the assumed flow rate. Output "
                "scales linearly with flow, so a flow test would narrow this "
                "immediately."
            )
        else:
            sensitivity = "No uncertainty band was produced for this well."

    return {
        "summary": summary,
        "facts": _facts(ctx),
        "unknowns": [
            _u(
                "Achievable sustainable flow rate",
                "No flow test has been performed on this well.",
                "Thermal output scales linearly with flow, so the estimate carries the "
                "full flow uncertainty.",
                "Commission a flow test, or a short-duration interference test if live.",
            ),
            _u(
                "Borehole thermal recovery between cycles",
                "Only a single temperature record exists; there is no time series.",
                "Sustained output over consecutive seasons cannot be predicted.",
                "Log the well repeatedly across at least one heating season.",
            ),
            _u(
                "Long-term reservoir deliverability",
                "No pressure record accompanies the temperature data.",
                "Whether the formation can sustain production is unknown.",
                "Obtain bottom-hole pressure before and after a production period.",
            ),
        ],
        "thermal_output_status": (
            eng.get("thermal_output_status") or EpistemicStatus.ESTIMATE.value
        ),
        "configuration_rationale": eng.get("configuration_rationale") or "",
        "calculation_notes": (
            "All figures in this section were computed in Python by "
            "app.engineering. No value here was produced by a language model."
        ),
        "sensitivity_notes": sensitivity,
    }


def _build_economic_assessment(ctx: dict[str, Any]) -> dict[str, Any]:
    econ = ctx.get("economics") or {}
    lcoh = econ.get("lcoh_p_per_kwh")
    heat_price = econ.get("heat_price_p_per_kwh")

    # Only compare when both figures exist. A margin against an unknown price is
    # not a small margin, it is no information at all.
    margin = (
        (heat_price - lcoh) / heat_price
        if (lcoh is not None and heat_price)
        else None
    )

    if lcoh is None:
        summary = (
            "No cost of heat could be calculated because the thermal model produced "
            "no usable output. The economics of this well are therefore not assessable."
        )
    elif heat_price is None:
        summary = (
            f"LCOH is {lcoh:.1f} p/kWh. No heat price is assumed in this context, so "
            "the figure cannot be compared against a revenue side, and the scheme's "
            "viability is undetermined rather than favourable."
        )
    elif margin is not None and margin < 0:
        summary = (
            f"LCOH of {lcoh:.1f} p/kWh exceeds the assumed heat price of "
            f"{heat_price:.1f} p/kWh. On these inputs the scheme does not work, before "
            "any consideration of risk."
        )
    else:
        summary = (
            f"LCOH of {lcoh:.1f} p/kWh sits {margin:.0%} below the assumed heat price "
            f"of {heat_price:.1f} p/kWh. That margin is an output of the assumptions, "
            "not evidence that the scheme is viable."
        )

    return {
        "summary": summary,
        "facts": _facts(ctx),
        "unknowns": [
            _u(
                "Achievable heat sales price",
                "No market sounding or offtake offer exists for this scheme.",
                "The margin between LCOH and an achievable heat price cannot be confirmed.",
                "Run a market sounding with anchor commercial or institutional buyers.",
            ),
            _u(
                "Final capital cost after site investigation",
                "The estimate is Class 3 and predates any site visit or route survey.",
                "CAPEX and therefore LCOH remain indicative only.",
                "Commission a Class 2 estimate with a site visit and route survey.",
            ),
            _u(
                "Financing structure and cost of debt",
                "Capital structure has not been considered at screening stage.",
                "The equity return cannot be assessed, only the project return.",
                "Confirm the funding structure with the investment committee.",
            ),
            _u(
                "Connection and reinforcement costs",
                "No utility or network operator has been approached.",
                "Connection cost is included only as a unit-rate allowance.",
                "Discuss reinforcement requirements with the network operator.",
            ),
        ],
        "lcoh_vs_heat_price_assessment": (
            "unknown"
            if margin is None
            else ("unfavourable" if margin < 0 else "favourable")
        ),
        "capex_notes": _capex_note(econ.get("capex_gbp")),
        "viability_caveat": (
            "These figures are deterministic arithmetic on estimated inputs. They do "
            "not constitute a statement of commercial viability, which depends on "
            "evidence quality, risk and market testing."
        ),
    }


def _build_regulatory_analysis(ctx: dict[str, Any]) -> dict[str, Any]:
    config = ctx.get("configuration", "")
    regs = ctx.get("requirements") or []
    return {
        "summary": (
            f"For a {config} configuration, {len(regs)} consent(s) or obligation(s) "
            "were identified."
            if regs
            else f"No consent requirements are recorded for a {config} configuration."
        ),
        "facts": _facts(ctx),
        "unknowns": [
            _u(
                "Local planning authority pre-application position",
                "No pre-application consultation has taken place.",
                "Whether the scheme is acceptable in principle is unconfirmed.",
                "Make a formal pre-application enquiry before committing capital.",
            ),
            _u(
                "Environment Agency licensing timeline for this site",
                "No enquiry has been made to the Environment Agency.",
                "The consent programme for an open loop is unbounded.",
                "Make early contact and ask about the reinjection requirement.",
            ),
        ],
        "consent_timeline_months": (
            max((r.get("typical_lead_time_months") or 0) for r in regs) if regs else None
        ),
        "key_obstacles": [
            r["title"] for r in regs if r.get("is_mandatory") and (r.get("typical_lead_time_months") or 0) > 12
        ],
        "recommendation_notes": (
            "Make early pre-application contact before committing capital. A closed "
            "loop avoids the abstraction licence and the discharge consent question "
            "entirely, which is why it is often preferred for a repurposed well."
        ),
    }


def _build_risk_assessment(ctx: dict[str, Any]) -> dict[str, Any]:
    risks = ctx.get("risks") or []
    critical = [r for r in risks if r.get("is_critical")]
    uncertain_critical = [r for r in critical if r.get("uncertainty", 0) > 0.5]
    return {
        "summary": (
            f"{len(risks)} risks were registered across the full taxonomy, of which "
            f"{len(critical)} are critical. Aggregate exposure is "
            f"{ctx.get('aggregate_score', 0):.0%}."
        ),
        "facts": _facts(ctx),
        "unknowns": [
            _u(
                r["title"],
                f"The probability of this risk is not established (uncertainty "
                f"{r.get('uncertainty', 0):.0%}).",
                "The risk cannot be priced or mitigated on the current evidence.",
                r.get("mitigation"),
            )
            for r in uncertain_critical
        ],
        "top_risks": [
            {"category": r["category"], "score": r["risk_score"], "title": r["title"]}
            for r in sorted(risks, key=lambda r: r.get("uncertainty_adjusted_score", 0), reverse=True)[:5]
        ],
        "risk_drivers": [
            r["title"] for r in sorted(risks, key=lambda r: r.get("uncertainty_adjusted_score", 0), reverse=True)[:3]
        ],
        "mitigation_overview": (
            "The highest-value mitigations are the ones that retire the most "
            "uncertainty per pound: a temperature log, then an integrity inspection, "
            "then a demand survey."
        ),
    }


def _build_feasibility_assessment(ctx: dict[str, Any]) -> dict[str, Any]:
    score = ctx.get("feasibility_score", 0.0)
    confidence = ctx.get("confidence_score", 0.0)
    weak = ctx.get("weakest_components") or []
    gaps = ctx.get("data_gaps") or []
    return {
        "summary": (
            f"Feasibility score {score:.0f}/100 with evidence confidence "
            f"{confidence:.0%}. "
            + (
                f"The score is held back mainly by {', '.join(weak)}."
                if weak
                else "No single component is holding the score back."
            )
            + (
                " This number is computed in Python and cannot be influenced by a "
                "language model."
            )
        ),
        "facts": _facts(ctx),
        "unknowns": [
            _u(
                gap,
                "This item is not established by any source held for this well.",
                "It contributes to a reduced confidence score and a discounted ranking.",
                "See the validation plan for the action that would resolve it.",
            )
            for gap in gaps
        ],
        "overall_assessment": (
            "promising" if score >= 60 else "marginal" if score >= 40 else "weak"
        ),
        "confidence_caveat": (
            f"Confidence is {confidence:.0%}. "
            + (
                "This is a good candidate with a well-documented evidence base."
                if confidence >= 0.65
                else "The evidence base is incomplete, so the score should be treated "
                "as provisional."
            )
        ),
        "recommendation": ctx.get("deterministic_recommendation") or Recommendation.DO_NOT_PURSUE.value,
        "recommendation_reasoning": (
            "The recommendation follows from the deterministic score, the confidence "
            "band and the number of critical risks. It was not chosen by a model."
        ),
        "recommended_next_steps": [
            _next_step(
                ctx.get("next_action") or "Resolve the outstanding data gaps.",
                "This is the highest-information action available given the current "
                "evidence base.",
                "critical" if confidence < 0.45 else "high",
            )
        ],
    }


def _build_report(ctx: dict[str, Any]) -> dict[str, Any]:
    score = ctx.get("feasibility_score", 0.0)
    confidence = ctx.get("confidence_score", 0.0)
    recommendation = ctx.get("recommendation", "DO NOT PURSUE")
    thermal = ctx.get("thermal_output_kw")
    gaps = ctx.get("data_gaps") or []

    executive = (
        f"{ctx.get('well_name', 'This well')} scores {score:.0f}/100 on feasibility "
        f"with {confidence:.0%} evidence confidence, giving a recommendation of "
        f"{recommendation}."
    )
    if thermal:
        executive += (
            f" Estimated thermal output is {thermal:.0f} kW at a recorded temperature "
            f"of {ctx.get('source_temperature_c')} degC."
        )
    else:
        executive += (
            " No temperature measurement exists for this well, so no thermal output "
            "can be estimated."
        )
    if gaps:
        executive += f" {len(gaps)} material data gap(s) remain outstanding."
    executive += (
        " This assessment is a screening analysis. It is not a statement of "
        "commercial viability."
    )

    sections = [
        {
            "title": "Executive summary",
            "content": executive,
            "evidence_ids": [],
        },
        {
            "title": "Well characteristics",
            "content": (
                f"{ctx.get('well_name')} at {ctx.get('latitude')}, {ctx.get('longitude')}; "
                f"status {ctx.get('status')}; total depth {ctx.get('total_depth_m')} m; "
                f"formation {ctx.get('formation') or 'not recorded'}."
            ),
            "evidence_ids": [],
        },
        {
            "title": "Temperature assessment",
            "content": (
                f"Recorded temperature {ctx.get('source_temperature_c')} degC "
                f"(status: {ctx.get('temperature_status')}, confidence: "
                f"{ctx.get('temperature_confidence')}). "
                + (
                    "The figure is measured and traceable to a source record."
                    if ctx.get("temperature_status") == "MEASURED"
                    else "The figure is an estimate and is treated as such throughout."
                )
            ),
            "evidence_ids": [],
        },
        {
            "title": "Geology",
            "content": (
                ctx.get("geology_summary")
                or "No formation-level characterisation is available for this well."
            ),
            "evidence_ids": [],
        },
        {
            "title": "Well integrity",
            "content": ctx.get("integrity_summary") or "Integrity has not been assessed.",
            "evidence_ids": [],
        },
        {
            "title": "Geothermal configuration",
            "content": (
                f"Recommended configuration: {ctx.get('configuration')}. "
                f"{ctx.get('configuration_rationale', '')}"
            ),
            "evidence_ids": [],
        },
        {
            "title": "Thermal output",
            "content": (
                f"Estimated wellhead output {thermal:.0f} kW (status: ESTIMATE, no flow "
                "test). Network losses and annual production are modelled in "
                "app.engineering with a full calculation trace."
            )
            if thermal
            else "Not assessable: no temperature measurement exists.",
            "evidence_ids": [],
        },
        {
            "title": "Heat demand",
            "content": ctx.get("demand_summary") or "No heat demand has been matched.",
            "evidence_ids": [],
        },
        {
            "title": "Heat network",
            "content": ctx.get("network_summary") or "No network route has been assessed.",
            "evidence_ids": [],
        },
        {
            "title": "CAPEX",
            "content": (
                f"Estimated capital cost GBP {ctx.get('capex_gbp'):,.0f} (Class 3 "
                "estimate, ~20% contingency)."
                if ctx.get("capex_gbp")
                else "Not estimated."
            ),
            "evidence_ids": [],
        },
        {
            "title": "OPEX",
            "content": (
                f"Estimated annual operating cost GBP {ctx.get('opex_gbp_per_year'):,.0f}."
                if ctx.get("opex_gbp_per_year")
                else "Not estimated."
            ),
            "evidence_ids": [],
        },
        {
            "title": "LCOH",
            "content": (
                f"Levelised cost of heat {ctx.get('lcoh_p_per_kwh'):.1f} p/kWh against an "
                f"assumed heat price of {ctx.get('heat_price_p_per_kwh')} p/kWh."
                if ctx.get("lcoh_p_per_kwh")
                else "Not calculated."
            ),
            "evidence_ids": [],
        },
        {
            "title": "NPV",
            "content": (
                f"Net present value GBP {ctx.get('npv_gbp'):,.0f} at the assumed discount rate."
                if ctx.get("npv_gbp") is not None
                else "Not calculated."
            ),
            "evidence_ids": [],
        },
        {
            "title": "IRR",
            "content": (
                f"Internal rate of return {ctx.get('irr_pct'):.1f}%."
                if ctx.get("irr_pct") is not None
                else "No valid IRR exists for the modelled cash flows."
            ),
            "evidence_ids": [],
        },
        {
            "title": "Risks",
            "content": ctx.get("risk_summary") or "",
            "evidence_ids": [],
        },
        {
            "title": "Regulatory considerations",
            "content": ctx.get("regulatory_summary") or "",
            "evidence_ids": [],
        },
        {
            "title": "Data gaps",
            "content": (
                "\n".join(f"- {g}" for g in gaps) if gaps else "No material data gaps."
            ),
            "evidence_ids": [],
        },
        {
            "title": "Validation plan",
            "content": ctx.get("validation_plan") or "",
            "evidence_ids": [],
        },
        {
            "title": "Final recommendation",
            "content": (
                f"{recommendation}. {ctx.get('recommendation_reasoning', '')}\n\n"
                f"Next action: {ctx.get('next_action', '')}"
            ),
            "evidence_ids": [],
        },
    ]

    return {
        "executive_summary": executive,
        "sections": sections,
        "overall_recommendation": recommendation,
        "disclaimers": [
            "This report is a screening analysis produced from desk study and public "
            "records. It is not a statement of commercial viability.",
            "Thermal output is estimated. No flow test has been performed unless "
            "explicitly stated otherwise.",
            "Financial figures are deterministic calculations on estimated inputs and "
            "inherit their uncertainty.",
        ],
    }


#: Maps a schema name to the function that builds mock output for it.
_MOCK_BUILDERS: dict[str, Any] = {
    "WellDataInterpretation": _build_well_data_interpretation,
    "GeothermalInterpretation": _build_geothermal_interpretation,
    "WellIntegrityAssessment": _build_integrity_assessment,
    "HeatDemandAnalysis": _build_heat_demand_analysis,
    "HeatNetworkAnalysis": _build_heat_network_analysis,
    "EngineeringAssessment": _build_engineering_assessment,
    "EconomicAssessment": _build_economic_assessment,
    "RegulatoryAnalysis": _build_regulatory_analysis,
    "RiskAssessmentSummary": _build_risk_assessment,
    "FeasibilityAssessment": _build_feasibility_assessment,
    "ReportOutput": _build_report,
}


def get_llm_provider(prefer_mock: bool = False) -> LLMProvider:
    """Resolve the provider to use.

    Falls back to the deterministic mock when no API key is configured or when
    the caller explicitly asks for it. Never raises for a missing key: the
    platform must remain usable without one.
    """
    if prefer_mock or not settings.llm_available:
        return MockProvider()
    try:
        return AnthropicProvider()
    except LLMError:
        return MockProvider()

