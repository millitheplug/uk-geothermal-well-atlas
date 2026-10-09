# AI agents and prompts

## What the agents are for

Eleven agents read the output of the deterministic engineering engine and write
a human-readable interpretation of it. That is the whole of their job.

They do **not**:

- perform any arithmetic;
- set or adjust the feasibility score;
- choose the recommendation;
- introduce a figure that is not in the engine's result;
- claim commercial viability.

This is enforced structurally (the agents have no calculator and no access to
the score-setting code) and then enforced again at runtime by the discipline
gate, because a structural argument is not something to rely on when the thing
being defended is "this platform does not make claims it cannot support".

---

## Agents

| Agent (`name` in code) | Role |
|---|---|
| `WellDataAgent` | Whether the input record is fit to assess at all: completeness, plausibility, blocking issues |
| `GeothermalAgent` | Geology, formation and geothermal gradation context |
| `WellIntegrityAgent` | Casing, wellhead, abandonment status and what a re-equipment would involve |
| `HeatDemandAgent` | Whether the matched demand is a real opportunity or a modelled artefact |
| `HeatNetworkAgent` | Distribution losses, temperature feasibility, corridors |
| `EngineeringAgent` | Thermal output, heat pump, delivered heat |
| `EconomicAgent` | Reads CAPEX, OPEX, LCOH, NPV, IRR and break-even |
| `RiskAgent` | The risk register in narrative form |
| `RegulatoryAgent` | Consents, authorities and likely lead times |
| `FeasibilityAgent` | The composite picture: why the score is what it is |
| `ReportAgent` | Assembles the 19-section document |

The orchestrator runs them in dependency order — data validation before
engineering interpretation before economics before the report — because later
agents need earlier outputs to write anything coherent.

---

## Prompt construction

`agents/prompts.py` holds the system prompts. Each agent contributes three parts:

```
ROLE
  who this agent is and what it is responsible for

DISCIPLINE
  the constraints that apply to this agent specifically

OUTPUT
  the schema, restated as prose, with the field meanings
```

The user prompt (`BaseAgent.user_prompt`) is deliberately minimal:

```python
(
    "Assess the well described below. Use only the facts provided in the "
    "context. Anything not present in the context is unknown to you.\n\n"
    "CONTEXT_JSON:\n" + json.dumps(context, indent=2, default=str)
)
```

Each agent's `build_context()` extracts only the slice it needs. The context is
a serialisation of the engine's result, so **the context cannot contain a number
the engine did not produce**. This is the mechanism that makes "no arithmetic" a
property rather than a request.

### Values withheld from the agent on purpose

`expected_recommendation` and `expected_thermal_status` are passed to the
discipline gate, **not** into the agent's context.

The schemas are strict about extra fields, so embedding them would let an agent
see — and echo back — the very values it is meant to be checked against. An
agent that can read the answer is not being tested.

### Sampling

```python
temperature=0.0
```

Not a stylistic choice. An agent that varies between runs cannot be used to
review a decision, because you cannot tell a meaningful change in output from
sampling noise.

---

## The discipline gate

`agents/base.py::enforce_discipline(agent_name, output, expected_recommendation, expected_thermal_status)`
runs on every agent output before it is used.

### Two classes of violation

**Fatal — rejected, run recorded as violated.**

| Rule | Trigger |
|---|---|
| `no_guaranteed_viability` | Output contains a phrase from `FORBIDDEN_PHRASES`: `"commercially viable"`, `"is commercially viable"`, `"guaranteed"`, `"risk-free"`, `"risk free"`, `"certain return"`, `"will be profitable"`, `"is profitable"`, `"proven technology"`. The last is legitimate as a general statement about ground source heat pumps and is only rejected when the text also contains a narrowing marker — `"this well"`, `"this scheme"`, `"this project"`, `"this site"`, `"this candidate"`, `"the well is"` or `"the scheme is"`. |
| `recommendation_must_be_deterministic` | The agent named a recommendation other than the engine's. |

These cannot be repaired. The whole value of the platform is that it does not
make these claims, so a violation is a bug in the agent or the model, not a
formatting problem.

**Repairable — corrected, and the correction recorded.**

| Rule | Trigger | Action |
|---|---|---|
| `evidence_required` | A `FACT`, `MEASURED`, `DERIVED` or `ESTIMATE` assertion with no `source` | Relabelled `ASSUMPTION` |
| `evidence_required` | A `MEASURED` assertion with no source | Relabelled `UNKNOWN` |
| `no_status_upgrade` | `thermal_output_status` ranked above the engine's value | Reverted to the engine's value |
| `malformed_fact` | A fact record missing `statement` or `fact_type` | Dropped |

`MUST_NOT_UPGRADE` records the statuses that must never be presented as
something stronger: `ESTIMATE`, `ASSUMPTION` and `UNKNOWN`.

Rejection is too blunt for these: failing an entire run because an agent omitted
a citation teaches the agent to omit less rather than to omit correctly, and it
loses good work alongside the flaw.

Status rank order:

```
UNKNOWN < ASSUMPTION < ESTIMATE < DERIVED < MEASURED < FACT
```

Only *upgrades* are caught. Downgrading is conservative and is left alone.

### Visibility

Every correction is appended to the output's `confidence_notes` as
`"Corrected by the discipline gate: <rule> (<action>); …"` so it reaches the
report, and recorded in `OrchestrationResult.violations`, whose count the report
states. A gate nobody can see is indistinguishable from a gate that is not
running.

---

## Providers

`agents/llm.py`:

| Provider | Used when | Behaviour |
|---|---|---|
| `AnthropicProvider` | `ANTHROPIC_API_KEY` set | `claude-sonnet-4-5`, temperature 0, structured output validated against the agent's Pydantic schema |
| `MockProvider` | No key | Deterministic, schema-valid, offline |

Selection is `prefer_mock` overridable per call, which is what lets the test suite
exercise the real orchestration path without a network.

### Why the mock provider is safe

Because no agent performs arithmetic, the numbers in a report produced with the
mock provider are identical to those produced with the real one. Only the prose
differs.

This is not just a convenience for testing. It is the practical demonstration
that the agents are not load-bearing for any figure — if they were, running
without a key would produce a different answer, and the platform's central claim
would be conditional on having an API key.

The mock provider builds its output from the context it is given, so it also
exercises every downstream path: schema validation, discipline gate, report
assembly.

---

## Failure handling

Agent failures never lose a deterministic result. `run_assessment` wraps
orchestration in `try/except`; on failure it returns an
`OrchestrationResult(provider_name="failed")` with the exception recorded as a
violation, and the assessment is persisted with `agent_outputs = null`.

The correct behaviour for a screening tool is that the analysis is still available
with the engineering figures and a note explaining that the interpretation could
not be produced. Losing the score because a prose generator timed out would be
exactly backwards.

---

## The 19-section report

`agents/prompts.py::REQUIRED_REPORT_SECTIONS` is the authoritative list. The
orchestrator enforces that every one is present, and orders whatever the agent
produced to match it, so a report cannot silently lose a section:

1. Executive summary
2. Well characteristics
3. Temperature assessment
4. Geology
5. Well integrity
6. Geothermal configuration
7. Thermal output
8. Heat demand
9. Heat network
10. CAPEX
11. OPEX
12. LCOH
13. NPV
14. IRR
15. Risks
16. Regulatory considerations
17. Data gaps
18. Validation plan
19. Final recommendation

`render_report_markdown()` appends an executive summary and a `### Disclaimers`
block to whatever the agents produced. The disclaimers are not optional
flourishing: they carry the caveats the API returns, and a report that ends with
a recommendation and no stated limits invites the reader to treat that
recommendation as a decision.

---

## Extending this

Adding an agent:

1. Subclass `BaseAgent` in `agents/agents.py`: set `name`, `schema`, implement
   `build_context`.
2. Add the system prompt to `agents/prompts.py`.
3. Add the schema to `agents/schemas.py`.
4. Register it in the orchestrator's sequence, after the agents it depends on.

Then check three things:

- Does the context it builds contain only engine output? If you need a number the
  engine did not produce, the engine should produce it.
- Does the gate have everything it needs to check this agent? `expected_*` values
  are passed per agent, not globally.
- Does a `MockProvider` output pass the schema? The test suite runs on mock, so a
  schema the mock cannot satisfy is a schema nothing verifies.

Adding a forbidden phrase: add it to `FORBIDDEN_PHRASES`, or to the
narrowing-marker list instead if the phrase is legitimate as a general statement.
`test_agents.py` should cover each phrase — a prohibited-phrase list with no test
is a list that will grow by accident.