# Thesis walkthrough

A single reference for demonstrating and writing up the platform: the numbers
to quote, the questions a reviewer is likely to ask with the answer the code
supports, and the wording corrections that keep the write-up honest.

Everything here was verified against the code and the database on
**2026-10-26** (originally 2026-10-21; §1 and §3 refreshed after the full
assessment run). Where a figure depends on the database (they differ per
deployment), the source database is named.

---

## 1. The five headline numbers (one database, one run)

**Source: the local development database (`dev.db`), fully assessed on
2026-10-26** with:

    python -m scripts.cli assess --email analyst@example.com --limit 5000

Every figure below is the *latest stored analysis per well* from that run —
the same rows the dashboard and API serve. Earlier screenshots showing
"2 assessed" or "40 assessed" were counts of stored analyses at *that moment*,
not a different truth. When a figure is quoted in the thesis, name the
database and the run; do not mix numbers from different states.

| Figure | Value |
|---|---|
| Wells in inventory | **2,158** (2,138 real NSTA records + 20 synthetic, labelled) |
| With a temperature record | **37** (19 real + 18 synthetic) |
| Wells scored (assessed) | **2,158 — every well in the inventory** |
| Reaching Medium or High priority | **7** (5 Medium + 2 High) — **all synthetic and labelled; no real well reaches Medium** |
| Best score | **71.75** UK-MOCK-WLN-002 Wealden Capture Test 4 (synthetic, High). Best *real* well: **43.18** LN/10-4Z REMPSTONE 4Z (Low band) |

Band breakdown (latest analysis per well):

| Band | All (2,158) | Real only (2,138) | Synthetic only (20) |
|---|---|---|---|
| HIGH PRIORITY | 2 | 0 | 2 |
| MEDIUM PRIORITY | 5 | 0 | 5 |
| LOW PRIORITY | 23 | 14 | 9 |
| DO NOT PURSUE | 2,128 | 2,124 | 4 |

Best real wells: LN/10-4Z REMPSTONE 4Z **43.18**, L46/16-31 SPRINGS ROAD
**39.96**, L47/16-16 SALTFLEETBY 7X **39.75**, L47/16-7W SALTFLEETBY 7W
**37.27** — all Low band.

Wells without a temperature record score the thermal component 0.0 (never
silently dropped) and land in Do not pursue with scores of roughly 8–15; that
is why the inventory-wide assessed count now reads 2,158 where partial runs
read much smaller numbers.

Several easily-confused quantities; do not mix them:

- **2,158 / 2,138** — national inventory (dashboard KPIs are national).
- **37** — wells with a temperature record (the only wells whose scores are
  driven by measured heat).
- **23** — *candidates*: temperature record **and** a known integrity status
  (`dashboard.py`, `candidate_wells`). This coincidentally equals the
  Low-priority count today; they are different quantities.
- **2,158** — wells with a stored assessment and therefore a priority band.
- The *candidate table* is additionally **tenant-scoped**: a fresh account has
  adopted no wells, so its candidate table can legitimately show nothing while
  the national KPIs are non-zero.

## 2. The sixteen questions, answered

1. **Is data confidence in the composite?** Yes. `WEIGHTS` includes
   `data_confidence: 0.05` and `composite_score()` sums it. Separately, the
   headline confidence score gates HIGH (≥0.55) and MEDIUM (≥0.35) priority and
   discounts the score by 25% below 0.35. Both statements are true of *different
   things*; the misleading "not folded into the score" wording was corrected in
   PR #15.
2. **Heat-demand provenance** — entirely synthetic: 341 modelled buildings,
   8 demand areas, all `is_mock = True`. Real sources (DESNZ, ONS EPC) are
   documented as future work in `docs/data-sources.md`.
3. **Which wells were scored** — see §1. As of 2026-10-26 the local database
   holds an assessment for every one of the 2,158 wells; the "14 assessed"
   figure formerly on the risk page was a mislabelled candidate count (fixed in
   PR #15); other deployments' numbers come from that deployment's own analyses.
4. **Component formulas** — all eight in `backend/app/engineering/scoring.py`,
   each 0–1 with documented internal sub-weights, piecewise curves, caps for
   estimated values and hard floors for integrity. Written out in §6.1.
5. **Weight origin** — no derivation exists in the repository. State in the
   thesis: provisional author judgement, not literature-derived or elicited,
   and (now) sensitivity-tested — see §3.
6. **Bands** — ≥65 **and** confidence ≥0.55 → High; ≥45 **and** ≥0.35 → Medium;
   ≥25 → Low; <25 → Do not pursue. A critical integrity risk caps at Low;
   ≥3 critical risks apply an extra ×0.8. "Eligible" = candidate (temperature +
   known integrity).
7. **Missing information** — never dropped. A missing primary input scores the
   component 0.0; a missing secondary input scores at the low end of its curve.
   Gaps therefore lower the score and are listed as data gaps.
8. **Evidence quality** — 5 confidence bands from 5 weighted axes; 7 epistemic
   statuses label every figure. Two separate mechanisms by design. The axes and
   their derivation are in §6.2.
9. **Risk register** — 17 categories, one rule per category; likelihood and
   impact derived from the well's own data; uncertainty is a documented
   constant per rule (0.35–0.60). The register stores computed output, not user
   input. The 17 category names are in §6.3.
10. **NSTA provenance** — ArcGIS item `d40f9dc58ca84268935582152a5b20f9`,
    snapshot + SHA-256 committed under `data/real/nsta/`, 2,138 records,
    refresh via `python -m scripts.fetch_nsta_onshore_wells`, CI verifies the
    checksum.
11. **Data-quality score** — a hardcoded 0.0 placeholder in both adapters, not a
    measurement. The UI now says "Not calculated" (PR #16).
12. **Licence** — NSTA Open User Licence, non-commercial use with attribution
    ("Contains data from the North Sea Transition Authority."). Read the terms
    before any public release.
13. **Parameters** — 17 documented defaults (`parameters.py`), each with
    rationale, source and range; exposed at `GET /admin/parameters`; null means
    "computed from well data at run time". All 17 named in §6.3.
14. **Stack** — Python 3.12.7, FastAPI, SQLAlchemy 2.0, PostgreSQL/PostGIS with
    SQLite fallback, Alembic; Next.js 14, React 18, TypeScript 5.6, Tailwind;
    Render (Frankfurt, free plan), Neon Postgres.
15. **Adapters/queue** — 10 adapters (9 synthetic + NSTA), no Celery: analyses
    run inline via FastAPI BackgroundTasks; `workers/analysis_worker.py` exists
    and is documented as not required. Detail in §6.4.
16. **LLM role** — explains, never computes (`docs/architecture.md`: "no code
    path by which a language model can influence a number"). The provider is
    configuration-selected (Anthropic today; PR #18 adds a MiMo provider behind
    `AI_PROVIDER`); with no key a deterministic mock fills the same schema, and
    the numbers are identical either way.

## 3. Weight sensitivity test (the outstanding methodological check)

Run: `python scripts/weight_sensitivity.py` — re-runs the unmodified engine for
every well with a temperature record (37: 19 real, 18 synthetic) on a **copy**
of the database, then recomputes composites under perturbed weights and re-bands
with the engine's own `recommend()`. The recomputed baseline matches the engine
to 1e-6 for every well, which also demonstrates the 0.05 confidence term is
live.

The correlation reported is **Spearman's rank correlation ρ**, implemented in
the script as the standard `1 − 6Σd²/(n³−n)` over ranks. The script reports it
twice per scenario: over all 37 temperature wells, and over the **19 real NSTA
wells only** (the 37 include 18 synthetic wells, which the thesis must say).

| Perturbation | ρ (37 wells) | ρ (19 real) | Band changes | Max score move |
|---|---|---|---|---|
| Any single weight ±5 points | ≥ 0.95 (most ≥ 0.99) | ≥ 0.93 | ≤ 15, all one step | ≤ 4.0 pts |
| Any single weight ±10 points | ≥ 0.89 | ≥ 0.74 | ≤ 15, all one step | ≤ 8.0 pts |
| Equal weights (0.125 each) — a deliberately drastic control | 0.895 | 0.665 | 9 | 11.6 pts |
| Regulatory weight ±5 / ±10 | 1.000 | 1.000 | scores move, ranks do not | ≤ 7.9 pts |

Conclusions the thesis may draw — stated with the honest caveat:

- Single-weight shifts of ±5 points leave the ranking essentially unchanged on
  both populations (ρ ≥ 0.93 even on the 19 real wells alone): **the ranking is
  not an artefact of the particular weights** at the tested perturbation sizes.
- **Caveat to state explicitly**: the 19 real wells cluster tightly (best 43.2,
  most around 12–15), so *drastic* re-weightings reorder them more than they
  reorder the full table — the equal-weight control drops real-only ρ to 0.665
  (and geometry +10 points to 0.737). The **band structure is far more stable
  than the fine ordering**: every band change observed anywhere under
  single-weight shifts is one step, concentrated at the Low/Do-not-pursue
  boundary (score ≈ 25), where several real wells sit within two points of the
  line.
- LN/10-4Z REMPSTONE 4Z crosses Medium under thermal +5/+10, integrity −10,
  demand −5/−10, economics −10, network −5/−10, geometry +5/+10, regulatory
  ±5/±10 and equal weights. L47/16-16 SALTFLEETBY 7X crosses only under thermal
  +10, geometry +10 and regulatory +10. Say "within one band of Medium under
  weight stress", never "Medium".
- The two High-priority wells (both synthetic, labelled) stay High in all but
  the −10-point thermal scenario.
- The regulatory weight moves scores but not ranks (ρ = 1.0 in every shift): it
  is close to a constant across the inventory at present.

## 4. Wording that must match the app

Use these formulations; each replaced a sentence that contradicted the code
(landed in PRs #15 and #16):

- Evidence quality **counts for 5% of the score** *and* the separate confidence
  rating **can pull a well down a priority level**.
- The weights are **provisional engineering judgement**, not published
  research — now accompanied by the sensitivity result in §3.
- A well **is a candidate when it has a temperature measurement and a known
  integrity status**. Do not write "eligible".
- Risk exposure = **raw likelihood × impact × (1 + uncertainty × 0.5), capped
  at 1** — uncertainty multiplies scores *up*, it does not divide them.
- The data-quality column reads **"Not calculated"** because the value is a
  placeholder; do not quote 0.00 as a result.
- Distance to demand: **"No match within 2 km"** means the assessment searched
  and found no building — demand is **unknown, not zero**.
- Buildings, demand and the nearest 20 synthetic wells are stand-ins; NSTA well
  records are real (2,138); Scotland, Wales and Northern Ireland are not covered
  by the temperature dataset.

## 5. Known limitations to state if asked

- The Render free-plan API has a **cold start of roughly 35 s** on the first
  request after idle; that first request can time out (it presented as a 502)
  while the retry succeeds. The deployment is otherwise healthy (Postgres on
  Neon, seeded, `is_mock_data = true` in admin health).
- Network corridors on the heat-demand page return zero rows for the dev
  dataset (no temperature well lies within 5 km of a demand cell there).
- Re-loaded analyses restore their calculation trace but not the per-entry
  `input_units`/`assumptions`/`sources` for rows written before PR #16 (new
  assessments store them).
- Analysis-level `warnings` and `parameters` are still empty on re-load (not
  persisted on the analysis row); freshly created analyses carry them.
- Monte Carlo is not implemented: no spreads are quoted anywhere, by design.

## 6. The supervisor's follow-up questions (detailed answers)

### 6.1 Item 4 — how each 0–1 component sub-score is computed

All formulas are in `backend/app/engineering/scoring.py`; every curve endpoint
below is a literal in that file, not a tuned parameter.

**Thermal (weight 0.25)** — `thermal_score()`. A missing temperature returns
0.0 outright. Otherwise three sub-scores:
- *temperature*: headroom above the 70 °C target; ≤0 K → 0.15, then piecewise
  0 K → 0.35, 10 K → 0.70, 30 K → 1.0.
- *swing*: usable temperature swing, piecewise 0 → 0.05, 5 K → 0.40, 15 K →
  0.80, 25 K → 1.0 (missing swing → 0.6 × temperature sub-score).
- *output*: thermal output in kW, piecewise 0 → 0, 50 → 0.20, 200 → 0.60,
  500 → 0.85, 1000 → 1.0 (missing → 0.5 neutral).
The temperature-derived part is `min(0.40·temp + 0.25·swing, cap)` where the
cap is 1.0 for measured temperatures and 0.85/0.70/0.55/0.40/0.30 for
High/Medium/Low/Very-low/Unknown *estimated* temperatures; the component is
that plus `0.35·output`.

**Integrity (0.20)** — `integrity_score()`. A floor is set from the recorded
status (good 0.85, partially mechanical 0.55, suspended/inaccessible 0.35,
abandoned/no access 0.15, poor 0.10, unknown 0.20). If condition sub-scores
exist they are combined as casing 0.30 + abandonment 0.25 + access 0.20 +
wellhead 0.10, capped at floor + 0.15; if none exist the score is floor × 0.75.
A well with no casing string documented is multiplied by 0.8 — its condition
cannot be verified from records at all.

**Demand (0.15)** — `demand_score()`. Missing demand or missing output returns
0.0. Otherwise: *ratio* = annual demand ÷ (output kW × 8,760 h), banded
piecewise (<0.25 → 0.10, 0.25–0.6 → up to 0.45, 0.6–3.0 → up to 1.0 at 3.0,
>3.0 → 1.0); *off-taker concentration* (1 building → 0.35, <5 → 0.65, <20 →
0.85, ≥20 → 1.0, unknown → 0.6); *peak ratio* (<0.3 → 0.45, 0.3–1.5 piecewise,
>1.5 → 0.7, no peak data → 0.8). Component = `0.50·ratio + 0.25·concentration +
0.25·peak`, then capped by demand confidence (High 1.0, Medium 0.90, Low 0.75,
Very low 0.60, Unknown 0.45). Demand matching is a **ratio, not a magnitude**.

**Network (0.10)** — `network_score()`. Distance to demand, piecewise metres:
0 → 1.0, 500 → 0.90, 1,500 → 0.70, 3,000 → 0.45, 10,000 → 0.15; **missing →
0.0** (unknown distance cannot be credited). Heat loss as a fraction, piecewise:
0 → 0.70, 0.10 → 1.0, 0.20 → 0.60, 0.35 → 0.25; unknown → 0.8. Existing
network 1.0, none 0.5; required reinforcement reduces the score toward 0.45
(0.35 when no network exists). Component = `0.50·distance + 0.25·loss +
0.25·existing`; a pipe run beyond 5 km is multiplied by 0.85.

**Geometry (0.05)** — `geometry_score()`. Depth, piecewise metres: 0 → 0.35,
800 → 0.70, 1,500 → 0.90, 3,000 → 1.0, 5,000 → 0.75; missing → 0.0.
Deviation: deviated wells start at 0.55 capped at 0.70; >60° inclination →
0.30 capped at 0.45; 30–60° → capped at 0.60. True-vertical-depth / measured-
depth ratio: <0.5 → 0.5, <0.75 → 0.8, else 1.0. Component = `0.5·depth +
0.3·deviation + 0.2·tvd/md`, capped by the deviation ceiling.

**Economics (0.15)** — `economics_score()`. No LCOH → 0.0. LCOH versus the
assumed heat price: ≤0.4× price → 1.0, ≥1.5× price → 0, linear in between.
NPV positive → 1.0, negative → 0.25, unknown → 0.6. IRR piecewise 0 % → 0.20
up to 20 % → 1.0 (unknown → 0.6). Payback piecewise 0 yr → 1.0 down to 25 yr →
0.05 (unknown → 0.7). Component = `0.50·lcoh + 0.20·npv + 0.15·irr +
0.15·payback`.

**Regulatory (0.05)** — `regulatory_score()`. Consent burden starts at 1.0 and
is reduced by 0.30 (abstraction licence), 0.20 (discharge consent), 0.15
(planning permission), 0.20 (Site of Special Scientific Interest), 0.10
(conservation area) and 0.15 (mining-subsidence area) as applicable. Programme
risk is piecewise in estimated approval months: 0 → 1.0, 6 → 0.85, 12 → 0.60,
24 → 0.30, 36 → 0.10. Component = `0.65·consent + 0.35·programme`. Configuration
matters first: a closed loop can avoid the abstraction licence and discharge
consent an open loop needs.

**Data confidence (0.05)** — the separate confidence score (§6.2), clamped to
0–1, enters the composite directly as the eighth component.

Composite = Σ (weight × component), clamped to [0, 1] and reported ×100.

### 6.2 Item 8 — how the confidence percentage is derived

`backend/app/engineering/confidence.py` computes a 0–1 score from **five
weighted axes**, reported separately from feasibility except for the explicit
5% weight above:

| Axis | Weight | What it measures (short form) |
|---|---|---|
| `source_reliability` | 0.25 | Mean trust of the contributing sources; ×0.8 for a single source; +0.05 per extra source beyond one (capped at +0.10); no sources → 0.15 |
| `data_completeness` | 0.25 | `0.75 × (required fields present / 10) + 0.25 × (desirable fields present / 6)`, with documented reductions if integrity is unassessed (×0.8) or demand is absent (×0.85) and a bonus for available well logs (+0.10) |
| `measurement_quality` | 0.25 | Method score (static bottom-hole temperature 0.95 down to analogous 0.20; none → 0.45), reduced for estimates (×0.75), derived values (×0.85), un-stabilised readings (×0.7), high variability (×0.75), shallow measurement depth (×0.9); +0.15 if a flow test exists; **no temperature at all → 0.05** |
| `recency` | 0.10 | Half-life decay `0.5^(age/25 yr)`, ×0.7 beyond 30 years, ×0.6 if the well was abandoned more than 10 years ago |
| `cross_source_agreement` | 0.15 | Spread of independent temperature records against a 5 K tolerance: within tolerance → `1 − 0.1·spread/5`; beyond → `max(0.05, 0.6/(1+ratio))`; +0.05 if ≥3 sources agree; single source → 0.40 |

Score = the weighted sum, clamped to [0, 1], then **capped at 0.6 when no
temperature is known** — an unmeasured well cannot claim high confidence.
Bands: ≥0.75 High, ≥0.55 Medium, ≥0.35 Low, >0 Very low, 0 Unknown.

The score is then used in two places, deliberately: the 5% term inside the
composite (a nudge, not a proxy for physical defects) and as a **gate** —
Medium priority requires ≥0.35, High requires ≥0.55, and below 0.35 the
feasibility score itself is discounted by 25%.

### 6.3 Item 13 — the 17 parameters and the 17 risk categories

**Parameters** (`backend/app/engineering/parameters.py`, each with value, unit,
rationale, source and low/high/distribution where a range is defensible;
served at `GET /admin/parameters`; **null means "computed from the well's own
data at run time", never defaulted**):

1. `flow_rate_lps` — 20 L/s
2. `source_temperature_c` — null (record-derived)
3. `return_temperature_c` — null (computed)
4. `utilisation_factor` — 0.85
5. `capacity_factor` — 0.55
6. `operating_hours_per_year` — 3,300 h
7. `target_supply_temperature_c` — 70 °C
8. `heat_pump_carnot_ratio` — 0.45
9. `network_length_m` — null (computed)
10. `ground_temperature_c` — 10 °C
11. `linear_loss_w_per_m_per_k` — 0.20 W/(m·K)
12. `discount_rate` — 0.08
13. `project_lifetime_years` — 20 years
14. `electricity_price_p_per_kwh` — 15.0 p/kWh
15. `heat_price_p_per_kwh` — 8.5 p/kWh
16. `contingency_fraction` — 0.20
17. `fuel_price_p_per_kwh` — null (fuel offset not modelled)

**Risk categories** (`RiskCategory` in `backend/app/core/enums.py`; one rule
per category in `engineering/risk.py` — `groundwater` has two rules):

1. `well_integrity`
2. `temperature_uncertainty`
3. `thermal_decline`
4. `corrosion`
5. `scaling`
6. `groundwater`
7. `network_distance`
8. `heat_demand_uncertainty`
9. `capex`
10. `electricity_price`
11. `heat_price`
12. `regulation`
13. `planning`
14. `land_access`
15. `customer_connection`
16. `construction`
17. `operations`

### 6.4 Item 15 — how data is ingested, and what the "queue" does

**Adapters.** `backend/app/data_import/` defines an `Adapter` base class: a
subclass implements `fetch()` (and one or more `load_*` methods), and the base
`run()` wrapper handles dataset registration, provenance recording, timing,
error capture and the batch commit — so every adapter produces the same
`ImportResult` (records read / written / rejected, errors, warnings, duration).
The registry (`data_import/registry.py`) holds **10 adapters**: nine synthetic
(`mock_wells`, `mock_temperatures`, `mock_integrity`, `mock_geology`,
`mock_buildings`, `mock_demand_areas`, `mock_heat_networks`,
`mock_energy_prices`, `mock_regulatory`) and one real (`nsta_wells`, the NSTA
onshore snapshot, deliberately excluded from bootstrap — it is loaded only on
explicit ingest). Order matters and is declared (`BOOTSTRAP_ORDER`): wells
before temperatures, integrity or geology; temperatures before the roll-up.
Ingestion runs from the CLI (`python -m scripts.cli ingest nsta_wells`,
`bootstrap`) or the admin API.

**Queue.** There is **no Celery/Redis queue**. `POST /analyses` runs the
deterministic pipeline synchronously (seconds); the agent narration and report
can be deferred to a FastAPI **BackgroundTasks** job, and
`GET /analyses/{id}/progress` polls the analysis row's own status
(`pending/running/complete/failed`). `workers/analysis_worker.py` is a
documented-as-**not required** poller kept ready for future scale: because no
agent performs a calculation, dropping the agent step would slow a run down
without changing a single figure.

### 6.5 Items 17–19 — testing, user review, ethics

**17 — Testing.** Yes, automated and CI-enforced on every PR:
**534 backend tests** in 10 suites (`test_scoring`, `test_thermal`,
`test_confidence_risk`, `test_pipeline`, `test_financial`, `test_geospatial`,
`test_nsta_adapter`, `test_api`, `test_agents`, `test_config`) plus **42
frontend tests** (`auth-routes`, `basemap`, `report-markdown`, `utils`), with
lint, type-check and `next build` in the same pipeline. The discipline-gate
tests are *negative* tests — they fail if the guards that stop an LLM from
influencing numbers are ever removed. The agent path runs against a
deterministic mock provider, so it is testable offline and in CI. The
sensitivity script (§3) additionally asserts the recomputed composite matches
the engine to 1e-6.

**18 — User review.** Human review is supported, and its channels are:
every figure carries an **epistemic label** (7 statuses: measured, derived,
estimated, assumed, synthetic, unknown, not-applicable) and provenance;
**what-if scenarios** let a user override any input parameter and re-run, stored
as separate, clearly labelled scenarios; each analysis emits **prioritised
validation actions** (CRITICAL/HIGH/MEDIUM — what to measure next and why); and
agent text is schema-gated so it can never alter a number — it can only narrate,
prioritise or contest. There is deliberately **no approve/reject workflow over
scores**: scores are deterministic engine output (versioned `SCORE_VERSION`);
human judgement enters as overrides and validation, both recorded.

**19 — Ethics.** Research-ethics approval is **not applicable** to this system
and none was sought: the platform uses only public regulatory and industrial
data (NSTA open-licence records, published guidance) about infrastructure —
**no human participants, no personal data, no human-subject material**. Two
honest side-notes for the write-up: the NSTA licence is **non-commercial with
attribution**, and if user accounts were ever studied as participants (e.g. a
usability study), normal ethics procedures would then apply — that is not the
case for the work described here.
