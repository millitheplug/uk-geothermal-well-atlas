"""Tests for the agent layer.

The important assertions here are negative ones: that the discipline gate
actually catches the failures it claims to catch. A test suite that only checks
the happy path would pass even if every guard were removed.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from app.agents.agents import FeasibilityAgent
from app.agents.base import enforce_discipline
from app.agents.llm import (
    AnthropicProvider,
    LLMError,
    MimoProvider,
    MockProvider,
    get_llm_provider,
)
from app.agents.orchestrator import (
    AgentOrchestrator,
    _environmental_summary,
    _sensitivity_summary,
)
from app.agents.prompts import REQUIRED_REPORT_SECTIONS, system_prompt_for
from app.agents.schemas import (
    AGENT_NAMES,
    EconomicAssessment,
    EngineeringAssessment,
    FactRecord,
    FeasibilityAssessment,
    ReportOutput,
    WellDataInterpretation,
)
from app.core.enums import EpistemicStatus, Recommendation
from app.engineering.pipeline import WellInputs, assess_well


def _good_well(**overrides) -> WellInputs:
    defaults = dict(
        well_id="AGENT-001",
        well_name="Agent Test Well",
        latitude=53.4,
        longitude=-2.5,
        status="producing",
        original_purpose="gas",
        operator="Test Oil",
        licence="UK-OG-1",
        drilling_year=1985,
        total_depth_m=2000.0,
        tvd_m=1950.0,
        formation="Millstone Grit",
        has_casing_record=True,
        temperature_c=62.0,
        temperature_depth_m=1950.0,
        temperature_status=EpistemicStatus.MEASURED.value,
        temperature_confidence="high",
        temperature_measurements_c=[61.0, 62.0, 63.0],
        temperature_sources=["nsta", "bgs"],
        source_reliabilities=[0.92, 0.88],
        integrity_status="good_condition",
        annual_demand_kwh=6_000_000.0,
        peak_demand_kw=1200.0,
        number_of_buildings=30,
        nearest_building_distance_m=600.0,
        demand_confidence="high",
        required_supply_temperature_c=70.0,
        existing_network=True,
    )
    defaults.update(overrides)
    return WellInputs(**defaults)


def _context(**overrides) -> dict:
    ctx = {
        "well": {
            "well_id": "AGENT-001",
            "well_name": "Agent Test Well",
            "status": "producing",
            "operator": "Test Oil",
            "drilling_year": 1985,
            "total_depth_m": 2000.0,
            "tvd_m": 1950.0,
            "formation": "Millstone Grit",
            "latitude": 53.4,
            "longitude": -2.5,
        },
        "temperatures": [{"temperature_c": 62.0, "depth_m": 1950.0}],
        "integrity": {"status": "good_condition"},
        "geology": {"water_ph": 7.1, "water_salinity_ppt": 25.0},
        "demand": {
            "building_count": 30,
            "radius_m": 2000,
            "total_annual_demand_kwh": 6_000_000.0,
            "nearest_building_distance_m": 600.0,
        },
        "network": {"distance_m": 600.0, "pipe_length_m": 700.0, "loss_fraction": 0.03},
        "regulatory_requirements": [
            {"title": "Abstraction licence", "is_mandatory": True,
             "typical_lead_time_months": 18}
        ],
    }
    ctx.update(overrides)
    return ctx


class TestProviderSelection:
    def test_mock_used_when_no_api_key(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ai_provider", "auto", raising=False)
        monkeypatch.setattr(settings, "mimo_api_key", None, raising=False)
        monkeypatch.setattr(settings, "anthropic_api_key", None, raising=False)
        assert isinstance(get_llm_provider(), MockProvider)

    def test_mock_used_when_explicitly_requested(self):
        assert isinstance(get_llm_provider(prefer_mock=True), MockProvider)

    def test_provider_name_is_stable(self):
        assert MockProvider().name == "mock"
        assert MimoProvider.__name__ == "MimoProvider"

    def test_mimo_used_when_key_set(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ai_provider", "auto", raising=False)
        monkeypatch.setattr(settings, "mimo_api_key", "k", raising=False)
        monkeypatch.setattr(settings, "anthropic_api_key", None, raising=False)
        assert isinstance(get_llm_provider(), MimoProvider)

    def test_anthropic_used_when_only_anthropic_key(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ai_provider", "auto", raising=False)
        monkeypatch.setattr(settings, "mimo_api_key", None, raising=False)
        monkeypatch.setattr(settings, "anthropic_api_key", "k", raising=False)
        assert isinstance(get_llm_provider(), AnthropicProvider)

    def test_explicit_provider_never_silently_substituted(self, monkeypatch):
        """AI_PROVIDER=anthropic with only a MiMo key must not call MiMo."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "ai_provider", "anthropic", raising=False)
        monkeypatch.setattr(settings, "mimo_api_key", "k", raising=False)
        monkeypatch.setattr(settings, "anthropic_api_key", None, raising=False)
        assert isinstance(get_llm_provider(), MockProvider)

    def test_ai_provider_mock_forces_deterministic_even_with_keys(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ai_provider", "mock", raising=False)
        monkeypatch.setattr(settings, "mimo_api_key", "k", raising=False)
        monkeypatch.setattr(settings, "anthropic_api_key", "k", raising=False)
        assert isinstance(get_llm_provider(), MockProvider)


class TestMimoProvider:
    """MiMo speaks the OpenAI wire format but shares the validation contract."""

    class _Payload(BaseModel):
        answer: str

    def _configure(self, monkeypatch) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "mimo_api_key", "test-key", raising=False)
        monkeypatch.setattr(settings, "mimo_base_url", "https://mimo.test/v1", raising=False)
        monkeypatch.setattr(settings, "mimo_model", "mimo-v2.6-flash", raising=False)
        monkeypatch.setattr(settings, "ai_max_tokens", 4096, raising=False)
        monkeypatch.setattr(settings, "ai_temperature", 0.0, raising=False)

    def _provider(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return MimoProvider(client=client)

    def test_requires_a_key(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "mimo_api_key", None, raising=False)
        with pytest.raises(LLMError, match="MIMO_API_KEY"):
            MimoProvider()

    def test_parses_submit_tool_call(self, monkeypatch):
        self._configure(monkeypatch)
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["api_key"] = request.headers.get("api-key")
            body = json.loads(request.content)
            seen["thinking"] = body.get("thinking")
            seen["temperature"] = body.get("temperature")
            return httpx.Response(
                200,
                json={
                    "model": "mimo-v2.6-flash",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "type": "function",
                                        "function": {
                                            "name": "submit",
                                            "arguments": json.dumps({"answer": "42"}),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

        response = self._provider(handler).complete(
            system="sys", user="usr", schema=self._Payload
        )
        assert seen["url"] == "https://mimo.test/v1/chat/completions"
        assert seen["api_key"] == "test-key"
        # Thinking must be disabled or the server overrides temperature to 1.0.
        assert seen["thinking"] == {"type": "disabled"}
        assert seen["temperature"] == 0.0
        assert json.loads(response.text) == {"answer": "42"}
        assert response.provider == "mimo"
        assert response.input_tokens == 10
        assert response.output_tokens == 5

    def test_falls_back_to_fenced_json_content(self, monkeypatch):
        self._configure(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": '```json\n{"answer": "7"}\n```',
                            },
                        }
                    ],
                },
            )

        response = self._provider(handler).complete(
            system="sys", user="usr", schema=self._Payload
        )
        assert json.loads(response.text) == {"answer": "7"}

    def test_http_error_raises(self, monkeypatch):
        self._configure(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        with pytest.raises(LLMError, match="HTTP 429"):
            self._provider(handler).complete(
                system="sys", user="usr", schema=self._Payload
            )

    def test_token_limit_raises(self, monkeypatch):
        self._configure(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"choices": [{"finish_reason": "length", "message": {}}]}
            )

        with pytest.raises(LLMError, match="token limit"):
            self._provider(handler).complete(
                system="sys", user="usr", schema=self._Payload
            )

    def test_no_choices_raises(self, monkeypatch):
        self._configure(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        with pytest.raises(LLMError, match="no choices"):
            self._provider(handler).complete(
                system="sys", user="usr", schema=self._Payload
            )

    def test_complete_model_validates_json_like_every_provider(self, monkeypatch):
        """The retry-and-fail contract is inherited, not re-implemented."""
        self._configure(monkeypatch)
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            # A list where the schema demands a string: validation must fail on
            # the first attempt and the retry must succeed.
            content = (
                json.dumps({"answer": "42"})
                if calls["n"] > 1
                else json.dumps({"answer": ["not", "a", "string"]})
            )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": content},
                        }
                    ]
                },
            )

        result, _ = self._provider(handler).complete_model(
            system="sys", user="usr", schema=self._Payload
        )
        assert result.answer == "42"
        assert calls["n"] == 2


class TestSchemaValidation:
    def test_fact_without_source_is_rejected_by_schema(self):
        """Rule 8 enforced at the schema level, not only in the gate."""
        with pytest.raises(ValidationError, match="must cite a source"):
            WellDataInterpretation(
                summary="x",
                data_quality="partial",
                well_name_confirmed=True,
                facts=[
                    {
                        "statement": "The well was drilled in 1985.",
                        "fact_type": "FACT",
                        "source": None,
                    }
                ],
            )

    def test_assumption_needs_no_source(self):
        result = WellDataInterpretation(
            summary="x",
            data_quality="partial",
            well_name_confirmed=True,
            facts=[
                {
                    "statement": "Flow rate is assumed to be 20 L/s.",
                    "fact_type": "ASSUMPTION",
                    "source": None,
                }
            ],
        )
        assert result.facts[0].source is None

    def test_unknown_needs_no_source(self):
        result = WellDataInterpretation(
            summary="x",
            data_quality="partial",
            well_name_confirmed=True,
            facts=[
                {
                    "statement": "Casing condition is unknown.",
                    "fact_type": "UNKNOWN",
                    "source": None,
                }
            ],
        )
        assert result.facts[0].fact_type == "UNKNOWN"

    def test_measured_claim_requires_source(self):
        with pytest.raises(ValidationError):
            WellDataInterpretation(
                summary="x",
                data_quality="good",
                well_name_confirmed=True,
                facts=[
                    {"statement": "Temperature is 62 degC.", "fact_type": "MEASURED",
                     "source": None}
                ],
            )

    def test_feasibility_agent_cannot_return_a_free_form_recommendation(self):
        with pytest.raises(ValidationError):
            FeasibilityAssessment(
                summary="x",
                overall_assessment="promising",
                recommendation="PROBABLY FINE",
                recommendation_reasoning="x",
                confidence_caveat="x",
            )

    def test_every_fact_type_literal_is_accepted(self):
        for fact_type in ("FACT", "MEASURED", "DERIVED", "ESTIMATE", "ASSUMPTION", "UNKNOWN"):
            WellDataInterpretation(
                summary="x",
                data_quality="partial",
                well_name_confirmed=True,
                facts=[{"statement": "s", "fact_type": fact_type, "source": "src"}],
            )


class TestDisciplineGate:
    def _valid_interp(self, summary: str):
        return WellDataInterpretation(
            summary=summary,
            data_quality="partial",
            well_name_confirmed=True,
            facts=[
                {"statement": "Drilled 1985.", "fact_type": "FACT", "source": "nsta"}
            ],
        )

    def _unsourced_interp(self, statement: str = "The well is 2000 m deep."):
        """An output carrying a claim with no source.

        Built with ``model_construct`` from raw dicts because the gate has to cope
        with output that never went through the schema validator - which is the
        first line of defence, exercised separately in TestSchemaValidation. This
        exercises the second.
        """
        return WellDataInterpretation.model_construct(
            summary="x",
            data_quality="partial",
            well_name_confirmed=True,
            confidence=0.5,
            facts=[
                {
                    "statement": statement,
                    "fact_type": "ESTIMATE",
                    "source": None,
                }
            ],
            unknowns=[],
            recommended_next_steps=[],
        )

    def test_clean_output_passes(self):
        _, violations = enforce_discipline(
            "WellDataAgent", self._valid_interp("A normal summary.")
        )
        assert not violations

    def test_commercial_viability_claim_is_rejected(self):
        """The single most important rule: no viability claims."""
        _, violations = enforce_discipline(
            "EconomicAgent", self._valid_interp("This scheme is commercially viable.")
        )
        assert any(v.rule == "no_guaranteed_viability" for v in violations)
        assert any(v.action == "rejected" for v in violations)

    def test_guaranteed_language_is_rejected(self):
        for phrase in ("guaranteed return", "risk-free", "certain return"):
            _, violations = enforce_discipline(
                "EconomicAgent", self._valid_interp(f"The outcome is {phrase}.")
            )
            assert any(v.rule == "no_guaranteed_viability" for v in violations), phrase

    def test_profitability_claim_is_rejected(self):
        _, violations = enforce_discipline(
            "EconomicAgent", self._valid_interp("The project will be profitable.")
        )
        assert violations

    def test_proven_technology_flagged_on_narrowing_context(self):
        """A general statement about ground source heat pumps is legitimate.

        The same phrase asserted of this specific well is not, because the well
        has no track record. The check looks for a narrowing reference ("this
        well", "this scheme") alongside the phrase.
        """
        _, no_violations = enforce_discipline(
            "EconomicAgent",
            self._valid_interp(
                "Closed-loop ground source heat pumps are proven technology in "
                "general, though this particular wellbore is not."
            ),
        )
        assert not any(v.rule == "no_guaranteed_viability" for v in no_violations)

        _, violations = enforce_discipline(
            "EconomicAgent",
            self._valid_interp("The scheme at this well is proven technology."),
        )
        assert any(v.rule == "no_guaranteed_viability" for v in violations)

    def test_agent_prompt_mentions_proven_technology_only_in_a_general_way(self):
        """The mock agent's own output must pass the gate it is subject to.

        This is the test that catches a self-inconsistency: if the mock provider
        generated prose containing a narrowing phrase, every orchestration run
        would report WellDataAgent as rejected.
        """
        assessment = assess_well(_good_well())
        orchestrator = AgentOrchestrator(prefer_mock=True)
        result = orchestrator.run(assessment, _context())
        assert "WellDataAgent" in result.agent_runs
        assert result.agent_runs["WellDataAgent"].accepted

    def test_mismatched_recommendation_is_rejected(self):
        output = FeasibilityAssessment(
            summary="x",
            overall_assessment="strong",
            recommendation=Recommendation.HIGH_PRIORITY,
            recommendation_reasoning="x",
            confidence_caveat="x",
        )
        _, violations = enforce_discipline(
            "FeasibilityAgent",
            output,
            expected_recommendation=Recommendation.DO_NOT_PURSUE,
        )
        assert any(v.rule == "recommendation_must_be_deterministic" for v in violations)
        assert any(v.action == "rejected" for v in violations)

    def test_matched_recommendation_passes(self):
        output = FeasibilityAssessment(
            summary="x",
            overall_assessment="marginal",
            recommendation=Recommendation.LOW_PRIORITY,
            recommendation_reasoning="x",
            confidence_caveat="x",
        )
        _, violations = enforce_discipline(
            "FeasibilityAgent",
            output,
            expected_recommendation=Recommendation.LOW_PRIORITY,
        )
        assert not any(v.action == "rejected" for v in violations)

    def test_no_expectation_supplied_means_no_comparison(self):
        """The gate cannot invent an expectation; without one it only checks prose."""
        output = FeasibilityAssessment(
            summary="x",
            overall_assessment="strong",
            recommendation=Recommendation.HIGH_PRIORITY,
            recommendation_reasoning="x",
            confidence_caveat="x",
        )
        _, violations = enforce_discipline("FeasibilityAgent", output)
        assert not any(v.rule == "recommendation_must_be_deterministic" for v in violations)

    def test_status_upgrade_is_reverted(self):
        """An agent may not turn an ESTIMATE into a MEASURED."""
        output = EngineeringAssessment(
            summary="x",
            thermal_output_status=EpistemicStatus.MEASURED.value,
            configuration_rationale="x",
            calculation_notes="x",
            sensitivity_notes="x",
        )
        fixed, violations = enforce_discipline(
            "EngineeringAgent",
            output,
            expected_thermal_status=EpistemicStatus.ESTIMATE.value,
        )
        assert fixed.thermal_output_status == EpistemicStatus.ESTIMATE.value
        assert any(v.rule == "no_status_upgrade" for v in violations)
        assert any(v.action == "reverted" for v in violations)

    def test_downgrade_is_allowed(self):
        output = EngineeringAssessment(
            summary="x",
            thermal_output_status=EpistemicStatus.UNKNOWN.value,
            configuration_rationale="x",
            calculation_notes="x",
            sensitivity_notes="x",
        )
        fixed, violations = enforce_discipline(
            "EngineeringAgent",
            output,
            expected_thermal_status=EpistemicStatus.MEASURED.value,
        )
        assert fixed.thermal_output_status == EpistemicStatus.UNKNOWN.value
        assert not any(v.rule == "no_status_upgrade" for v in violations)

    def test_missing_source_is_relabelled_not_fatal(self):
        """A repairable defect is corrected rather than failing the run."""
        fixed, violations = enforce_discipline("WellDataAgent", self._unsourced_interp())
        assert fixed.facts[0].fact_type == "ASSUMPTION"
        assert any(v.action == "relabelled as ASSUMPTION" for v in violations)
        assert not any(v.action == "rejected" for v in violations)

    def test_unparseable_fact_is_dropped_and_reported(self):
        output = WellDataInterpretation.model_construct(
            summary="x",
            data_quality="partial",
            well_name_confirmed=True,
            confidence=0.5,
            facts=[{"not": "a fact record"}],
            unknowns=[],
            recommended_next_steps=[],
        )
        fixed, violations = enforce_discipline("WellDataAgent", output)
        assert fixed.facts == []
        assert any(v.rule == "malformed_fact" for v in violations)
        assert any(v.action == "dropped" for v in violations)

    def test_validated_facts_are_repaired_in_place(self):
        """A schema-valid output with a hand-relabelled unsourced claim.

        FactRecord's own validator requires a source for ESTIMATE, so the only
        way to reach this state is to bypass validation. The gate must still
        catch it.
        """
        fact = FactRecord(
            statement="The well is 2000 m deep.",
            fact_type="ASSUMPTION",
            source=None,
        )
        output = WellDataInterpretation(
            summary="x",
            data_quality="partial",
            well_name_confirmed=True,
            facts=[fact],
        )
        # Downgrade-then-check: the gate only acts on non-assumption labels, so
        # an already-labelled ASSUMPTION is left alone.
        _, violations = enforce_discipline("WellDataAgent", output)
        assert not any(v.action == "rejected" for v in violations)

    def test_corrections_are_recorded_in_the_output(self):
        fixed, _ = enforce_discipline("WellDataAgent", self._unsourced_interp())
        assert "Corrected by the discipline gate" in (fixed.confidence_notes or "")


class _RogueProvider:
    """A provider that returns a recommendation the engine did not produce.

    Deliberately hostile. Rule 6 exists so that the model cannot change the
    recommendation however confidently it asserts one, so the test provider
    asserts one very confidently.
    """

    def __init__(self, recommendation: str) -> None:
        self.recommendation = recommendation

    def complete_model(self, *, system, user, schema, max_tokens=None):
        output = schema.model_validate(
            {
                "summary": "The model disagrees with the deterministic engine.",
                "overall_assessment": "strong",
                "recommendation": self.recommendation,
                "recommendation_reasoning": "The model would like to pursue this well.",
                "confidence_caveat": "x",
            }
        )
        return output, "rogue mock response"


class TestRecommendationIsWiredIntoTheGate:
    """Rule 6 only holds if the agent hands its expectation to the gate.

    `FeasibilityAgent` once defined `run` twice. Python keeps the last
    definition, so the one that set `expected_recommendation` was dead code and
    the rule silently never fired — the agent could have returned any
    recommendation it liked.

    These drive the agent rather than calling `enforce_discipline` directly,
    because the gate passing in isolation is precisely what hid the bug.
    """

    def test_agent_supplies_the_deterministic_recommendation(self):
        agent = FeasibilityAgent(llm=_RogueProvider(Recommendation.HIGH_PRIORITY.value))
        run = agent.run({**_context(), "recommendation": Recommendation.DO_NOT_PURSUE.value})
        assert any(v.rule == "recommendation_must_be_deterministic" for v in run.violations), (
            run.violations
        )

    def test_agent_does_not_flag_a_model_that_agrees(self):
        agent = FeasibilityAgent(llm=_RogueProvider(Recommendation.LOW_PRIORITY.value))
        run = agent.run({**_context(), "recommendation": Recommendation.LOW_PRIORITY.value})
        assert not any(v.action == "rejected" for v in run.violations), run.violations

    def test_no_comparison_is_made_when_the_engine_has_no_verdict(self):
        """An unscored well must not be rejected for disagreeing with nothing."""
        agent = FeasibilityAgent(llm=_RogueProvider(Recommendation.HIGH_PRIORITY.value))
        run = agent.run({**_context(), "recommendation": None})
        assert not any(
            v.rule == "recommendation_must_be_deterministic" for v in run.violations
        ), run.violations


class TestPrompts:
    def test_all_eleven_agents_have_prompts(self):
        assert len(AGENT_NAMES) == 11
        for name in AGENT_NAMES:
            assert system_prompt_for(name), name

    def test_rules_block_is_in_every_prompt(self):
        for name in AGENT_NAMES:
            prompt = system_prompt_for(name)
            assert "NEVER INVENT DATA" in prompt
            assert "NEVER CLAIM COMMERCIAL VIABILITY" in prompt
            assert "NEVER PERFORM DETERMINISTIC CALCULATIONS" in prompt
            assert "NEVER SET THE FEASIBILITY SCORE" in prompt

    def test_domain_primer_is_included(self):
        prompt = system_prompt_for("EconomicAgent")
        assert "UK onshore geothermal" in prompt
        assert "Environment Agency" in prompt

    def test_twenty_one_report_sections_required(self):
        # Nineteen from the original spec, plus Environmental considerations
        # and Sensitivity analysis, which the first pass folded into other
        # sections and which are decision-relevant enough to stand alone.
        assert len(REQUIRED_REPORT_SECTIONS) == 21


class TestOrchestration:
    def _run(self, well=None, ctx=None):
        assessment = assess_well(well or _good_well())
        orch = AgentOrchestrator(prefer_mock=True)
        return orch, assessment, orch.run(assessment, ctx or _context())

    def test_runs_all_eleven_agents(self):
        _, _, result = self._run()
        assert set(result.agent_runs) == set(AGENT_NAMES)
        assert len(result.agent_runs) == 11

    def test_all_agents_produce_validated_output(self):
        _, _, result = self._run()
        for name, run in result.agent_runs.items():
            assert run.output is not None, name
            assert run.accepted, f"{name}: {run.violations}"

    def test_mock_provider_is_flagged(self):
        _, _, result = self._run()
        assert result.provider_name == "mock"
        assert result.to_dict()["is_mock"] is True

    def test_report_is_produced(self):
        _, _, result = self._run()
        assert isinstance(result.report, ReportOutput)
        assert result.executive_summary
        assert result.report_markdown

    def test_report_covers_all_required_sections(self):
        _, _, result = self._run()
        titles = {s.title for s in result.report.sections}
        for required in REQUIRED_REPORT_SECTIONS:
            assert required in titles, required

    def test_report_sections_are_in_spec_order(self):
        _, _, result = self._run()
        titles = [s.title.strip() for s in result.report.sections]
        expected = [t for t in REQUIRED_REPORT_SECTIONS if t in set(titles)]
        assert titles == expected

    def test_environmental_section_names_the_screened_configuration(self):
        """Whether the scheme abstracts groundwater is decision-relevant.

        The first version read the configuration from the agent context, which
        does not carry it at enrichment time, so the sentence never fired and
        the section reported designations while staying silent on the one
        environmental fact that most changes the consenting route.
        """
        assessment = assess_well(_good_well())
        env = _environmental_summary(assessment, {}).lower()

        if "open" in assessment.configuration:
            assert "open-loop" in env
        else:
            assert "closed-loop" in env

    def test_environmental_section_refuses_to_read_absence_as_clearance(self):
        """No recorded constraint must not be reported as no constraint."""
        assessment = assess_well(_good_well())
        env = _environmental_summary(assessment, {}).lower()
        assert "not a finding that no constraint applies" in env

    def test_sensitivity_section_reports_assumptions_without_recalculating(self):
        """Sensitivity must name the drivers, not fabricate a spread."""
        assessment = assess_well(_good_well())
        summary = _sensitivity_summary(
            {"calculation_trace": assessment.calculation_trace.get("traces", [])}
        )
        assert "single scenario" in summary
        assert "Monte Carlo simulation is not implemented" in summary

    def test_report_recommendation_is_deterministic(self):
        assessment = assess_well(_good_well())
        _, _, result = self._run(well=_good_well())
        assert str(result.report.overall_recommendation) == assessment.recommendation

    def test_report_contains_the_screening_disclaimer(self):
        _, _, result = self._run()
        assert any(
            "not a statement of commercial viability" in d
            for d in result.report.disclaimers
        )

    def test_report_does_not_claim_viability(self):
        _, _, result = self._run()
        text = result.report_markdown.lower()
        for phrase in ("commercially viable", "risk-free", "guaranteed return"):
            assert phrase not in text, phrase

    def test_stages_are_recorded(self):
        _, _, result = self._run()
        assert result.stages_completed

    def test_output_is_json_serialisable(self):
        import json

        _, _, result = self._run()
        json.dumps(result.to_dict())

    def test_deterministic_results_are_untouched_by_agents(self):
        """The core guarantee: agents cannot change a score."""
        assessment = assess_well(_good_well())
        orch = AgentOrchestrator(prefer_mock=True)
        before = (
            assessment.feasibility_score,
            assessment.lcoh_p_per_kwh,
            assessment.npv_gbp,
            assessment.recommendation,
        )
        orch.run(assessment, _context())
        after = (
            assessment.feasibility_score,
            assessment.lcoh_p_per_kwh,
            assessment.npv_gbp,
            assessment.recommendation,
        )
        assert before == after

    def test_report_can_be_skipped(self):
        _, _, result = self._run()
        assessment = assess_well(_good_well())
        orch = AgentOrchestrator(prefer_mock=True)
        without = orch.run(assessment, _context(), include_report=False)
        assert "ReportAgent" not in without.agent_runs
        assert without.report is None

    def test_agent_failure_does_not_abort_the_run(self):
        """A provider error on one agent must not lose the rest."""

        class BrokenProvider(MockProvider):
            name = "broken"

            def complete(self, *, system, user, schema, max_tokens=None):
                if schema is WellDataInterpretation:
                    raise LLMError("simulated provider outage")
                return super().complete(system=system, user=user, schema=schema)

        assessment = assess_well(_good_well())
        orch = AgentOrchestrator(llm=BrokenProvider())
        result = orch.run(assessment, _context())

        assert "WellDataAgent" not in result.agent_runs
        assert len(result.agent_runs) == 10
        assert any(v.rule == "provider_error" for v in result.violations)
        # The deterministic result is still complete.
        assert assessment.feasibility_score > 0


class TestReportRendering:
    """``_run`` is defined on TestOrchestration; reuse it via the class itself."""

    _run = TestOrchestration._run

    def test_markdown_has_a_heading_per_section(self):
        _, _, result = self._run()
        for section in result.report.sections:
            assert f"## {section.title}" in result.report_markdown

    def test_markdown_includes_disclaimers(self):
        _, _, result = self._run()
        assert "### Disclaimers" in result.report_markdown

    def test_markdown_does_not_duplicate_the_executive_summary_heading(self):
        _, _, result = self._run()
        assert result.report_markdown.count("## Executive summary") == 1


def _report_section(markdown: str, title: str) -> str:
    """The body of one ``##`` section, so an assertion cannot leak into the next."""
    body, active = [], False
    for line in markdown.splitlines():
        if line.startswith("## "):
            active = line.strip() == f"## {title}"
            continue
        if active:
            body.append(line)
    return "\n".join(body).strip()


class TestEconomicSectionsReportWhatWasComputed:
    """The economic sections read from the agent context, not the assessment.

    `_enrich_context` copies forty-odd fields off the assessment but omitted
    capex, opex, LCOH, NPV and IRR, so all five sections rendered their absent
    wording for figures the pipeline had computed. The report then contradicted
    itself: the final recommendation quoted the very LCOH that the LCOH section
    claimed did not exist. Understating rather than overstating, but wrong.
    """

    _run = TestOrchestration._run

    def test_enriched_context_carries_the_economics(self):
        """The root cause: the values never reached any of the readers."""
        assessment = assess_well(_good_well())
        ctx = AgentOrchestrator(prefer_mock=True)._enrich_context(assessment, _context())
        for key in ("capex_gbp", "opex_gbp_per_year", "lcoh_p_per_kwh", "npv_gbp", "irr_pct"):
            assert key in ctx, key
            assert ctx[key] == getattr(assessment, key), key

    def test_capex_section_shows_the_computed_figure(self):
        _, assessment, result = self._run()
        section = _report_section(result.report_markdown, "CAPEX")
        assert f"GBP {assessment.capex_gbp:,.0f}" in section
        assert "Not estimated." not in section

    def test_opex_section_shows_the_computed_figure(self):
        _, assessment, result = self._run()
        section = _report_section(result.report_markdown, "OPEX")
        assert f"GBP {assessment.opex_gbp_per_year:,.0f}" in section
        assert "Not estimated." not in section

    def test_lcoh_section_shows_the_computed_figure(self):
        _, assessment, result = self._run()
        section = _report_section(result.report_markdown, "LCOH")
        assert f"{assessment.lcoh_p_per_kwh:.1f} p/kWh" in section
        assert "Not calculated." not in section

    def test_npv_section_shows_the_computed_figure(self):
        _, assessment, result = self._run()
        section = _report_section(result.report_markdown, "NPV")
        assert f"GBP {assessment.npv_gbp:,.0f}" in section
        assert "Not calculated." not in section

    def test_irr_section_shows_the_computed_figure(self):
        _, assessment, result = self._run()
        section = _report_section(result.report_markdown, "IRR")
        assert f"{assessment.irr_pct:.1f}%" in section
        assert "No valid IRR exists" not in section

    def test_the_assumed_heat_price_is_rendered_as_a_number(self):
        """It lives under `parameters["values"]`, not at the top level.

        Reading it top-level yields None and the LCOH sentence prints
        "None p/kWh", which is worse than quoting no figure at all.
        """
        _, assessment, result = self._run()
        heat_price = assessment.parameters["values"]["heat_price_p_per_kwh"]
        assert "None p/kWh" not in result.report_markdown
        assert f"assumed heat price of {heat_price} p/kWh" in result.report_markdown


class TestMockProviderBehaviour:
    def test_mock_derives_content_from_the_context(self):
        """The mock must produce genuinely useful output, not filler."""
        import json

        provider = MockProvider()
        response = provider.complete(
            system="s",
            user="CONTEXT_JSON:\n"
            + json.dumps(
                {"economics": {"capex_gbp": 1234567.0, "lcoh_p_per_kwh": 5.2}}
            ),
            schema=EconomicAssessment,
        )
        assert "1,234,567" in response.text
        assert response.is_mock

    def test_mock_works_on_python_repr_context(self):
        """Python ``str()`` of a dict is not JSON, but single quotes are harmless.

        Worth pinning: the orchestrator serialises with ``json.dumps``, but a
        future caller might not, and the mock should degrade rather than crash.
        """
        provider = MockProvider()
        response = provider.complete(
            system="s",
            user="CONTEXT_JSON:\n{'economics': {'lcoh_p_per_kwh': 5.2}}",
            schema=EconomicAssessment,
        )
        assert response.text

    def test_mock_reports_unknown_when_no_heat_price_is_assumed(self):
        """A margin against an unknown price is no information, not a good margin."""
        import json

        provider = MockProvider()
        response = provider.complete(
            system="s",
            user="CONTEXT_JSON:\n"
            + json.dumps({"economics": {"lcoh_p_per_kwh": 5.2, "heat_price_p_per_kwh": None}}),
            schema=EconomicAssessment,
        )
        assert "undetermined" in response.text
        assert '"lcoh_vs_heat_price_assessment": "unknown"' in response.text

    def test_mock_never_formats_none_into_a_report_string(self):
        """A missing value must read as 'not estimated', not 'GBP None'."""
        provider = MockProvider()
        response = provider.complete(
            system="s",
            user='CONTEXT_JSON:\n{"economics": {"capex_gbp": null, "lcoh_p_per_kwh": null}}',
            schema=EconomicAssessment,
        )
        assert "None" not in response.text
        assert "not estimated" in response.text.lower()

    def test_mock_engineering_handles_a_missing_output(self):
        provider = MockProvider()
        response = provider.complete(
            system="s",
            user='CONTEXT_JSON:\n{"engineering": {"thermal_output_kw": null}}',
            schema=EngineeringAssessment,
        )
        assert "None" not in response.text
        assert response.text

    def test_mock_is_deterministic(self):
        provider = MockProvider()
        user = "CONTEXT_JSON:\n" + str({"economics": {"lcoh_p_per_kwh": 5.2}})
        a = provider.complete(system="s", user=user, schema=EconomicAssessment)
        b = provider.complete(system="s", user=user, schema=EconomicAssessment)
        assert a.text == b.text

    def test_mock_handles_empty_context_without_crashing(self):
        provider = MockProvider()
        response = provider.complete(
            system="s", user="no context here", schema=WellDataInterpretation
        )
        assert response.text
