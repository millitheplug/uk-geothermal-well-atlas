# API

Base URL: `http://localhost:8000/api/v1` (configurable with `API_PREFIX`).

Interactive documentation is at `/docs` (Swagger) and `/redoc`.

---

## Conventions

### Authentication

Every endpoint requires a bearer token. There is no anonymous access and no
development bypass — a build that runs open locally and closed in production is a
build where nobody has tested the auth path.

```http
Authorization: Bearer <access_token>
```

API keys are also accepted and are recognised by their `ukg_` prefix, so the
dependency can tell a key from a JWT without a database round trip.

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"..."}' | jq -r .access_token)
```

### Errors

Standard FastAPI shapes. `detail` is always a human-readable sentence explaining
what to do, not a code.

```json
{ "detail": "well not found, or not visible to this tenant. Wells are national data but are only reachable once they are referenced by a project or analysis belonging to your organisation." }
```

| Status | Meaning |
|---|---|
| 400 | Invalid query parameter |
| 401 | Missing or invalid credentials |
| 403 | Authenticated but not permitted (role, scope, tenant) |
| 404 | Not found, **or not visible to this tenant** |
| 422 | Request validation failed — the body names the offending field |
| 429 | Rate limit or daily quota |

The 404 is used for invisible resources deliberately. A 403 would confirm that a
well exists, which is itself information the caller is not entitled to.

### Headers

| Header | Direction | Purpose |
|---|---|---|
| `X-Request-ID` | Response | Correlates a request with a log line |
| `X-Spatial-Dialect` | Response | `postgis` or `haversine` |
| `X-Is-Mock-Data` | Response | `true` when any contributing dataset is synthetic |
| `X-RateLimit-Remaining` | Response | Requests left in the current window |

The mock-data header exists so that a screenshot of a response is
self-identifying. A JSON blob without it is ambiguous; with it, not.

### Pagination

`limit` (1–1000, default 50) and `offset` (default 0). Responses carry `total`,
`limit` and `offset`.

---

## Health

### `GET /admin/health`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "environment": "development",
  "database": "sqlite",
  "spatial_dialect": "haversine",
  "redis": "unavailable",
  "llm": "mock",
  "is_mock_data": true
}
```

`llm` is `mock` when no API key is configured. That is not a degraded mode worth
hiding: no agent performs a calculation, so results are identical either way and
only the prose differs.

---

## Authentication

### `POST /auth/login`

```json
{ "email": "you@example.com", "password": "..." }
```

→

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 43200,
  "user": { "id": "...", "email": "...", "full_name": "...", "role": "analyst" }
}
```

### `GET /auth/me`

The current user.

### `GET /auth/audit`

Audit entries for the caller's tenant. Append-only, scoped.

### `POST /auth/api-keys`

Issues a long-lived machine credential. The key is returned **once**, in full,
and only its hash is stored.

---

## Wells

### `GET /wells`

Search and filter the inventory. All parameters optional.

| Parameter | Type | Notes |
|---|---|---|
| `search` | string | Name, ID, operator, licence |
| `status[]` | enum[] | Multi-value |
| `original_purpose[]`, `region[]` | string[] | Multi-value |
| `operator`, `licence`, `county`, `formation` | string | Single |
| `min_temperature_c`, `max_temperature_c` | float | |
| `min_depth_m`, `max_depth_m` | float | |
| `min_score`, `max_score` | float | 0–100 |
| `min_confidence_score` | float | 0–1 |
| `min_data_confidence[]` | enum[] | |
| `drilling_year_from`, `drilling_year_to` | int | |
| `has_temperature`, `has_integrity` | bool | |
| `recommendation[]` | enum[] | |
| `min_nearest_demand_m`, `max_nearest_demand_m` | float | |
| `min_annual_demand_kwh` | float | |
| `centre_lat`, `centre_lon`, `radius_m` | float | Circular search |
| `include_mock` | bool | Default `true` |
| `include_claimable` | bool | Default `false`, see below |
| `limit`, `offset` | int | |
| `order_by` | string | Allow-listed, not interpolated |
| `descending` | bool | |

→

```json
{
  "items": [
    {
      "id": "3f2b...",
      "well_id": "UK-MOCK-CRN-001",
      "well_name": "Cornwall Geothermal Trial 1",
      "latitude": 50.2660, "longitude": -5.0507,
      "region": "South West England", "county": "Cornwall",
      "status": "non_producing",
      "original_purpose": "exploration",
      "operator": "Example Energy",
      "drilling_year": 1988,
      "total_depth_m": 2410.0,
      "temperature_c": 74.2,
      "temperature_status": "MEASURED",
      "temperature_confidence": "medium",
      "data_confidence": "medium",
      "feasibility_score": 67.6,
      "confidence_score": 0.551,
      "recommendation": "HIGH PRIORITY",
      "is_mock": true
    }
  ],
  "total": 20, "limit": 50, "offset": 0,
  "spatial_dialect": "haversine"
}
```

`temperature_status` is present on every row because the temperature without its
provenance is the exact failure the platform exists to prevent.

**Tenancy.** Only wells referenced by one of the caller's projects or analyses
are returned. This has caught out two endpoints during development, which is why
the rule lives in one function.

**Claimable wells.** Discovery endpoints (`/wells`, `/wells/map`) accept
`include_claimable=true`, which additionally returns wells that sit in *no
project at all* — national reference data nobody has adopted yet. It defaults to
`false` so existing inventories and provenance tests keep their exact meaning;
discovery is opt-in. A well that appears in *any* project (even another
tenant's) is never claimable, so adoption cannot be used to reach across a
tenant boundary. Claimable rows carry a `claimable` flag; the UI offers to adopt
one into one of your projects (`POST /projects/{uuid}/wells`), after which the
normal tenancy rule applies.

### `GET /wells/map`

GeoJSON `FeatureCollection` for the map. Heavier filters than `/wells` but a much
smaller payload: terse property names because every one is used in the popup.

```json
{
  "type": "FeatureCollection",
  "spatial_dialect": "haversine",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [-5.0507, 50.2660] },
      "properties": {
        "id": "3f2b...", "well_id": "UK-MOCK-CRN-001",
        "name": "Cornwall Geothermal Trial 1",
        "score": 67.6, "confidence": 0.551,
        "confidence_band": "medium",
        "recommendation": "HIGH PRIORITY",
        "temperature_c": 74.2, "temperature_status": "MEASURED",
        "depth_m": 2410.0, "status": "non_producing",
        "region": "South West England", "operator": "Example Energy",
        "is_mock": true
      }
    }
  ]
}
```

`id` is the UUID; `well_id` is the human identifier. The UI uses `id` for
navigation and `well_id` for display. When `include_claimable=true` is passed,
each feature also carries `"claimable": true` for wells in no project, so the map
can route a click to the adopt panel instead of a 404.

### `GET /wells/facets`

Distinct values and ranges for the filter panel.

```json
{
  "statuses": ["abandoned", "completed", "non_producing", "producing", "suspended"],
  "purposes": ["exploration", "gas", "oil"],
  "regions": ["East Midlands", "North West England", "South West England"],
  "counties": ["Cornwall", "Lancashire"],
  "recommendations": ["DO NOT PURSUE", "HIGH PRIORITY", "LOW PRIORITY", "MEDIUM PRIORITY"],
  "confidence_bands": ["high", "low", "medium", "unknown", "very_low"],
  "temperature_range_c": { "min": 21.4, "max": 118.3 },
  "depth_range_m": { "min": 610.0, "max": 3410.0 },
  "score_range": { "min": 12.4, "max": 84.1 },
  "total_wells": 20
}
```

Not tenant-scoped: this is metadata about the shape of the national inventory.
An earlier version joined against a `select(Well.id)` subquery, which SQLAlchemy
correctly warned was a cartesian product — the multiplication was hidden by
`DISTINCT` in the result but not in the scan.

### `GET /wells/{well_uuid}`

The full record in one request: temperatures, integrity, logs and provenance.
One request rather than four, so the page cannot render a score with no evidence
behind it.

```json
{
  "well_id": "UK-MOCK-CRN-001",
  "well_name": "Cornwall Geothermal Trial 1",
  "latitude": 50.2660, "longitude": -5.0507,
  "licence": "EX/2020/118",
  "commissioned_date": "1988-04-19",
  "md_m": 2410.0, "tvd_m": 2398.0,
  "max_deviation_deg": 3.2, "is_deviated": true,
  "formation": "Cornwall granite", "basin": "West Penwith",
  "temperature_c": 74.2,
  "temperature_depth_m": 2380.0,
  "temperature_source": "static_bht",
  "temperature_status": "MEASURED",
  "temperature_confidence": "medium",
  "temperature_variability_c": 2.1,
  "casing_string": "9 5/8\" to 480 m; 7\" to 2,100 m",
  "completion_type": "open_perforated",
  "has_wellhead": true, "loggable": true,
  "data_completeness": 0.82,
  "known_data_gaps": { "flow_test": "no flow test has been performed" },
  "source": "mock_nsta_wells",
  "source_url": "https://example.invalid/synthetic",
  "dataset_version": "2026.1",
  "temperatures": [
    {
      "id": "...",
      "depth_m": 2380.0, "temperature_c": 74.2,
      "measurement_method": "static_bht",
      "status": "MEASURED",
      "confidence": "medium",
      "is_final_stabilised": true,
      "geothermal_gradient_c_per_km": 27.4,
      "source": "Well completion report",
      "measured_at": "1988-11-02"
    }
  ],
  "integrity": {
    "status": "requires_reequipment",
    "status_status": "ESTIMATE",
    "confidence": "low",
    "requires_reequipment": true,
    "estimated_recompletion_capex_gbp": 480000.0,
    "estimated_recompletion_capex_status": "ESTIMATE",
    "gas_hazard": null,
    "last_integrity_check_date": null,
    "unknown_reasons": "No integrity inspection has been recorded since abandonment in 1994."
  },
  "logs": [
    { "log_type": "gamma", "logged_at": "1988-04-19", "has_temperature_curve": false, "is_public_domain": true }
  ]
}
```

### `GET /wells/{well_uuid}/demand`

Buildings near a well and their aggregated demand.

| Parameter | Default | Notes |
|---|---|---|
| `radius_m` | 2000 | 0–20,000 |
| `min_connection_potential` | — | |
| `limit` | 100 | 1–500 |

```json
{
  "well_id": "UK-MOCK-CRN-001",
  "radius_m": 2000.0,
  "building_count": 41,
  "total_annual_demand_kwh": 1284000.0,
  "total_peak_demand_kw": 812.0,
  "nearest_building_distance_m": 340.2,
  "weighted_centre_latitude": 50.2701,
  "weighted_centre_longitude": -5.0442,
  "dominant_building_type": "detached",
  "average_required_supply_temperature_c": 65.0,
  "demand_confidence": "low",
  "notes": ["Demand is modelled from floor area and building type, not metered."],
  "spatial_dialect": "haversine",
  "buildings": [
    {
      "id": "...",
      "building_type": "detached",
      "latitude": 50.2712, "longitude": -5.0438,
      "postcode": "TR21 3AA",
      "floor_area_m2": 124.0,
      "annual_heat_demand_kwh": 31200.0,
      "peak_heat_demand_kw": 7.2,
      "required_supply_temperature_c": 65.0,
      "current_fuel": "gas_central",
      "connection_potential": "good",
      "distance_m": 340.2
    }
  ]
}
```

### `GET /wells/{well_uuid}/evidence`

Evidence documents and claims behind a well's conclusions. This is the endpoint
that makes the score answerable: every figure on the detail page should be
traceable from here to a source.

---

## Analyses

### `POST /analyses`

Runs the deterministic pipeline and, unless told otherwise, the agents.

```json
{
  "well_id": "3f2b8c14-...",
  "inputs": { "flow_rate_lps": 25.0 },
  "include_ai_agents": true
}
```

→ (abridged)

```json
{
  "analysis_id": "9b1e...",
  "well_id": "3f2b...",
  "well_name": "Cornwall Geothermal Trial 1",
  "pipeline_version": "0.1.0",
  "configuration": "closed_loop_plus_heat_pump",
  "recommended_configuration": "closed_loop_plus_heat_pump",
  "source_temperature_c": 74.2,
  "temperature_status": "MEASURED",
  "thermal_output_kw": 452.0,
  "thermal_output_low_kw": 371.0,
  "thermal_output_high_kw": 533.0,
  "thermal_output_status": "ESTIMATE",
  "heat_pump_cop": 3.4,
  "heat_pump_electricity_kw": 133.0,
  "delivered_heat_kw": 402.0,
  "network_length_m": 340.0,
  "network_heat_loss_kw": 9.9,
  "network_loss_fraction": 0.021,
  "nearest_building_distance_m": 340.2,
  "annual_heat_kwh": 1326000.0,
  "capex_gbp": 1240000.0,
  "opex_gbp_per_year": 74000.0,
  "lcoh_p_per_kwh": 14.2,
  "npv_gbp": 412000.0,
  "irr_pct": 8.7,
  "payback_years": 11.4,
  "break_even_heat_price_p_per_kwh": 11.8,
  "feasibility_score": 67.6,
  "confidence_score": 0.551,
  "confidence_band": "medium",
  "component_scores": { "thermal": 71.0, "integrity": 58.0, "demand": 66.0, "economics": 61.0, "network": 82.0, "geometry": 74.0, "regulatory": 79.0, "data_confidence": 55.0 },
  "recommendation": "HIGH PRIORITY",
  "recommendation_rationale": ["Feasibility score and evidence confidence are both strong enough to justify detailed due diligence and a site visit."],
  "next_action": "Commission a flow test to replace the assumed flow rate with a measurement.",
  "risk": { "aggregate_score": 47.2, "risk_count": 11, "critical_count": 0, "risks": [ ... ] },
  "confidence_detail": { "score": 0.551, "band": "medium", "axes": { ... }, "conflicting_sources": [], "unknowns": [ ... ] },
  "data_gaps": ["no flow test has been performed on this well"],
  "unknowns": ["achievable injection pressure at the completion depth"],
  "warnings": ["Thermal output scales linearly with the assumed flow rate; no flow test exists."],
  "calculation_trace": [
    {
      "function_name": "thermal_power",
      "inputs": { "flow_rate_lps": 25.0, "source_temperature_c": 74.2, "return_temperature_c": 55.0 },
      "input_units": { "flow_rate_lps": "L/s", "source_temperature_c": "degC" },
      "formula": "Q = (flow_lps * density / 1000) * cp * (T_source - T_return) * utilisation_factor",
      "result": 452.0,
      "result_unit": "kW",
      "status": "ESTIMATE",
      "assumptions": [ { "key": "flow_rate_lps", "value": 25.0, "unit": "L/s", "rationale": "..." } ],
      "sources": [ { "citation": "..." } ],
      "intermediate_values": { "mass_flow_kg_s": 25.0, "delta_t_k": 19.2 },
      "warnings": [],
      "confidence": 0.55,
      "engine_version": "0.1.0"
    }
  ],
  "parameters": { ... },
  "evidence": [ ... ],
  "claims": [ ... ],
  "regulatory_requirements": [ ... ],
  "validation_actions": [ ... ],
  "agent_outputs": { "thermal_interpreter": { ... }, ... },
  "executive_summary": "...",
  "report_markdown": "# UK Geothermal Well Atlas — ..."
}
```

Note the status labels throughout. `temperature_status` is `MEASURED` while
`thermal_output_status` is `ESTIMATE`, because the input is measured and the
output is not: no flow test has been performed. That distinction is the product.

### `GET /analyses`

List, filtered by `well_id`, `recommendation`, `min_score`, paginated.

### `GET /analyses/{analysis_uuid}`

One stored analysis.

### `GET /analyses/{analysis_uuid}/progress`

Stage-by-stage progress for an in-flight run.

```json
{
  "analysis_id": "9b1e...",
  "status": "running",
  "stage": "economics",
  "completed_stages": ["data_validation", "geology", "temperature", "well_integrity", "heat_demand", "engineering"],
  "stage_messages": { "temperature": "Source temperature taken from the deepest stabilised survey at 2,380 m." },
  "percent_complete": 68,
  "error_message": null
}
```

### `GET /analyses/{analysis_uuid}/trace`

The calculation trace as a typed list, without the rest of the result.

### `GET /analyses/{analysis_uuid}/report`

The 19-section report as `text/markdown`.

### `POST /analyses/what-if`

Recalculate with overrides. **Never persisted** — `analysis_id` comes back `null`.

```http
POST /analyses/what-if?well_uuid=3f2b...&configuration=closed_loop
{ "flow_rate_lps": 40.0, "heat_price_p_per_kwh": 22.0 }
```

### `POST /analyses/{well_uuid}/scenarios`

Runs several input sets through the same engine and returns them side by side,
with the expected value under the supplied probability weights.

```json
[
  { "name": "conservative", "probability_weight": 0.25, "inputs": { "flow_rate_lps": 12 } },
  { "name": "central",      "probability_weight": 0.5,  "inputs": { "flow_rate_lps": 25 } },
  { "name": "optimistic",   "probability_weight": 0.25, "inputs": { "flow_rate_lps": 40 } }
]
```

→

```json
{
  "well_id": "UK-MOCK-CRN-001",
  "scenarios": [
    { "name": "conservative", "thermal_output_kw": 268.0, "lcoh_p_per_kwh": 27.4, "npv_gbp": -980000.0, "irr_pct": null, "feasibility_score": 41.2, "recommendation": "LOW PRIORITY" },
    { "name": "central",      "thermal_output_kw": 452.0, "lcoh_p_per_kwh": 14.2, "npv_gbp": 412000.0,  "irr_pct": 8.7,  "feasibility_score": 67.6, "recommendation": "HIGH PRIORITY" },
    { "name": "optimistic",   "thermal_output_kw": 691.0, "lcoh_p_per_kwh": 9.8,  "npv_gbp": 1810000.0,"irr_pct": 15.2, "feasibility_score": 78.9, "recommendation": "HIGH PRIORITY" }
  ],
  "expected_lcoh_p_per_kwh": 16.4,
  "expected_npv_gbp": 413000.0,
  "spread_lcoh_p_per_kwh": 17.6,
  "notes": ["A wide spread indicates that this assessment rests on inputs nobody has measured."]
}
```

`irr_pct` is `null` for the conservative case because its cash flow never changes
sign. That is `UNKNOWN`, not 0%.

---

## Dashboard

### `GET /dashboard/national`

Headline position. Note that the capacity total is a sum over **measured** wells
only, and carries its own status for exactly that reason.

```json
{
  "total_wells": 20,
  "wells_with_temperature": 14,
  "wells_without_temperature": 6,
  "candidate_wells": 14,
  "high_potential_wells": 3,
  "average_temperature_c": 68.4,
  "average_depth_m": 2180.0,
  "total_estimated_thermal_capacity_mwt": 2.41,
  "total_estimated_thermal_capacity_status": "ESTIMATE",
  "nearby_heat_demand_opportunity_gwh": 412.0,
  "wells_needing_more_data": 9,
  "recommendation_breakdown": { "HIGH PRIORITY": 3, "MEDIUM PRIORITY": 5, "LOW PRIORITY": 4, "DO NOT PURSUE": 2 },
  "confidence_breakdown": { "high": 1, "medium": 8, "low": 4, "very_low": 1, "unknown": 6 },
  "status_breakdown": { "producing": 2, "non_producing": 6, "suspended": 4, "plugged_abandoned": 5, "abandoned": 3 },
  "purpose_breakdown": { "oil": 6, "gas": 5, "exploration": 9 },
  "region_breakdown": { "South West England": 5, "East Midlands": 6, "North West England": 4 },
  "score_histogram": [ { "range": "0-20", "lower": 0, "upper": 20, "count": 2 }, ... ],
  "risk_category_totals": { "well_integrity": 184.2, "temperature_uncertainty": 141.8, ... },
  "is_mock": true,
  "caveats": [
    "Capacity total aggregates only wells with a temperature measurement; unmeasured wells are excluded rather than counted as zero.",
    "Scores are model outputs at the stated version and are not comparable with results from an earlier version."
  ]
}
```

### `GET /dashboard/candidates`

Ranked candidate table. Accepts every filter from `/wells` plus
`min_confidence_score`, and returns `ranking_basis` so the UI can label the
sorted column.

```json
{
  "items": [
    {
      "rank": 1,
      "well_id": "UK-MOCK-CRN-001",
      "well_name": "Cornwall Geothermal Trial 1",
      "latitude": 50.2660, "longitude": -5.0507,
      "region": "South West England",
      "status": "non_producing",
      "total_depth_m": 2410.0,
      "temperature_c": 74.2,
      "temperature_status": "MEASURED",
      "temperature_confidence": "medium",
      "nearest_building_distance_m": 340.2,
      "annual_demand_kwh": 1284000.0,
      "thermal_output_kw": 452.0,
      "thermal_output_status": "ESTIMATE",
      "capex_gbp": 1240000.0,
      "lcoh_p_per_kwh": 14.2,
      "feasibility_score": 67.6,
      "confidence_score": 0.551,
      "recommendation": "HIGH PRIORITY",
      "is_mock": true
    }
  ],
  "total": 14, "limit": 50, "offset": 0,
  "ranking_basis": "feasibility_score",
  "includes_mock_data": true
}
```

### `GET /dashboard/summary`

Stage order, the scoring weights and their sum, the recommendation levels, the
confidence bands and the risk categories. The UI uses this rather than
hard-coding the taxonomy, so a change to the engine surfaces here first.

---

## Heat demand

### `GET /heat/clusters`

Aggregated demand cells. `is_clustered_with_postgis` reports which backend did the
clustering.

### `GET /heat/corridors`

Straight-line corridors from each well to its nearest demand centroid.

```json
{
  "corridors": [
    {
      "well_id": "UK-MOCK-CRN-001",
      "well_name": "Cornwall Geothermal Trial 1",
      "geometry": { "type": "LineString", "coordinates": [[-5.0507, 50.2660], [-5.0442, 50.2701]] },
      "distance_m": 340.2,
      "target_demand_kwh": 1284000.0,
      "indicative": true,
      "note": "Straight-line distance, not a routed pipeline. Treat as a lower bound."
    }
  ],
  "total_straight_line_length_km": 184.2,
  "caveat": "Distances are straight-line, not routed, and exclude road crossings, third-party consents and wayleaves."
}
```

### `GET /heat/demand-summary`

```json
{
  "by_building_type": { "detached": { "count": 210, "demand_kwh": 64400000 }, "terraced": { "count": 88, "demand_kwh": 21200000 } },
  "by_fuel": { "gas_central": { "count": 248, "demand_kwh": 71600000 } },
  "totals": { "buildings": 341, "annual_demand_gwh": 92.4, "peak_demand_kw": 18400.0 },
  "caveat": "Demand is modelled from floor area and building type. Peak demand is coincident and therefore overstates a real network peak."
}
```

### `GET /heat/buildings`, `GET /heat/buildings/map`, `GET /heat/density`

Buildings near a point, building points for the map, and a density grid.

---

## Projects

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/projects` | List the caller's projects |
| `POST` | `/projects` | Create |
| `GET` | `/projects/{uuid}` | Detail with wells |
| `POST` | `/projects/{uuid}/wells/{well_uuid}?role=candidate` | **Makes a well visible to the tenant** |
| `PATCH` | `/projects/{uuid}/stage?stage=validation` | Move stage |
| `POST` | `/projects/{uuid}/archive` | Archive; analyses retained |

`stage` is validated against an explicit allow-list:
`sourcing`, `screening`, `due_diligence`, `validation`, `feed_study`,
`investment_decision`, `delivery`, `operating`, `closed`, `rejected`.

---

## Admin

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/health` | Service health |
| `GET` | `/admin/datasets` | Registered datasets with provenance |
| `GET` | `/admin/adapters` | Available ingestion adapters |
| `POST` | `/admin/ingest` | Run one adapter |
| `POST` | `/admin/bootstrap` | Run every adapter in order |
| `GET` | `/admin/prices` | Energy price book |
| `GET` | `/admin/regulatory?configuration=…` | Consent requirements |
| `GET` | `/admin/heat-networks` | Known heat networks |
| `GET` | `/admin/demand-areas` | Settlement-level demand |
| `GET` | `/admin/parameters` | Documented engine parameters |

`/admin/parameters` is the canonical list of every default the engine applies,
each with a unit, a rationale and a source — or an explicit marker that it is an
assumption.

---

## Worked example: end to end

```bash
# 1. Sign in
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"..."}' | jq -r .access_token)

# 2. Make a well visible by creating a project and adding the well
PROJECT=$(curl -s -X POST localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"South West screening"}' | jq -r .id)

WELL=$(curl -s "localhost:8000/api/v1/wells?limit=1" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.items[0].id')

curl -s -X POST "localhost:8000/api/v1/projects/$PROJECT/wells/$WELL" \
  -H "Authorization: Bearer $TOKEN"

# 3. Now the well is visible
curl -s "localhost:8000/api/v1/wells/$WELL" -H "Authorization: Bearer $TOKEN"

# 4. Assess it
curl -s -X POST localhost:8000/api/v1/analyses \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"well_id\":\"$WELL\",\"include_ai_agents\":true}" \
  | jq '{score: .feasibility_score, confidence: .confidence_score, rec: .recommendation}'
```

Step 2 before step 3 is not ceremony. It is the tenancy model, and it is the
step most likely to be forgotten when scripting against this API.