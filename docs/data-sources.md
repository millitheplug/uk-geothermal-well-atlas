# Data sources

## The rule this project follows

**No production well data is fabricated.** The development datasets are clearly
marked synthetic, are structurally identical to the real data, and are replaced
by adapters pointed at real sources without any change to the application.

The reason is not squeamishness about where numbers come from. It is that the
platform's entire claim is that its figures are traceable and honest about their
provenance. Shipping a well record that looks like real UK borehole data but is
not would undermine every other guarantee in the product — and it would fail in
the worst possible way, quietly, in a screenshot someone forwards.

---

## Development datasets

Nine adapters, all `is_mock = True`, all registered in
`app/data_import/registry.py`:

| Adapter | `source` | Produces | Volume |
|---|---|---|---|
| `mock_wells` | `mock_nsta` | Well records | 20 |
| `mock_temperatures` | `mock_nsta_temps` | Temperature readings, several per well including disagreements | 43 |
| `mock_integrity` | `mock_nsta_integrity` | Integrity rows | 20 |
| `mock_geology` | `mock_bgs_geology` | Formation and basin context | 20 |
| `mock_buildings` | `mock_heat_demand` | Buildings with modelled demand | 341 |
| `mock_demand_areas` | `mock_heat_demand_areas` | Settlement-level demand | — |
| `mock_heat_networks` | `mock_heat_networks` | Known heat networks | — |
| `mock_energy_prices` | `mock_energy_prices` | Energy price book | — |
| `mock_regulatory` | `mock_regulatory` | Consent requirements | — |

The names deliberately mirror what the real sources would be (`mock_nsta` for
the NSTA well dataset, `mock_bgs_geology` for BGS), so the provenance shown in
the interface reads the way it will once the real adapters land.

### What makes them realistic rather than convenient

The point of the mock data is to exercise the paths that matter. Four properties
were built in deliberately:

**Disagreeing temperature sources.** Several wells carry multiple readings that
disagree by more than the tolerance threshold. The roll-up prefers the deepest
*stabilised* reading, downgrades confidence, and records
`temperature_variability_c`. The interface shows the spread. This is the path that
a dataset of perfectly consistent values would never exercise, and it is the one
that most affects the confidence score.

**Wells with no temperature at all.** Six of the twenty have none. Their thermal
potential is unknown, the pipeline short-circuits rather than guessing, and the
recommendation reflects that. Without them the dashboard would never show a
coverage gap and the whole "unknown is not zero" discipline would be untested.

**A spread of recommendations and confidence bands.** Not all wells are good. A
mock dataset of uniformly excellent candidates would make the scoring look
correct for the wrong reasons.

**Non-stabilised readings.** Maximum dynamic temperatures are present and are
never promoted to the roll-up, because they overstate what is producible.

### How synthetic data is marked

The `is_mock` flag is not decorative. It propagates:

```
Adapter.is_mock
  → datasets.is_mock
  → wells.source starts with "mock_"  →  wells.is_mock (derived)
  → X-Is-Mock-Data response header
  → /admin/health .is_mock_data
  → the map's "Synthetic data" marker in the header
  → MockDataBanner on any view drawing on it
  → .mock-watermark / .mock-badge CSS, if a view opts into the watermark
```

Filtering with `include_mock=false` removes synthetic wells from the inventory,
the map and the candidate ranking entirely. Synthetic wells are individually
tinted in tables and on the map, so a mixed view cannot be misread as
wholly real.

---

## Real sources

These are the datasets the real adapters should read. Licences must be confirmed
against each publisher's terms before any ingest — the table is a starting point
for implementation, not a clearance to redistribute.

### Wells and completions

| Source | Publisher | Contents | Notes |
|---|---|---|---|
| **NSTA historic well data** | North Sea Transition Authority | UK onshore and offshore well headers, operators, licences, spud and abandonment dates, coordinates | The canonical well inventory. Licence terms apply to redistribution; the platform is not for public indexing, and the UI sets `robots: noindex` accordingly. |
| **NSTA well operations reports** | NSTA | Reports on individual wells, sometimes including temperature surveys | Often PDF. Expect an extraction step and a per-document evidence record. |
| **BGS borehole index** | British Geological Survey | Borehole locations, stratigraphy, final depths | Good for cross-checking depth and formation against operator records. |
| **BGS geothermal gradient maps** | BGS | Regional geothermal gradient and surface heat flow | Regional values are `MODELLED`, never `MEASURED`. |

### Geology

| Source | Publisher | Contents |
|---|---|---|
| **BGS GeoIndex / BGS 1:50,000 mapping** | BGS | Lithostratigraphy, formation polygons |
| **BGS geophysical logs** | BGS | Density, neutron, sonic — from which a formation temperature can be estimated |

A log-derived formation temperature is a real estimate and should be labelled
`ESTIMATE` or `MODELLED` with the log named. It is not a stabilised bottom-hole
survey and must never be labelled `MEASURED`.

### Heat demand

| Source | Publisher | Contents | Caveat |
|---|---|---|---|
| **DESNZ / MHDRG postcode-level electricity and gas consumption** | DESNZ | Domestic energy consumption by postcode | Local authority geography, not buildings |
| **ONS EPC register** | Office for National Statistics | EPC ratings, floor area, wall and glazing properties, for most UK buildings | Self-reported and not complete; EPC data underpins the standard factors |
| **OS OpenMap Local Building** | Ordnance Survey | Building outlines and geometry | Lets floor area be computed from footprint and storey count |
| **UK HVO / DESNZ heat network records** | DESNZ | Known heat networks and their operators | Sparse and manually maintained |
| **NOMIS** | ONS | Settlement-level and regional demographics | Useful for demand-area weights |

**Building demand in this platform is modelled**, from floor area and building
type using standard UK factors. It is a screening estimate for comparing
locations. It is not a heat audit, and it will not reveal that a single
industrial estate holds more demand than a thousand houses. Every surface that
shows it says so.

### Prices

| Source | Publisher | Contents |
|---|---|---|
| **DESNZ Quarterly Energy Prices** | DESNZ | Industrial and domestic electricity and gas prices, published quarterly |
| **Ofgem price cap** | Ofgem | Default tariff caps |

Prices carry a vintage. A 2019 price presented without its date is an assumption
wearing a fact's clothes, so `energy_prices` stores `source`, `published_date`
and the period covered.

### Regulatory

| Source | Publisher | Contents |
|---|---|---|
| **Water Resources Act 1998, Schedule 2** | legislation.gov.uk | Abstraction and impoundment licensing |
| **Environment Agency abstraction registers** | Environment Agency | Licences, licence numbers, abstraction volumes |
| **Wells of more than 20 m: requirements** | HSE | Notification and reporting duties |
| **MRA / CPR 2011 requirements** | HSE / Planning Inspectorate | Borehole status where MRA applies |
| **Planning: minerals and energy** | MHCLG, devolved authorities | National and devated planning policy |

Regulatory content in this platform is **indicative**. A screening tool cannot
establish what a regulator will actually require, and the interface says so where
the catalogue appears.

---

## Swapping in real data

The adapters implement one interface, so replacing a mock adapter with a real one
is a registration change plus a new class. No application code changes.

```python
class Adapter(Protocol):
    source: str
    is_mock: bool

    def run(self, *, limit: int | None = None, dry_run: bool = False) -> ImportResult: ...
```

Then in `app/data_import/registry.py`:

```python
from app.data_import.adapters.nsta_wells import NstaWellAdapter
from app.data_import.adapters.nsta_temperatures import NstaTemperatureAdapter

ADAPTERS = {
    "nsta_wells": NstaWellAdapter,
    "nsta_temperatures": NstaTemperatureAdapter,
    # ... the rest
}
```

An adapter's job is to emit normalised, validated records and an
`ImportResult`. Anything the source provides and the platform does not model
should be preserved as an `evidence` record with a citation, not discarded —
that is how a figure keeps its provenance.

### Before switching off the mock data

A checklist, because switching is easy and forgetting one step produces results
that look right and are not:

1. **`is_mock = False`** on the new adapter. This is what removes the
   watermarks, and it is the step most likely to be left as `True`.
2. **Licence recorded** in `datasets.licence`. If the terms forbid
   redistribution, the platform's no-index posture and tenant scoping matter
   much more than usual.
3. **`source_url` set** so every well's provenance resolves to a real document.
4. **`source` name must not start with `mock_`**, because `wells.is_mock` is
   derived from that prefix.
5. **Validation summaries reviewed** — `records_rejected` should be small, and
   every rejection should have a reason. A large rejection count with plausible
   row counts usually means a column mapping is wrong.
6. **`temperature_status` mapping reviewed.** A source that reports a formation
   temperature is not reporting a stabilised bottom-hole survey.
7. **Re-run bootstrap** and confirm `python -m scripts.cli check` reports
   `is_mock_data: false`.

### Migration of the existing development data

The mock rows are not deleted automatically — deleting them on adapter swap
would destroy the record of what a given analysis was computed against, and an
analysis that was run and then withdrawn is part of the record of why a decision
was taken. Filter with `include_mock=false` instead.

To remove them for good, delete analyses and projects first (foreign keys), then
the wells, then the datasets. Export the analyses first if you want them.

---

## Normalisation

`app/data_normalisation/normalise.py` maps source-specific spellings onto the
enums. This is where a lot of real-ingest work lives, because every publisher
spells things differently:

| Source spelling | Normalised to |
|---|---|
| `"static bottom hole temperature"`, `"static_bht"` | `static_bht` |
| `"thermal recovery test"`, `"circulation_test"` | `circulation_test` |
| `"max_dynamic"`, `"maximum dynamic temperature"` | `max_dynamic` |
| `"dts"`, `"dts_reprocessed"` | `dts` |
| `"gamma"`, `"regional_estimate"`, `"analogue"` | their own enums, all `ESTIMATE` |
| `"modelled"`, `"petrophysical_model"`, `"basin_model"` | `MODELLED` |
| `"P&A"`, `"plugged and abandoned"`, `"abandoned"` | `plugged_abandoned` |
| `"non-producing"`, `"non producing"`, `"shut in"` | `non_producing` |

A value that cannot be normalised is **not** silently defaulted. It is either
mapped to `unknown` or rejected with a reason, and both outcomes are counted in
the `ImportResult`.

---

## Validation

`app/data_validation/validators.py` runs on ingest. Rows are rejected with a
reason rather than dropped silently, because a silent drop is indistinguishable
from a source that did not contain the data.

Checks include: coordinate plausibility within the UK bounding box; depth
greater than zero and consistent between MD and TVD; temperature within
physically possible bounds for depth; dates in a coherent order
(commissioned before abandonment); demand per unit floor area within a plausible
range; and casing or completion strings matching known patterns.

`0 records rejected` on a real import is itself suspicious. It usually means the
validator is not running, not that the source is perfect.