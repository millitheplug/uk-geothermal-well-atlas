# Architecture

## The central constraint

The platform must produce numbers that someone can audit, and it must not be
able to produce a number that nobody can explain. Those two requirements drive
almost every structural decision below, so they are worth stating once and
referring back to.

---

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│  frontend/          Next.js app router, React 18, Tailwind   │
│                     typed API client, MapLibre GL            │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP + bearer token
                            │ (proxied through the Next server,
                            │  so the browser sees one origin)
┌───────────────────────────▼──────────────────────────────────┐
│  api/v1/             FastAPI routers, Pydantic schemas       │
│  core/security.py    auth, tenant scoping, rate limit, audit │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  services/           query_service, analysis_service          │
│                      query: filtering, facets, demand match   │
│                      analysis: well → inputs → pipeline       │
└───────┬───────────────────────────────────┬──────────────────┘
        │                                   │
┌───────▼─────────────────┐   ┌─────────────▼──────────────────┐
│  engineering/          │   │  agents/                      │
│  EVERY calculation     │──▶│  11 agents, orchestrator,     │
│  thermal, network,     │   │  discipline gate, providers   │
│  heatpump, cost, opex, │   │  (reads results, writes prose)│
│  financial, scoring,   │   └────────────────────────────────┘
│  confidence, risk,     │
│  pipeline             │
└───────┬─────────────────┘
        │
┌───────▼─────────────────────────────────────────────────────┐
│  models/ + db/         SQLAlchemy 2.0, PostgreSQL/PostGIS,   │
│                       SQLite + haversine fallback            │
└─────────────────────────────────────────────────────────────┘
```

The one-way dependency between `engineering/` and `agents/` is the important
edge. Agents import engineering types; engineering never imports agents. There is
no code path by which a language model can influence a number.

---

## The calculation pipeline

`engineering/pipeline.py::assess_well()` is the only orchestrator. It sequences
the modules and produces a `WellAssessment` dataclass containing every figure,
every status, the component scores, the risk assessment, the confidence
assessment, the data gaps, the unknowns, the warnings and the full trace.

Nine stages, all deterministic:

| Stage | Module | Produces |
|---|---|---|
| `data_validation` | `data_validation/validators.py` | Plausibility and completeness findings |
| `geology` | `models/geology.py` + inputs | Formation, basin, lithology context |
| `temperature` | `engineering/thermal.py` | Source temperature, output, uncertainty band |
| `well_integrity` | inputs | Casing, wellhead, abandonment status |
| `heat_demand` | `services/query_service.py` | Matched buildings, distances, demand totals |
| `engineering` | `network.py`, `heatpump.py` | Network loss, heat pump, delivered heat |
| `economics` | `cost.py`, `opex.py`, `financial.py` | CAPEX, OPEX, LCOH, NPV, IRR, payback |
| `risk` | `risk.py` | Seventeen-category register |
| `final_assessment` | `scoring.py`, `confidence.py` | Component scores, composite, recommendation |

Every stage writes into a shared trace context, which is why the Trace tab can
show all 30–60 calculations for a run in order rather than a flat list.

**The pipeline short-circuits rather than guessing.** A well with no temperature
record produces a `WellAssessment` with `source_temperature_c = None`,
`thermal_output_kw = None`, a `MEASURED`-or-`UNKNOWN` thermal component, and an
entry in `data_gaps`. It does not produce a thermal component of zero, and it
does not substitute a regional average.

---

## Tenant model

Wells are **national reference data with no `tenant_id`**. This is the right
model: a borehole is a physical object, not an organisation's asset, and
duplicating 40,000 rows per tenant to preserve that would be both wasteful and
misleading.

It creates a real problem: if wells have no owner, what stops one organisation
seeing another's projects?

`core/security.py::scoped_well_query()` is the answer, and it is the **only**
supported way to load wells:

```
visible(tenant) = wells referenced by an Analysis in that tenant
                  ∪ wells referenced by a WellDemand in that tenant
```

A well becomes visible to an organisation the moment it is attached to one of
their projects or analyses. Nothing else does that.

The rule is enforced in one function rather than by remembering to add a filter,
because the failure mode of forgetting is invisible: the query still works, it
just returns too much. That is exactly the kind of bug that survives code review
and ships.

**A security fix that this model required.** `/wells` and `/wells/map` originally
did not scope at all, because the mental model "national reference data" reads as
"public data". Both now go through `scoped_well_query`. There is a test asserting
that a tenant with no projects sees no wells.

**Discovery of unadopted wells.** Screening a well you have not yet adopted is a
legitimate workflow, so the two discovery endpoints accept
`include_claimable=true` (default `false`) and return wells that sit in no
project at all. `claimable_well_ids()` is deliberately tenant-independent: a
well in *any* project — including another tenant's — is never claimable, so the
opt-in cannot be used to reach across a boundary. `scoped_or_claimable_well_query()`
exists only for those two endpoints; everything else stays on `scoped_well_query`.
A claimable row is rendered with an adopt action, and adoption is an ordinary
`add_well_to_project` call, after which the normal visibility rule takes over.

---

## Spatial layer

`db/geo.py` is a dialect switch. Every distance expression is written twice —
once against PostGIS, once as a haversine expansion in portable SQL — and chosen
at query time from the bind's dialect name.

```python
# PostgreSQL
ST_Distance(geography(point), geography(point))

# SQLite fallback
6371000 · 2 · asin(sqrt(
    sin²(Δlat/2) + cos(lat₁)·cos(lat₂)·sin²(Δlon/2)
))
```

Both are metres. Both are reported back to the client as `spatial_dialect` on
every response that contains a distance, so nobody has to guess which one
produced a number.

Two details that took a bug to find:

- `func.least` does not exist in SQLite; `sqlalchemy.case` is used instead. The
  PostGIS `ST_DWithin` path uses `least` on the bounding-box comparison.
- Bounding-box pre-filtering is a genuine optimisation on both backends, but it
  must be an intersection with the exact predicate, not a replacement for it. A
  bounding box alone over-reports on a rotated or skewed shape.

The practical consequence: the whole platform, including every geospatial test,
runs on a laptop with no PostGIS server. That is not a convenience — it is what
makes the spatial logic reviewable by more than one person.

---

## Frontend

App router, React 18, Tailwind, shadcn-style primitives, Recharts, MapLibre GL.

### The map

`lib/basemap.ts` picks the basemap without ever needing a key:

- Default → OpenFreeMap's `liberty` style, vector tiles over OpenStreetMap data.
- `NEXT_PUBLIC_MAP_STYLE` set to an `https` style URL → that style instead.
  `mapbox://…` is rejected outright, because MapLibre has no code path for it
  and accepting it would produce a map that silently never loads.
- Configured style unreachable → a raster style built from OpenStreetMap tiles,
  swapped in at runtime.

Layer setup, event handling and popups are identical in all three paths, so the
fallback is purely a style choice and not a second code path that can drift.
Which of the three is on screen is stated in the badge on the map and on the
Settings screen, rather than hidden — and a basemap failure that survives the
raster swap is reported as a failure instead of a silently grey rectangle.

The renderer is MapLibre GL JS (BSD-3-Clause). It makes no authenticated calls
to anyone, which is what lets an evaluation environment with no credentials
provisioned still show a working map.

Two visual decisions worth explaining:

- **Marker radius encodes uncertainty.** An unassessed well is drawn larger and
  grey. A well nobody has measured cannot be mistaken for one that scored badly
  without anyone reading a legend.
- **The score ramp is ordered and colour-blind safe** (a viridis-like
  progression, dark blue → teal → green), because the map colours hundreds of
  points by score. A rainbow would imply a precision the score does not have and
  would collapse under deuteranopia.

Epistemic status is never carried by colour alone: every status badge carries a
word and an icon as well.

Attribution lives in the map's attribution control, not in a popup. The
OpenStreetMap source carries its own attribution string and the control is
always enabled, so clicking a well cannot dismiss a licence condition. The
absence of a token is disclosed separately as a small on-screen badge, which is
a UI nicety rather than the attribution itself.

### API client

`lib/api.ts` wraps fetch with bearer-token handling, abort support, and typed
responses. Errors are raised as `ApiError` with `isAuthError` and `isRateLimited`
predicates, so components branch on the failure kind rather than on message text.

The Next.js rewrite proxy forwards `/api/*` to the backend, so the browser sees a
single origin: no CORS preflight, and no backend host baked into the client
bundle. Set `API_PROXY=false` to talk to the backend directly.

---

## Agents and the discipline gate

`agents/orchestrator.py` runs eleven agents in sequence over the pipeline result.
Each returns a schema-validated object from `agents/schemas.py`.

`agents/base.py::enforce_discipline()` runs on every output and enforces the
rules below. Two classes of violation are handled differently:

**Fatal — the run is rejected and recorded.** The whole value of the platform is
that it does not make these claims, so they cannot be repaired:

- `no_guaranteed_viability` — output contains a prohibited phrase. The phrase
  list includes commercial-viability language and unfalsifiable assurances. A
  small number of phrases are legitimate as general statements but not of *this*
  well (`"proven technology"`); those are only rejected when the text also
  contains a narrowing marker such as `"this well"` or `"this scheme"`.
- `recommendation_must_be_deterministic` — the agent named a recommendation
  different from the engine's.

**Repairable — the output is corrected and the correction recorded.** Rejecting
a whole run over a formatting detail would make the gate something agents learn
to work around:

- `evidence_required` — a `FACT`, `MEASURED`, `DERIVED` or `ESTIMATE` assertion
  with no `source` is relabelled `ASSUMPTION`; a `MEASURED` assertion with no
  source is relabelled `UNKNOWN`. Both are true statements about the assertion's
  own provenance.
- `no_status_upgrade` — an agent that upgraded `thermal_output_status` from the
  engine's value has it reverted. Status is ranked
  `UNKNOWN < ASSUMPTION < ESTIMATE < DERIVED < MEASURED < FACT`, so only upgrades
  are caught.
- `malformed_fact` — a fact record missing `statement` or `fact_type` is dropped.

Every correction is appended to the output's `confidence_notes` so it is visible
downstream, and recorded in `OrchestrationResult.violations`, which the report
states as a count.

One structural point: `expected_recommendation` and `expected_thermal_status` are
passed to the gate, **not** embedded in the agent's input. The schemas are strict
about extra fields, so embedding them would let an agent see — and echo back —
the very values it is meant to be checked against.

### Providers

`agents/llm.py` has two:

- `AnthropicProvider` — used when `ANTHROPIC_API_KEY` is set. Temperature is
  0.0 because an agent that varies between runs cannot be used to review a
  decision.
- `MockProvider` — deterministic, schema-valid, no network. Used when no key is
  present.

Because no agent performs arithmetic, results are identical either way. Only the
prose differs. This is what makes the test suite runnable without a key, and it
is also the practical demonstration that the agents are not load-bearing for any
number.

---

## Data ingestion

```
adapters/<source>.py  →  base.Adapter.run()  →  ImportResult
                                    │
                        normalisation/validation
                                    │
                                 models
```

Every adapter declares `is_mock`. That flag is not decorative: it propagates to
the `datasets` row, to each well's `source` column, to every API response, and
into the interface, which is how synthetic data gets watermarked everywhere it
appears rather than only in one place.

`data_normalisation/normalise.py` maps source-specific spellings to enums
(`"static bottom hole temperature"` → `static_bht`, `"petrophysical_model"` →
`MODELLED`, and so on). `data_validation/validators.py` rejects implausible rows
with a reason rather than silently dropping them; rejected rows are counted and
returned in the `ImportResult` so a broken source is visible rather than silent.

`data_import/registry.py::run_bootstrap()` requires every adapter in
`BOOTSTRAP_ORDER` to succeed or raises. A partial load that looks successful is
worse than a failed one, because the dashboard cannot tell the difference between
"no wells in Scotland" and "the Scottish adapter crashed".

---

## Testing strategy

464 tests, organised by the thing under test rather than by module:

| File | Covers |
|---|---|
| `test_thermal.py` | Output, uncertainty bands, temperature swing, supersession |
| `test_financial.py` | LCOH, NPV, IRR bracket expansion, payback edge cases, break-even |
| `test_scoring.py` | Component normalisation, weight sum, recommendation bands |
| `test_confidence_risk.py` | All five confidence axes, uncertainty adjustment, taxonomy coverage |
| `test_pipeline.py` | Stage sequencing, unknown propagation, short-circuit behaviour |
| `test_agents.py` | Discipline gate rules, provider fallback, schema validation |
| `test_geospatial.py` | PostGIS/haversine equivalence, bounding boxes, radius queries |
| `test_api.py` | Every endpoint, tenant isolation, validation, error shapes |

`pytest-randomly` is enabled. This is not decoration: it has already caught one
real bug where a test passed only because of the order fixtures happened to run
in. The fix was a dedicated unclaimed-tenant fixture rather than relaxing the
assertion.

---

## Design decisions and their reasons

| Decision | Alternative | Why |
|---|---|---|
| Wells have no `tenant_id` | Tenant-owned wells | A borehole is physical. Duplicating 40k rows per tenant would misrepresent ownership and cost more for less safety. |
| Visibility via `scoped_well_query` | `tenant_id` on wells | One enforced function beats remembering a filter on 12 endpoints. |
| SQLite haversine fallback | Require PostGIS | The geospatial logic is reviewable and testable by anyone. Costs one dialect switch. |
| Confidence separate from score | Fold confidence into the score | Merging them hides exactly the case that matters: strong score, weak evidence. |
| Ordered viridis score ramp | Rainbow | Ordering survives greyscale and colour-blindness. A rainbow implies precision that is not there. |
| MapLibre GL with open basemaps | Mapbox GL with a token | A token-gated renderer shows a blank page to anyone who was not issued one, and the vendor's own auth call fails the whole map. MapLibre is BSD-3 and the default style needs no account at all. |
| Mock LLM provider | Require an API key | Tests run offline, and it demonstrates the agents are not load-bearing. |
| PBKDF2-HMAC-SHA256, 600k iterations | bcrypt/passlib | bcrypt 4.x broke passlib. PBKDF2 is in the standard library. |
| Threshold recommendations | Continuous ranking | The action attached to a band is discrete. You either commission a log or you do not. |
