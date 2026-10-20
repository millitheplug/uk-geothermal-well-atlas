# Thesis walkthrough

A single reference for demonstrating and writing up the platform: the numbers
to quote, the questions a reviewer is likely to ask with the answer the code
supports, and the wording corrections that keep the write-up honest.

Everything here was verified against the code and the running application on
**2026-10-21**. Where a figure depends on the database (they differ per
deployment), the source database is named.

---

## 1. The five headline numbers (local development database)

Recorded from the running app's own dashboard (`include_mock = true`, which is
the screen's default) and cross-checked against the API:

| Figure | Value |
|---|---|
| Wells in inventory | **2,158** (2,138 real NSTA records + 20 synthetic) |
| With a temperature record | **37** |
| Wells scored (assessed) | **2** |
| Reaching Medium or High priority | **0** |
| Best score | **40.49** (Low priority band; best *real* well 39.96, L46/16-31 SPRINGS ROAD) |

With the synthetic toggle off the same screen reads 2,138 / 19 / 1 / 0, best
39.96. The top-scoring well overall (40.49, UK-MOCK-NTH-012) is synthetic and
is labelled as such.

Three different figures are easily confused here and must not be mixed:

- **2,158 / 2,138** — national inventory (dashboard KPIs are national).
- **23** — *candidates*: wells with a temperature record **and** a known
  integrity status (`dashboard.py`, `candidate_wells`).
- **2** — wells with a stored assessment and therefore a priority band.
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
3. **Which wells were scored** — see §1. The "14 assessed" figure formerly on
   the risk page was a mislabelled candidate count (fixed in PR #15); the
   deployed database's numbers come from that deployment's own analyses.
4. **Component formulas** — all eight in `backend/app/engineering/scoring.py`,
   each 0–1 with documented internal sub-weights, piecewise curves, caps for
   estimated values and hard floors for integrity.
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
   statuses label every figure. Two separate mechanisms by design.
9. **Risk register** — 17 categories, one rule per category; likelihood and
   impact derived from the well's own data; uncertainty is a documented
   constant per rule (0.35–0.60). The register stores computed output, not user
   input.
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
    "computed from well data at run time".
14. **Stack** — Python 3.12.7, FastAPI, SQLAlchemy 2.0, PostgreSQL/PostGIS with
    SQLite fallback, Alembic; Next.js 14, React 18, TypeScript 5.6, Tailwind;
    Render (Frankfurt, free plan).
15. **Adapters/queue** — 10 adapters (9 synthetic + NSTA), no Celery: analyses
    run inline via FastAPI BackgroundTasks; `workers/analysis_worker.py` exists
    and is documented as not required.
16. **LLM role** — explains, never computes (`docs/architecture.md`: "no code
    path by which a language model can influence a number"). Anthropic only
    when a key is configured; otherwise a deterministic mock.

## 3. Weight sensitivity test (the outstanding methodological check)

Run: `python scripts/weight_sensitivity.py` — re-runs the unmodified engine for
every well with a temperature record (37: 19 real, 18 synthetic) on a **copy**
of the database, then recomputes composites under perturbed weights and re-bands
with the engine's own `recommend()`. The recomputed baseline matches the engine
to 1e-6 for every well, which also demonstrates the 0.05 confidence term is
live.

| Perturbation | Rank ρ vs baseline | Wells changing band | Max score move |
|---|---|---|---|
| Any single weight ±5 points | ≥ 0.95 (most ≥ 0.99) | ≤ 15, all one step | ≤ 4.0 pts |
| Any single weight ±10 points | ≥ 0.89 | ≤ 15, all one step | ≤ 8.0 pts |
| Equal weights (0.125 each) — a deliberately drastic control | 0.895 | 9 | 11.6 pts |

Conclusions the thesis may draw:

- The ranking is **not an artefact of the particular weights**: even doubling
  every non-thermal weight's share or flattening all eight to equality leaves
  rank correlation ≥0.89, and the top of the table barely moves.
- Band changes concentrate at the **Low / Do-not-pursue boundary (score ≈ 25)**,
  where several wells sit within two points of the line. Every change is one
  step; no well jumps a band by two.
- The two High-priority wells (both synthetic, labelled) stay High in all but
  the −10-point thermal scenario.
- Two real wells (LN/10-4Z REMPSTONE 4Z, L47/16-16 SALTFLEETBY 7X) sit just
  below the Medium line and cross it under some +5/+10 shifts — say "within one
  band of Medium under weight stress", not "Medium".
- The regulatory weight moves scores but not ranks (ρ = 1.0 in every shift):
  it is close to a constant across the inventory at present.

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

- Render deployment is currently returning 502 (diagnosis in progress); the
  local build is the reference for this walkthrough.
- Network corridors on the heat-demand page return zero rows for the dev
  dataset (no temperature well lies within 5 km of a demand cell there).
- Re-loaded analyses restore their calculation trace but not the per-entry
  `input_units`/`assumptions`/`sources` for rows written before PR #16 (new
  assessments store them).
- Analysis-level `warnings` and `parameters` are still empty on re-load (not
  persisted on the analysis row); freshly created analyses carry them.
- Monte Carlo is not implemented: no spreads are quoted anywhere, by design.
