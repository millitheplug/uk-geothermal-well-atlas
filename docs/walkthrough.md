# Thesis walkthrough

A single reference for demonstrating and writing up the platform: the numbers
to quote, the questions a reviewer is likely to ask with the answer the code
supports, and the wording corrections that keep the write-up honest.

Everything here was verified against the code and the running application on
**2026-10-21**. Where a figure depends on the database (they differ per
deployment), the source database is named.

---

## 1. The headline numbers (reference database)

One database is the source of every figure in the thesis. It was built fresh
from `main` on **2026-10-26** and every well was assessed by the engine
(score version 0.1.0):

```
export DATABASE_URL=sqlite:///ref.db ENVIRONMENT=development PYTHONPATH=backend
python -m scripts.cli init --migrate
python -m scripts.cli seed-user --email demo@example.com --password <password>
python -m scripts.cli bootstrap            # 20 synthetic wells + synthetic buildings
python -m scripts.cli ingest nsta_wells    # 2,138 real NSTA wells
python -m scripts.cli assess --email demo@example.com --limit 5000
```

The figures below are what the running app's own `/dashboard/national` and
`/dashboard/candidates` endpoints return for that database, with the synthetic
toggle on (the screen's default) and off:

| Figure | With synthetic wells | Real wells only |
|---|---|---|
| Wells in inventory | 2,158 | 2,138 |
| Wells scored (assessed) | 2,158 | 2,138 |
| With a temperature record | 37 | 19 |
| Candidates (temperature + known integrity status) | 23 | 14 |
| High / Medium / Low / Do not pursue | 2 / 5 / 23 / 2,128 | 0 / 0 / 14 / 2,124 |
| Best score | 71.75 (Wealden Capture Test 4, synthetic) | 43.18 (REMPSTONE 4Z, Low) |
| Evidence confidence: medium / low / very low | 2 / 28 / 2,128 | 0 / 14 / 2,124 |
| Estimated thermal capacity (sum of estimates) | 123.3 MWt | 59.4 MWt |
| Average temperature (wells that have one) | 66.9 °C | 64.0 °C |

Heat demand near wells reads 61.6 GWh in both views; all of it comes from
synthetic buildings.

Do not mix up three different counts:

- **Scored** — wells with a stored assessment (all 2,158 here).
- **Candidates** — wells with a temperature record **and** a known integrity
  status (`dashboard.py`, `candidate_wells`): 23, or 14 for real wells.
- **Inventory** — every well in the database, whether or not it is scored.

Figures such as "2 wells scored", a best score of 40.49, or counts between 14
and 40 came from databases in which only some wells had been assessed. Do not
quote them.

The *candidate table* is additionally **tenant-scoped**: a fresh account has
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
   impact derived from the well's own data; uncertainty is set per rule in
   `risk.py` (roughly 0.15–0.85, and lower for a few rules once the input is
   known). The register stores computed output, not user
   input.
10. **NSTA provenance** — ArcGIS item `d40f9dc58ca84268935582152a5b20f9`,
    snapshot + SHA-256 committed under `data/real/nsta/`, 2,138 records,
    refresh via `python -m scripts.fetch_nsta_onshore_wells`, CI verifies the
    checksum.
11. **Data-quality score** — a hardcoded 0.0 placeholder in both adapters, not a
    measurement. The UI now says "Not calculated" (PR #16).
12. **Licence** — NSTA User Agreement, non-commercial use with attribution
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

## 3. Weight sensitivity test

Run: `python scripts/weight_sensitivity.py --db ref.db` (all wells with a
temperature record: 37, of which 19 real and 18 synthetic) and
`python scripts/weight_sensitivity.py --db ref.db --real-only` (the 19 real
wells). It re-runs the unmodified engine on a **copy** of the database, then
recomputes composites under perturbed weights and re-bands with the engine's own
`recommend()`. The recomputed baseline matches the engine to 1e-6 for every
well, which also demonstrates the 0.05 confidence term is live.

The rank correlation is **Spearman's ρ**: the Pearson correlation of ranks, with
tied scores given the average of the ranks they span. (An earlier version used
plain ordinal ranks, which treat ties arbitrarily; the combined results moved
by less than 0.01 when this was corrected.)

| Perturbation | All 37 wells: ρ | Wells changing band | 19 real wells: ρ | Wells changing band |
|---|---|---|---|---|
| Any single weight ±5 points | ≥ 0.951 | ≤ 15 | ≥ 0.940 | ≤ 10 |
| Any single weight ±10 points | ≥ 0.894 | ≤ 15 | ≥ 0.737 | ≤ 13 |
| Equal weights (0.125 each), a deliberately drastic control | 0.905 | 9 | 0.712 | 6 |
| Confidence weight set to 0 | 0.981 | 8 | 1.000 | 6 |

Largest single-well score move: 4.0 points for ±5 and 8.0 for ±10 in both
groups (11.6 points for equal weights, or 11.3 for the real wells). Every band change, in both groups, moves a well
by exactly one band.

What the thesis may say:

- **Combined result.** With the synthetic wells included, the ranking is stable:
  ρ ≥ 0.89 under every single-weight shift and 0.905 under equal weights.
  Part of that is because the 18 synthetic wells span a wide range of scores
  and are easy to separate.
- **Real wells alone.** The ordering is stable under 5-point shifts (ρ ≥ 0.94)
  but not under every 10-point shift: geometry +10 gives 0.74, economics −10
  gives 0.86, integrity −10 gives 0.91, and equal weights give 0.71. The top
  four real wells score only 37.3 to 43.2, so small shifts reorder them. Report
  the real-well ranking as **indicative**; the robust result is the band (Low
  priority), not the order within it.
- **Weights that do not matter for real wells.** Shifting the thermal, demand,
  network or regulatory weight leaves the real-well order essentially unchanged
  (ρ ≥ 0.998). The regulatory weight moves scores but never ranks (ρ = 1.0 in
  every shift): it is close to a constant across the inventory at present.
- **Band changes concentrate at the Low / Do-not-pursue boundary (score ≈ 25).**
  Of 183 band changes in the combined run, 144 are Low → Do not pursue; of 126
  in the real-only run, 101 are.
- **High-priority wells (both synthetic, labelled).** Wealden Capture Test 4
  stays High in every scenario. Cornwall Geothermal Trial 1 drops to Medium when
  the thermal weight falls by 10 points or the economics weight rises by 10.
- **Real wells near the Medium line.** REMPSTONE 4Z crosses to Medium in 13 of
  the 31 scenarios and SALTFLEETBY 7X in 3. Say "within one band of Medium under
  weight stress", not "Medium".

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
