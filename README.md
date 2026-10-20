# UK Geothermal Well Atlas

Screening platform for repurposing UK onshore oil, gas and exploration wells to
geothermal heat production and district heating.

It takes what is already known about a borehole — where it is, how deep it goes,
what temperature was measured in it, what condition it is in, what is nearby
that might want heat — and produces a **deterministic** feasibility score, a
confidence score that describes the evidence rather than the resource, a risk
register, and a written report in which every figure can be traced back to a
formula, an input, a unit and a source.

It does not claim any well is commercially viable, because nothing in the data
available at screening stage can support that claim.

---

## The three rules this platform is built around

### 1. Every figure carries its provenance

Seven labels, used consistently in the database, the API, the calculation trace
and the interface:

| Label | Means |
|---|---|
| `FACT` | Stated directly in a cited source document. |
| `MEASURED` | An instrument reading in a well log, survey or test. |
| `DERIVED` | Computed from measured or documented values by a published formula. |
| `MODELLED` | Output of a simulation or correlation model, not a reading. |
| `ESTIMATE` | A third-party or analyst estimate with a documented method. |
| `ASSUMPTION` | A choice made without observation. |
| `UNKNOWN` | No defensible value exists. **Never** silently replaced with zero. |

An unknown is a finding. A well with no temperature measurement has an *unknown*
thermal potential, not a thermal potential of zero, and the whole assessment is
scoped around that difference.

### 2. No language model computes anything

Every number — thermal output, network loss, CAPEX, LCOH, NPV, IRR, the
composite score, the recommendation — is produced by the Python engineering
engine in `backend/app/engineering/`. Each calculation returns a `CalcResult`
carrying its inputs, units, formula, result, epistemic status, assumptions,
sources and warnings, and all of it is persisted and shown in the UI.

The eleven analysis agents in `backend/app/agents/` read those results and write
prose. A discipline gate (`enforce_discipline`) rejects any agent output that
asserts commercial viability, states a recommendation other than the engine's,
or presents an unsourced assertion as fact — relabelling it instead of allowing
it through. A language model cannot move a score, because it never sees a way to.

### 3. Unknowns are never converted to zero

Every layer propagates `None` as "unknown": thermal output, LCOH, IRR, payback.
`data_gaps` and `unknowns` are separate lists on the result, both surfaced in
the interface, and the report says which of them gate which conclusion.

---

## What is in the box

- **FastAPI backend** — wells, analyses, dashboard, heat, projects, admin, auth.
- **Deterministic engineering engine** — thermal, network, heat pump, CAPEX,
  OPEX, financial, scoring, confidence, risk, and the pipeline that sequences
  them.
- **Eleven analysis agents** with structured-output schemas and a discipline
  gate, plus a deterministic mock provider so the platform runs and tests
  without an API key.
- **Next.js frontend** — national map, dashboard, candidate ranking, well
  explorer, well record, thermal, heat demand, financials, risk, projects, data
  sources.
- **Alembic migrations**, a CLI for the operational surface, and a Docker
  compose file for PostGIS / Redis / MinIO — none of which are required.

## Quick start

Nothing external is required. SQLite with a haversine distance fallback covers
every feature except PostGIS `earth_distance` queries and spatial clustering,
and every API response reports which backend produced its distances as
`spatial_dialect`.

```bash
# 1. Backend
cd backend
python -m venv .venv && .\.venv\Scripts\activate        # Windows
# source .venv/bin/activate                              # macOS / Linux

pip install -e ".[dev]"

# 2. Schema, data and an account (run from the repository root)
cd ..
export DATABASE_URL=sqlite:///./geothermal.db          # Windows: $env:DATABASE_URL=...

python -m scripts.cli init
python -m scripts.cli bootstrap
python -m scripts.cli seed-user --email you@example.com --password "a-strong-one"

# 3. API
cd backend
uvicorn app.main:app --reload
#    http://localhost:8000/docs

# 4. Frontend, in a second terminal
cd frontend
npm install
npm run dev
#    http://localhost:3000
```

> The development datasets are **synthetic**. They exercise every code path and
> are shaped like the real data, but no well, building or price in them
> corresponds to anything real. They are watermarked on every screen that draws
> on them. See [docs/data-sources.md](docs/data-sources.md) for how to replace
> them with real NSTA, BGS and DESNZ data.

### Optional: PostGIS

```bash
docker compose -f infra/docker-compose.yml up -d
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ukgeothermal
python -m scripts.cli init --migrate
```

## Layout

```
backend/
  app/
    core/         settings, enums, security (PBKDF2, JWT, tenant scoping, audit)
    db/           declarative base, session, PostGIS/haversine dialect switch
    models/       wells, geology, heat, evidence, analysis, project, user
    schemas/      Pydantic request/response models
    services/     query service (filtering, demand matching), analysis service
    engineering/  the deterministic engine — every calculation lives here
    agents/       11 agents, orchestrator, discipline gate, LLM providers
    data_import/  adapter base, registry, mock adapters
    data_normalisation/  source-value → enum normalisation
    data_validation/     plausibility and completeness checks
    api/v1/       wells, analyses, dashboard, heat, admin, auth, projects
  alembic/        migrations
  tests/          464 tests
frontend/
  src/app/        routes: map, dashboard, candidates, explorer, wells/[id],
                  thermal, heat-demand, financials, risk, pipeline, data,
                  settings, sign-in
  src/components/ ui primitives, map, analysis panels, charts, views
  src/lib/        typed API client, domain formatting, MapLibre basemap
scripts/cli.py    operational CLI
workers/          polling analysis worker (optional; not required)
infra/            docker compose, dev up script
data/             schema samples for real-data adapters; drop raw sources in data/adapters
docs/             architecture, schema, api, formulas, prompts, data sources
```

## Scoring

```
composite = 0.25·thermal + 0.20·integrity + 0.15·demand + 0.15·economics
          + 0.10·network + 0.05·geometry + 0.05·regulatory + 0.05·data_confidence
```

Each component is scored 0–100. The weights are asserted to sum to 1.0 at
import, so the composite is directly comparable across wells and across
versions; `SCORE_VERSION` travels with every stored analysis.

The weights themselves are **provisional engineering judgement**. They were not
derived from published research or a structured elicitation method, and they
have not yet been sensitivity-tested. Changing a weight by 5–10 points and
checking whether the ranking moves is the test still outstanding.

Confidence is computed **separately** and reported as its own number. It reaches
the outcome in two explicit places: evidence quality counts as the 0.05
`data_confidence` term above, and the separate confidence score gates HIGH and
MEDIUM priority. A high score on thin evidence is the case this platform most
needs to get right, so the two numbers stay visible side by side rather than
being merged into one.

Four recommendation levels, assigned by the engine from the composite score with
confidence and open critical risks applied as gates:

| Level | Condition on the discounted score band |
|---|---|
| `HIGH PRIORITY` | ≥ 65 **and** confidence ≥ 0.55 |
| `MEDIUM PRIORITY` | ≥ 45 **and** confidence ≥ 0.35 |
| `LOW PRIORITY` | ≥ 25 |
| `DO NOT PURSUE` | < 25 |

The score band is discounted before the bands are applied: a 25% reduction when
confidence is below 0.35, and a further 20% when three or more critical risks
are open. The reasoning behind every discount is returned with the
recommendation, and the UI shows it.

## Tests

```bash
cd backend
python -m pytest tests/ -q          # 464 tests
cd ../frontend
npm run typecheck
```

The suite covers the thermal, financial, scoring, confidence, risk and
geospatial modules individually, the agent discipline gate, and the API
end-to-end including tenant isolation. Tests are order-independent —
`pytest-randomly` is enabled and has already caught one real bug that a fixed
order would have hidden.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Layering, request flow, the tenant model, why the map falls back to OSM |
| [docs/schema.md](docs/schema.md) | Every table, its columns, and the relationships that matter |
| [docs/api.md](docs/api.md) | Every endpoint, with parameters and worked examples |
| [docs/engineering-formulas.md](docs/engineering-formulas.md) | Each formula, its variables, its status, its source |
| [docs/ai-prompts.md](docs/ai-prompts.md) | Agent roles, prompt structure, and the discipline rules |
| [docs/data-sources.md](docs/data-sources.md) | Real sources, licences, and how to swap the mock adapters |
| [docs/deployment.md](docs/deployment.md) | Containers, migrations, workers, environment variables |

## Known limits

Stated up front rather than discovered later:

- The heat-demand dataset is modelled from floor area and building type. It is
  a screening estimate for comparing locations, not a substitute for a heat
  audit, and it will not show you that a single industrial estate holds more
  demand than a thousand houses.
- Corridors are straight-line distances, not routed pipelines. They are a lower
  bound on network length.
- Thermal decline is modelled from a parameter, not measured. It is labelled
  `MODELLED` wherever it appears.
- Nothing here establishes consent feasibility, land access, offtake or
  construction risk. Those are outside a desk screen and the interface says so
  where a user would otherwise expect them to be answered.

## Licence and intended use

Screening tool for a defined operational area. Not for public indexing, not for
investment decisions, and not a substitute for site-specific investigation. The
robots meta tag reflects this.
