# Database schema

29 tables. PostgreSQL + PostGIS is the production target; the same models run on
SQLite with a haversine distance fallback.

Read [architecture.md](architecture.md) first if you have not — the tenancy
model in particular explains why `wells` has no `tenant_id`, which is the thing
most likely to look like a mistake otherwise.

---

## Conventions

Applied through `db/base.py`:

| Convention | Value |
|---|---|
| Primary keys | `UUID`, application-generated |
| Timestamps | `UTCDateTime`, a `TypeDecorator` that stores naive-UTC on SQLite and returns tz-aware on read |
| JSON columns | `JSONType` → `JSONB` on PostgreSQL, `JSON` elsewhere |
| Naming | `pk_<table>`, `fk_<table>_<column>_<ref>`, `ix_<column>` |
| Nullability | Nullable means *unknown*, never *zero*. This is enforced by convention and by the tests: a field that means zero is `NOT NULL DEFAULT 0`. |

---

## Tenancy

### `tenants`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `slug` | String(64) | Unique |
| `name` | String(255) | |
| `max_wells_per_month` | Integer | Quota |
| `max_analyses_per_day` | Integer | Quota |
| `is_active` | Boolean | |
| `created_at` | Timestamp | |

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK → tenants | `ON DELETE CASCADE` |
| `email` | String(320) | Unique **per tenant**, not globally |
| `hashed_password` | String(255) | PBKDF2-HMAC-SHA256, 600,000 iterations, per-user salt |
| `full_name` | String(255) | |
| `role` | String(32) | `owner` \| `engineer` \| `analyst` \| `viewer` |
| `is_active`, `is_verified` | Boolean | |
| `last_login_at` | Timestamp? | |
| `created_at`, `updated_at` | Timestamp | |

`ROLE_RANK` orders the roles for authorisation: viewer 0, analyst 1, engineer 2,
owner 3.

### `api_keys`

Machine credentials for ingestion and CI. Tokens are prefixed `ukg_` so the
auth dependency can tell a key from a JWT without a database round trip.

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | UUID FK? | Null for platform-wide keys |
| `name` | String(128) | |
| `prefix` | String(16) | Displayable portion |
| `hashed_key` | String(255) | The key itself is never stored |
| `scopes` | String(512) | Comma-separated |
| `expires_at`, `last_used_at` | Timestamp? | |
| `is_revoked` | Boolean | |

### `audit_logs`

Append-only. Written independently of the business tables so an entry survives
deletion of the thing it describes. No UPDATE or DELETE path is exposed.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK autoincrement | |
| `tenant_id`, `user_id` | UUID? | Deliberately not FKs with cascade |
| `action` | String(64) | e.g. `project.stage_changed` |
| `resource_type`, `resource_id` | String(64) | |
| `ip_address`, `user_agent` | String? | |
| `before`, `after`, `details` | JSON? | |
| `note` | Text? | |
| `created_at` | Timestamp, indexed | |

---

## Reference data — wells

### `wells`

**No `tenant_id`.** National reference data. Visibility is derived, not stored;
see `scoped_well_query`.

| Column | Type | Status semantics |
|---|---|---|
| `id` | UUID PK | |
| `well_id` | String | Human identifier, e.g. `UK-MOCK-CRN-001` |
| `well_name` | String | |
| `latitude`, `longitude` | Float | PostGIS `geography(Point)` on PostgreSQL |
| `region`, `county`, `licence` | String? | |
| `status` | Enum | `producing`, `non_producing`, `suspended`, `plugged_abandoned`, `abandoned`, `drilling`, `completed`, `exploration`, `unknown` |
| `original_purpose` | String? | `oil`, `gas`, `exploration`, … |
| `operator` | String? | |
| `drilling_year`, `commissioned_date`, `plugged_and_abandoned_date` | | |
| `total_depth_m`, `md_m`, `tvd_m` | Float? | `total_depth_m` is a roll-up; `md_m` and `tvd_m` are as-recorded |
| `max_deviation_deg` | Float? | |
| `is_deviated` | Boolean? | Tri-state: `NULL` = not recorded |
| `formation`, `basin` | String? | |
| `loggable`, `has_wellhead` | Boolean? | Tri-state |
| `casing_string`, `completion_type` | String? | |
| **`temperature_c`** | Float? | Roll-up. `NULL` means unknown, never 0 °C |
| **`temperature_depth_m`** | Float? | |
| **`temperature_status`** | Enum | The provenance of the roll-up |
| **`temperature_source`** | String? | Measurement method |
| **`temperature_confidence`** | Enum | `high`…`unknown` |
| **`temperature_variability_c`** | Float? | Spread between disagreeing sources |
| `bottomhole_pressure_bar`, `static_pressure_bar` | Float? | |
| `pressure_status` | Enum | |
| **`nearest_building_distance_m`** | Float? | Pre-computed demand proximity |
| **`annual_demand_kwh`** | Float? | |
| `number_of_buildings` | Integer? | |
| `demand_confidence` | Enum | |
| **`feasibility_score`** | Float? | 0–100, `NULL` until assessed |
| **`confidence_score`** | Float? | 0–1 |
| **`data_confidence`** | Enum | |
| **`recommendation`** | Enum? | |
| `data_completeness` | Float? | |
| `known_data_gaps` | JSON? | Field name → reason |
| **`source`** | String | Adapter name. Mock adapters are prefixed `mock_` |
| `source_url` | String? | |
| `dataset_version` | String? | |
| `is_mock` | Derived | `(source LIKE 'mock%')` |
| `analysed_at`, `analysis_version` | | |
| `created_at`, `updated_at` | Timestamp | |

Indexed on: `feasibility_score`, `recommendation`, `data_confidence`,
`temperature_c`, `nearest_building_distance_m`, `region`, `county`, `status`.

### `well_temperatures`

Every reading, not just the one that won the roll-up. This is what makes a
disagreement between sources visible.

| Column | Type | Notes |
|---|---|---|
| `well_id` | UUID FK → wells | |
| `depth_m` | Float | |
| `temperature_c` | Float | |
| `measurement_method` | Enum | `static_bht`, `circulation_test`, `max_dynamic`, `dts`, `gamma`, `regional_estimate`, `modelled`, … |
| `status` | Enum | The provenance of **this** reading |
| `confidence` | Enum | |
| `is_final_stabilised` | Boolean | False means it overstates what is producible |
| `geothermal_gradient_c_per_km` | Float? | |
| `evidence_id` | UUID? FK → evidence | |
| `source`, `source_url` | String | |
| `measured_at` | Date? | |
| `note` | Text? | |

Composite index on `(well_id, depth_m)`.

**Roll-up rule** (`_recompute_well_temperature`): prefer the deepest
*stabilised* reading. If sources disagree by more than a stated tolerance,
keep the deepest stabilised value and downgrade `temperature_confidence` and
record `temperature_variability_c`. A maximum dynamic temperature is never
promoted to the roll-up, because it overstates the producible figure.

### `well_integrity`

| Column | Type | Notes |
|---|---|---|
| `well_id` | UUID PK/FK → wells | One row per well |
| `status` | Enum | |
| `status_status` | Enum | Provenance of the integrity judgement itself |
| `confidence` | Enum | |
| `casing_condition_score`, `wellhead_condition_score`, `access_score`, `abandonment_score` | Float? | Each 0–1 |
| `requires_reequipment` | Boolean? | |
| `estimated_recompletion_capex_gbp` | Float? | |
| `estimated_recompletion_capex_status` | Enum | |
| `corrosion_evidence`, `scaling_evidence` | Text? | Free text, because it is a description of evidence |
| `gas_hazard` | Boolean? | |
| `last_integrity_check_date` | Date? | |
| `unknown_reasons` | Text? | Why the row is thin |
| `source`, `source_url` | String | |

Integrity carries 20% of the score and cannot be established from desk study. A
missing row is a data gap, not a good or bad condition.

### `well_logs`

| Column | Type | Notes |
|---|---|---|
| `well_id` | UUID FK | |
| `log_type` | Enum | |
| `logged_at` | Date? | |
| `top_depth_m`, `bottom_depth_m` | Float? | |
| `has_temperature_curve` | Boolean | |
| `storage_uri` | String? | Object storage |
| `is_public_domain` | Boolean | Licence-driven: whether the file can be surfaced |
| `tool_company`, `licence` | String? | |

---

## Reference data — geology

### `formations`, `geology`, `geothermal_settings`

Formation and basin dictionaries, per-well geology records (lithology, porosity,
permeability, and the geothermal gradient where it has been measured), and
regional settings. Gradient values carry their own `status` and `source`, because
a regional gradient is `MODELLED` while a log-derived one is `DERIVED`.

---

## Reference data — heat

### `buildings`

| Column | Type | Notes |
|---|---|---|
| `latitude`, `longitude` | Float | Spatially indexed |
| `building_type` | Enum | `detached`, `semi_detached`, `terraced`, `flat`, `commercial`, `industrial`, `public`, … |
| `postcode` | String? | |
| `floor_area_m2` | Float? | |
| **`annual_heat_demand_kwh`** | Float? | **Modelled from floor area and type, not metered** |
| `peak_heat_demand_kw` | Float? | |
| `required_supply_temperature_c` | Float? | |
| `current_fuel` | Enum? | |
| `connection_potential` | Enum | |
| `status` | Enum | |

### `heat_demands`

Per-well matched demand: `well_id`, `radius_m`, `building_count`,
`total_annual_demand_kwh`, `total_peak_demand_kw`,
`nearest_building_distance_m`, `weighted_centre_latitude/longitude`,
`dominant_building_type`, `average_required_supply_temperature_c`,
`demand_confidence`, `spatial_dialect`.

### `heat_networks`, `energy_prices`

Known heat networks with their operator, technology and length; energy prices by
fuel and period with their source and vintage. Prices carry a `source` and a
date, because a 2019 price presented without its date is an assumption wearing
a fact's clothes.

---

## Evidence and traceability

### `datasets`

The provenance of everything loaded.

| Column | Type | Notes |
|---|---|---|
| `source` | String | |
| `name`, `description` | String | |
| `source_url` | String? | |
| `download_date`, `published_date` | Date? | |
| `licence` | String? | |
| `version` | String | |
| `reliability` | Enum | Source tier |
| `quality_score` | Float | 0–1 from the validation layer |
| `row_count` | Integer? | |
| `validation_summary` | JSON? | |
| **`is_mock`** | Boolean | Propagates to every watermarked view |
| `status`, `last_ingested_at` | | |

### `evidence`

| Column | Type | Notes |
|---|---|---|
| `well_id`, `analysis_id` | UUID? | A document can support either or both |
| `source`, `source_title`, `source_url` | String | |
| `source_date` | Date? | |
| `document_type` | Enum? | |
| `reliability`, `relevance`, `quality` | Float | 0–1 each; reliability feeds the confidence axis |
| `excerpt`, `page_reference` | String? | |
| `status` | Enum | |
| `is_mock` | Boolean | |

### `claims`

A specific assertion attributed to a field.

| Column | Type | Notes |
|---|---|---|
| `well_id` | UUID FK | |
| `analysis_id` | UUID? | |
| `evidence_id` | UUID? | `NULL` → the claim is an `ASSUMPTION`, enforced by the discipline gate |
| `assumption_id` | UUID? | |
| `field_name` | String | |
| `claim` | Text | |
| `value` | JSON? | |
| `status` | Enum | |
| `confidence` | String? | |
| `agent` | String? | Which agent made it |
| `is_critical` | Boolean | |

### `assumptions`

Every non-`None` parameter as a traceable row: `key`, `value`, `unit`,
`rationale`, `source`, `is_default`. A what-if run writes its overrides here, so
"this figure assumed 40 L/s" is a query, not an inference.

### `calculation_traces`

One row per `CalcResult`. This is the audit trail.

| Column | Type | Notes |
|---|---|---|
| `analysis_id`, `well_id` | UUID | |
| `function_name` | String | e.g. `thermal_power` |
| `sequence` | Integer | Execution order within a run |
| `inputs`, `input_units`, `intermediate_values` | JSON | |
| `formula` | Text | The literal formula used |
| `result` | Float? | `NULL` = unknown |
| `result_unit` | String | |
| `status` | Enum | |
| `assumptions`, `sources` | JSON | |
| `warnings` | JSON | |
| `confidence` | Float? | |
| `engine_version` | String | |

Indexed on `(well_id, function_name)`.

---

## Analysis

### `analyses`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `NULL` for a what-if run, which is never persisted |
| `well_id` | UUID FK | |
| `tenant_id` | UUID | Owning tenant. **This is what makes a well visible** |
| `project_id`, `scenario_id` | UUID? FK | |
| `status` | Enum | `pending`/`running`/`complete`/`failed` |
| `configuration`, `recommended_configuration` | Enum | |
| `parameters` | JSON | Resolved for this run |
| `overrides` | JSON | What the user changed |
| `component_scores` | JSON | Eight components with contributions |
| **`feasibility_score`** | Float | |
| **`confidence_score`** | Float | |
| `confidence_band` | Enum | |
| `recommendation` | Enum | |
| `recommendation_rationale`, `next_action` | | |
| `risk_score` | Float | Aggregate exposure |
| `data_gaps`, `unknowns`, `warnings` | JSON | Three separate lists, never merged |
| `calculation_trace` | JSON | Mirrors the trace rows for a single-call read |
| `pipeline_version`, `score_version` | String | Version travel |
| `started_at`, `completed_at` | Timestamp? | |

Indexed on `(well_id, created_at)` — the composite that makes "latest analysis
for this well" a single index lookup rather than a window function.

### `scenarios`

Named input sets with a probability weight. The weight is explicitly labelled an
assumption: it is the user's belief, not a fitted distribution, and the scenario
panel warns when the weights do not sum to 1.

### `financial_models`

Persisted cash flows: `capex_gbp`, `opex_gbp_per_year`, `discount_rate`,
`lifetime_years`, `annual_heat_kwh`, `lcoh_p_per_kwh`, `npv_gbp`, `irr_pct`,
`payback_years`, `break_even_heat_price_p_per_kwh`, and the discounted
cash-flow series.

### `risks`

One row per risk per analysis: `category`, `title`, `description`, `likelihood`,
`probability`, `impact`, `impact_value`, `uncertainty`, `risk_score`,
`uncertainty_adjusted_score`, `severity`, `is_critical`, `evidence`,
`mitigation`, `addresses_data_gap`.

### `validation_actions`

Data-gathering steps derived from recorded gaps: `action_type`, `title`,
`description`, `priority`, `rationale`, `addresses_risk_ids`,
`addresses_data_gaps`, `estimated_cost_gbp`, `estimated_duration_days`,
`status`. Explicitly not a project plan.

### `regulatory_requirements`

Per configuration and jurisdiction: `authority`, `is_mandatory`,
`typical_lead_time_months`, `estimated_cost_gbp`, `source`, `is_mock`.
Indicative only — the interface says a screening tool cannot establish what a
regulator will actually require.

---

## Projects

### `projects`

`slug`, `name`, `description`, `stage` (ten values, `sourcing` → `operating`,
plus `rejected`), `target_region`, `target_scenario`, `is_archived`,
`archived_at`, timestamps. Unique on `slug`.

### `project_wells`

Join table: `project_id`, `well_id`, `role` (`candidate`/`primary`/`backup`),
`added_at`. **Inserting a row here is what makes a well visible to a tenant.**

---

## Migrations

Alembic, in `backend/alembic/`. The URL comes from application settings rather
than `alembic.ini`, because three sources of truth for a database URL is how a
migration ends up applied to the wrong database.

`render_as_batch` is enabled on SQLite so one migration is valid on both
backends — otherwise the test suite would be validating a schema that production
never sees. PostGIS and pgvector extensions are created outside Alembic's
transaction with dialect guards, because `CREATE EXTENSION` cannot run inside a
transaction in every setup and SQLite must not attempt it.

```bash
cd backend
python -m alembic upgrade head
python -m alembic revision --autogenerate -m "add heat_pump column"
```

> The generated `script.py.mako` imports `app.db.base` unconditionally. Autogenerate
> emits fully-qualified references such as `app.db.base.JSONType` for the custom
> types; without that import every generated migration fails with
> `NameError: name 'app' is not defined`.