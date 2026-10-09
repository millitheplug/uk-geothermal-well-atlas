# Engineering formulas

Every calculation the platform performs, with its variables, the status it
reports, and where the formulation comes from.

All of this is implemented in `backend/app/engineering/`. Each function returns a
`CalcResult` (`base.py`) carrying `inputs`, `input_units`, `formula`, `result`,
`result_unit`, `status`, `assumptions`, `sources`, `intermediate_values`,
`warnings` and `confidence`. Those results are persisted as
`calculation_traces` rows and rendered in the interface under
**Assessment → Trace**, which is why the formulae below are written out rather
than left implicit in the code.

**None of these calculations involve a language model.** The agents in
`app/agents/` read the results of these functions and write prose about them.

---

## Status convention

Every calculation declares what kind of number it is producing. The status is
not cosmetic: it propagates to the API response, to the stored analysis, and to
the badge rendered next to the figure.

| Status | When it is used |
|---|---|
| `MEASURED` | The output is an instrument reading, or a direct transcription of one. |
| `DERIVED` | Computed from measured or documented inputs by the formula below. Reproducible. |
| `MODELLED` | Output of a correlation or simulation, not an observation. |
| `ESTIMATE` | A published or analyst estimate with a documented method; the value was not observed. |
| `ASSUMPTION` | A chosen default. No observation underlies it. |
| `UNKNOWN` | No defensible value. Returned as `None` with a warning, never as zero. |

---

## 1. Thermal output — `thermal.py`

### 1.1 Extracted thermal power

```
Q_gross  = ṁ · c_p · ΔT
Q        = (flow_lps · ρ / 1000) · c_p · (T_source − T_return) · utilisation_factor
```

| Symbol | Meaning | Unit | Status |
|---|---|---|---|
| `flow_lps` | Flow rate through the production string | L/s | `ASSUMPTION` — 20 L/s default, a 7″ string at reasonable velocity. Not a measurement. |
| `ρ` | Fluid density | kg/m³ | `ASSUMPTION` (1000 kg/m³) |
| `c_p` | Specific heat capacity | J/kg·K | `ASSUMPTION` (4180 J/kg·K) |
| `T_source` | Source temperature | °C | `MEASURED` when the well has a stabilised survey; otherwise the status of whatever the record actually is |
| `T_return` | Return temperature | °C | `DERIVED` — source temperature minus the usable swing |
| `utilisation_factor` | Duty cycle | – | `ASSUMPTION` — 0.85 default. Heat demand is seasonal, so this is rarely 1 |

**Reported status: `ESTIMATE`.** Output scales linearly with flow rate, and no
flow test has been performed unless the record says one was. The interface says
so directly beneath the figure.

Source: BGS heat-capacity guidance and BGS geothermal temperature data.

### 1.2 Available versus delivered

```
Q_available = Q_gross · utilisation_factor
```

Applied after the above when a duty cycle has been applied separately, so the
report can distinguish the instantaneous output from the annualised one.

### 1.3 Uncertainty band

```
dQ/Q = −dT_useful / T_useful        where T_useful = T_source − T_return
dQ/Q =  dṁ / ṁ

combined = sqrt( (dT_useful/T_useful)² + (dṁ/ṁ)² )

Q_low  = Q · (1 − combined)
Q_high = Q · (1 + combined)
```

A first-order sensitivity band with the two error sources combined in
quadrature, which is appropriate because temperature uncertainty and flow
uncertainty are independent.

This is the mechanism by which a poorly characterised temperature produces a
wide band rather than a spuriously precise point value — and why a well with a
5 K spread between sources looks visibly weaker on the map than one that is
genuinely tight.

Note that temperature error propagates against the *useful swing*, not against
the absolute temperature. A ±5 K error on a 20 K swing is 25%; the same ±5 K on
a 70 K swing is 7%. Wells that are barely hot enough to be useful are therefore
correctly shown as far more uncertain than deep hot wells with the same
absolute temperature tolerance.

---

## 2. Heat pump — `heatpump.py`

### 2.1 Coefficient of performance

```
COP = Carnot(T_evap = T_source − 3 K, T_cond = T_supply_mean + 5 K)
      · carnot_ratio · condensing_penalty · part_load_derate · mechanical_efficiency
```

The Carnot limit is computed between the evaporator and condenser temperatures
with the stated offsets: 3 K approach on the evaporator, 5 K on the condenser.
`carnot_ratio` is a realistic fraction of Carnot (0.45 by default), then a
condensing penalty, a part-load derate and a mechanical efficiency.

**Reported status: `ESTIMATE`.** No heat pump has been specified for any well.

An important rule: when the well is hot enough to serve the network directly,
the engine does **not** add a heat pump. It returns
`HeatPumpNotRequired`, and the configuration is downgraded to the non-heat-pump
variant. Requiring a heat pump to make a configuration look more sophisticated
would be an invention, not an assessment.

Source: temperature-lift COP guidance.

### 2.2 Electricity consumption

```
P_electric = Q_thermal / COP
```

**Status: `DERIVED`.** Also reported as net electricity where the thermal
contribution is subtracted.

### 2.3 Delivered heat

```
E_delivered = Q_thermal · operating_hours · capacity_factor − E_loss

where E_loss = Q_loss · operating_hours · capacity_factor
          or   E_available · loss_fraction
```

**Status: `ESTIMATE`.**

---

## 3. Network — `network.py`

### 3.1 Distribution heat loss

```
Q_loss = k · L · ((T_supply + T_return)/2 − T_ground) / 1000 + Q_fixed
```

| Symbol | Meaning | Unit | Status |
|---|---|---|---|
| `k` | Thermal loss coefficient | W/(m·K) | `ASSUMPTION` — insulated pipe, default 0.20 |
| `L` | Network length | m | `DERIVED` — straight-line distance to the nearest matched demand centroid, and labelled as a lower bound |
| `T_ground` | Ground temperature at burial depth | °C | `ASSUMPTION` — default 10 °C |
| `Q_fixed` | Fixed loss for plant room and substation | kW | `ASSUMPTION` |

**Status: `ESTIMATE`.**

**Straight-line distance is not a route.** The interface draws corridors dashed
and labels them "indicative" on every view, because the moment a straight line
looks like a pipeline alignment someone will cost it as one.

Source: district-heating guide loss coefficients.

---

## 4. CAPEX — `cost.py`

```
CAPEX = plant
      + well_recompletion
      + network
      + substation
      + consents
      + contingency

where contingency = contingency_fraction · (sum of the above)
```

Components are built from documented unit rates applied to this well's depth,
completion geometry and matched network length. `contingency_fraction` defaults
to 0.20 and is applied to the sum of the named components. CAPEX does **not**
include land purchase, offtake negotiation, connection agreements or financing
cost.

**Status: `ESTIMATE`.**

Source: published cost guidance for geothermal well re-completion and district
heating plant.

---

## 5. OPEX — `opex.py`

```
OPEX = plant_fixed
     + network_fixed
     + heat_pump_service
     + abstraction
     + chemistry
     + insurance
     + land_lease
```

Abstraction and chemistry terms are only included where the configuration
actually abstracts water — an open loop carries both, a closed loop carries
neither, which is a real regulatory advantage as well as a cost one.

**Status: `ESTIMATE`.**

---

## 6. Financial — `financial.py`

### 6.1 Levelised cost of heat

```
CRF   = r(1 + r)^n / ((1 + r)^n − 1)
EUAC  = CAPEX · CRF + OPEX
LCOH  = EUAC / annual_heat_kWh · 100        (pence per kWh)
```

`r` is the real discount rate (`ASSUMPTION`, default 0.08), `n` the project
lifetime in years (`ASSUMPTION`, default 20). The default operating basis is
3,300 hours per year at a 0.55 capacity factor against a 0.85 utilisation
factor, and a 70 °C network supply temperature.

**Status: `DERIVED`.**

### 6.2 Net present value

```
NPV = Σ_{t=1..n} CF_t / (1 + r)^t − CAPEX_0
```

**Status: `DERIVED`.**

### 6.3 Internal rate of return

```
IRR solves Σ_{t=1..n} CF_t / (1 + IRR)^t − CAPEX_0 = 0
```

Solved by bisection with an expanding bracket.

**Two behaviours worth stating explicitly**, because both were bugs before they
were features:

- The `t = 0` capital outflow is part of the equation, not ignored. An earlier
  version bracketed the search using only the positive cash flows, which meant a
  scheme whose flows were small relative to CAPEX had no sign change and
  returned no IRR for the wrong reason.
- **A cash flow with no sign change returns `None` with `status=UNKNOWN` and a
  warning, never 0%.** A project that never recovers its capital does not have an
  IRR of zero; it has no IRR, and the difference matters when someone is
  comparing schemes.

### 6.4 Simple payback

```
simple_payback = CAPEX / annual_net_cash_flow
```

Returned as `None` when annual net cash flow is zero (never recovered) or
negative (never recovered). Both cases produce a warning, not a number.

### 6.5 Discounted payback

```
payback = min{ t : Σ_{s=1..t} CF_s/(1+r)^s − CAPEX_0 ≥ 0 }
```

`None` when the cumulative discounted cash flow never reaches zero within the
project lifetime.

### 6.6 Break-even heat price

```
p_break_even = [CAPEX·CRF + OPEX + electricity_cost] / annual_heat_kWh · 100
```

The heat price at which NPV is zero, holding every other input fixed. This is
the single most useful financial output for a screening tool, because it
converts the question from "is this project good?" to "what would heat have to
be worth?", which is a question a heat buyer can answer.

---

## 7. Scoring — `scoring.py`

Eight components, each scored 0–100:

```
composite = 0.25·thermal        + 0.20·integrity
          + 0.15·demand         + 0.15·economics
          + 0.10·network        + 0.05·geometry
          + 0.05·regulatory     + 0.05·data_confidence
```

The weights sum to 1.0 and this is asserted at import, so a mis-edited weight
fails immediately rather than silently changing every score in the database.
`SCORE_VERSION` is stored with each analysis.

Each component is normalised to 0–100 by a saturating or piecewise-linear
mapping defined in `scoring.py`, chosen so that the shape of the curve matches
what actually limits the component. Thermal, for example, saturates: the
difference between 40 °C and 55 °C decides whether a heat pump is needed at all,
while the difference between 120 °C and 135 °C changes nothing an operator would
do differently.

`data_confidence` appears inside the composite with a small weight **and** is
also reported separately. Both. The small weight stops weak evidence from
dominating the ranking; the separate reporting stops a strong score from hiding
weak evidence.

### 7.1 Recommendation

Threshold-based rather than continuous, because the action attached to a band is
discrete — you either commission a temperature log or you do not.

```
band = feasibility_score

if confidence < 0.35:  band *= 0.75
if critical_risks ≥ 3: band *= 0.80

HIGH PRIORITY     band ≥ 65 and confidence ≥ 0.55
MEDIUM PRIORITY   band ≥ 45 and confidence ≥ 0.35
LOW PRIORITY      band ≥ 25
DO NOT PURSUE      otherwise
```

Every discount that was applied is recorded in `recommendation_rationale` and
shown in the interface. The rationale also states the margin between LCOH and
the assumed heat price when both are known.

---

## 8. Confidence — `confidence.py`

Five axes, weighted, none of which describe the resource:

```
confidence = 0.25·source_reliability
           + 0.25·data_completeness
           + 0.25·measurement_quality
           + 0.10·recency
           + 0.15·cross_source_agreement
```

| Axis | What it measures | Notable behaviour |
|---|---|---|
| `source_reliability` | Trust in the sources behind the well's data | Discounted 20% when only one source exists — an uncorroborated source cannot be cross-checked. Two or more independent sources earn a bonus of up to 0.10. |
| `data_completeness` | Fraction of the fields the model needs that are present | Returns a floor rather than a high score when required fields are missing. |
| `measurement_quality` | Whether the key measurement was direct | An analogue or extrapolated temperature caps this axis. |
| `recency` | Age of the measurement | Ageing data is penalised, but never discounted to zero: a 1970s survey is still evidence. |
| `cross_source_agreement` | Agreement between sources | Two sources that disagree by more than a stated tolerance reduce this axis and are listed in `conflicting_sources`. |

Bands: `high` ≥ 0.75, `medium` ≥ 0.55, `low` ≥ 0.35, `very_low` > 0,
`unknown` = 0.

Confidence measures the **evidence**, not the resource. A well can be an
excellent candidate that nobody has measured, and the interface says that
wherever the two numbers appear next to each other.

---

## 9. Risk — `risk.py`

Seventeen categories:

```
well_integrity          temperature_uncertainty   thermal_decline
corrosion               scaling                   groundwater
network_distance        heat_demand_uncertainty   capex
electricity_price       heat_price                regulation
planning                land_access               customer_connection
construction            operations
```

Each risk carries `probability`, `impact_value` and an explicit `uncertainty`,
all in 0–1:

```
risk_score               = probability · impact_value
uncertainty_adjusted     = risk_score / (1 + uncertainty)
```

The adjustment is the point. A hazard nobody has quantified is ranked above an
equivalent hazard that has been measured, because the first one is the one being
managed by ignoring it. Ranking on raw likelihood × impact systematically
buries unknowns.

`severity` is derived from the adjusted score; three or more critical risks
discount the recommendation band (see §7.1).

---

## 10. Traceability

For any figure on any screen:

1. The figure's `status` is shown next to it.
2. The `Trace` tab lists every calculation that produced it, expandable to show
   `inputs`, `input_units`, `formula`, `intermediate_values`, `assumptions`,
   `sources` and `warnings`.
3. `Evidence` lists the source documents and the attributed claims.
4. `Claims` without evidence are labelled `ASSUMPTION`, never `FACT`.

That chain is what makes the score checkable rather than merely stated. If a
number is wrong, the reader can find where it came from without asking anyone.