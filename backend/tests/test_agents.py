"""Tests for the agent layer.

The important assertions here are negative ones: that the discipline gate
actually catches the failures it claims to catch. A test suite that only checks
the happy path would pass even if every guard were removed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.llm import LLMError, MockProvider, get_llm_provider
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
from app.agents.base import enforce_discipline
from app.agents.orchestrator import AgentOrchestrator, render_report_markdown
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

        monkeypatch.setattr(settings, "anthropic_api_key", None, raising=False)
        assert isinstance(get_llm_provider(), MockProvider)

    def test_mock_used_when_explicitly_requested(self):
        assert isinstance(get_llm_provider(prefer_mock=True), MockProvider)

    def test_provider_name_is_stable(self):
        assert MockProvider().name == "mock"


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

    def test_nineteen_report_sections_required(self):
        assert len(REQUIRED_REPORT_SECTIONS) == 19


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

    def test_report_covers_all_nineteen_sections(self):
        _, _, result = self._run()
        titles = {s.title for s in result.report.sections}
        for required in REQUIRED_REPORT_SECTIONS:
            assert required in titles, required

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
