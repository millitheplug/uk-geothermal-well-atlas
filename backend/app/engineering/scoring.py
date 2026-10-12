"""Deterministic feasibility scoring.

Hard constraint: the final score is produced entirely in this module. No LLM
call, no agent output, no free text influences it. Agents may explain the
score, prioritise validation actions against it, or contest it, but they cannot
change it.

Seven component scores, each normalised to 0-1, combined with the weights
below. Weights sum to 1.00. The `data_confidence` weight is included in the
composite because a well nobody has measured should not outrank a well that is
well characterised and only marginally less attractive.

`data_confidence` is deliberately a small component of the *feasibility* score
and a large component of the separate *confidence* score. It nudges the ranking
without pretending that a data gap is a physical defect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.enums import (
    DataConfidence,
    Recommendation,
    ScoreComponent,
    WellIntegrityStatus,
)

#: Component weights. Must sum to 1.0; asserted at import.
WEIGHTS: dict[str, float] = {
    ScoreComponent.THERMAL.value: 0.25,
    ScoreComponent.INTEGRITY.value: 0.20,
    ScoreComponent.DEMAND.value: 0.15,
    ScoreComponent.ECONOMICS.value: 0.15,
    ScoreComponent.NETWORK.value: 0.10,
    ScoreComponent.GEOMETRY.value: 0.05,
    ScoreComponent.REGULATORY.value: 0.05,
    ScoreComponent.DATA_CONFIDENCE.value: 0.05,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, f"weights must sum to 1.0, got {sum(WEIGHTS.values())}"

SCORE_VERSION = "0.1.0"


# ---------------------------------------------------------------- helpers
def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _piecewise(value: float | None, points: list[tuple[float, float]]) -> float:
    """Linear interpolation through ``(x, y)`` points, clamped at the ends.

    ``points`` must be sorted by x. Unknown inputs return the score for zero
    knowledge, which for every curve here is a low score rather than a neutral
    midpoint. Scoring an unknown as 0.5 would let missing data look average.
    """
    if value is None:
        return points[0][1]
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x0 <= value <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return points[-1][1]


# ------------------------------------------------------------ components
def thermal_score(
    *,
    source_temperature_c: float | None,
    target_supply_temperature_c: float = 70.0,
    usable_delta_t_c: float | None = None,
    flow_rate_lps: float | None = None,
    thermal_output_kw: float | None = None,
    temperature_confidence: str = DataConfidence.UNKNOWN.value,
    is_measured: bool = False,
) -> tuple[float, list[str]]:
    """Thermal adequacy: enough heat, at high enough temperature, to matter.

    Combines three signals:

    * source temperature against what the network needs;
    * the usable temperature swing actually available;
    * absolute output size, because a 30 kW well cannot support a district scheme.

    A measured temperature raises the ceiling of the score but does not by itself
    guarantee it; an estimated temperature is capped, because an estimate can be
    optimistic and the platform must not compound optimism into a score.
    """
    notes: list[str] = []

    if source_temperature_c is None:
        return 0.0, ["No source temperature available; thermal adequacy cannot be assessed."]

    # Adequacy relative to what is needed.
    headroom = source_temperature_c - target_supply_temperature_c
    if headroom <= 0:
        temp_component = 0.15
        notes.append(
            f"Source temperature {source_temperature_c:.0f} degC is below the "
            f"{target_supply_temperature_c:.0f} degC target supply temperature; a "
            "large heat pump lift would be required."
        )
    else:
        temp_component = _piecewise(headroom, [(0.0, 0.35), (10.0, 0.7), (30.0, 1.0)])
        if headroom > 10.0:
            notes.append(
                f"{headroom:.0f} K of headroom above the target supply temperature."
            )

    # Usable swing.
    if usable_delta_t_c is None:
        swing_component = temp_component * 0.6
        notes.append("Usable temperature swing not assessed.")
    else:
        swing_component = _piecewise(usable_delta_t_c, [(0.0, 0.05), (5.0, 0.4), (15.0, 0.8), (25.0, 1.0)])
        if usable_delta_t_c < 5.0:
            notes.append(
                f"Usable temperature swing is only {usable_delta_t_c:.1f} K, which "
                "severely limits extractable power per unit of flow."
            )

    # Absolute output size.
    if thermal_output_kw is None:
        output_component = 0.5
        notes.append("Thermal output not calculated; output adequacy scored neutrally.")
    else:
        output_component = _piecewise(
            thermal_output_kw, [(0.0, 0.0), (50.0, 0.2), (200.0, 0.6), (500.0, 0.85), (1000.0, 1.0)]
        )
        if thermal_output_kw < 50:
            notes.append(
                f"Estimated output of {thermal_output_kw:.0f} kW is small in district "
                "heating terms and is unlikely to support a viable network alone."
            )

    # Provenance ceiling on the temperature-derived terms only. Output size
    # depends mainly on the assumed flow rate, which is an independent
    # assumption, so capping it as well would conflate two uncertainties and
    # would stop a genuinely large well from ever outranking a small one.
    if is_measured:
        temp_cap = 1.0
        notes.append("Temperature is measured, so no confidence ceiling applied.")
    else:
        conf = temperature_confidence.lower()
        temp_cap = {
            DataConfidence.HIGH.value: 0.85,
            DataConfidence.MEDIUM.value: 0.70,
            DataConfidence.LOW.value: 0.55,
            DataConfidence.VERY_LOW.value: 0.40,
            DataConfidence.UNKNOWN.value: 0.30,
        }.get(conf, 0.55)
        notes.append(
            f"Temperature is estimated (confidence: {temperature_confidence}); the "
            f"temperature-derived part of the score is capped at {temp_cap:.0%} "
            "until it is measured."
        )

    temp_derived = min(0.40 * temp_component + 0.25 * swing_component, temp_cap)
    base = temp_derived + 0.35 * output_component

    return _clamp(base), notes


def integrity_score(
    *,
    integrity_status: str | None,
    casing_condition_score: float | None = None,
    abandonment_score: float | None = None,
    access_score: float | None = None,
    wellhead_condition_score: float | None = None,
    has_casing_record: bool = False,
) -> tuple[float, list[str]]:
    """Reuse-readiness of the wellbore.

    An unknown integrity status is scored low, not neutral. Reworking an
    abandoned well is possible but expensive, and a platform that scored
    "unknown" as 0.5 would systematically promote the wells nobody has looked at.
    """
    notes: list[str] = []
    status = integrity_status or WellIntegrityStatus.UNKNOWN.value

    status_floor = {
        WellIntegrityStatus.GOOD_CONDITION.value: 0.85,
        WellIntegrityStatus.PARTIALLY_MECHANICAL.value: 0.55,
        WellIntegrityStatus.SUSPENDED_INACCESSIBLE.value: 0.35,
        WellIntegrityStatus.ABANDONED_NO_ACCESS.value: 0.15,
        WellIntegrityStatus.POOR_UNKNOWN.value: 0.10,
        WellIntegrityStatus.UNKNOWN.value: 0.20,
    }.get(status, 0.20)

    if status == WellIntegrityStatus.UNKNOWN.value:
        notes.append(
            "Well integrity has not been assessed. This is the single largest source "
            "of uncertainty in the reuse case and is scored conservatively."
        )

    factors: list[tuple[float, float]] = []
    if casing_condition_score is not None:
        factors.append((casing_condition_score, 0.30))
    if abandonment_score is not None:
        factors.append((abandonment_score, 0.25))
    if access_score is not None:
        factors.append((access_score, 0.20))
    if wellhead_condition_score is not None:
        factors.append((wellhead_condition_score, 0.10))

    if not factors:
        # No condition detail at all: rely on the status floor, damped.
        score = status_floor * 0.75
        notes.append("No component-level condition data; scored from status alone.")
        return _clamp(_apply_casing_penalty(score, has_casing_record, notes)), notes

    weighted = sum(v * w for v, w in factors) / sum(w for _, w in factors)
    # The status is a ceiling: good sub-scores cannot rescue an abandoned well.
    score = min(weighted, status_floor + 0.15)
    notes.append(f"Weighted condition score {weighted:.2f}, status ceiling {status_floor:.2f}.")

    return _clamp(_apply_casing_penalty(score, has_casing_record, notes)), notes


def _apply_casing_penalty(score: float, has_casing_record: bool, notes: list[str]) -> float:
    """Discount a well whose casing string is undocumented.

    Without a casing record the condition cannot be verified at all, so the
    assessment rests on assumption rather than evidence.
    """
    if not has_casing_record:
        notes.append(
            "No casing string is documented for this well, so its condition cannot be "
            "assessed from records."
        )
        return score * 0.8
    return score


def demand_score(
    *,
    annual_demand_kwh: float | None,
    peak_demand_kw: float | None = None,
    thermal_output_kw: float | None = None,
    number_of_buildings: int | None = None,
    demand_confidence: str = DataConfidence.MEDIUM.value,
) -> tuple[float, list[str]]:
    """Whether enough heat demand exists near the well to absorb its output.

    Demand matching is a ratio, not a magnitude. A 5 MW well next to 50 kW of
    demand is a worse prospect than a 500 kW well next to 5 MW, even though the
    former is hotter.
    """
    notes: list[str] = []

    if annual_demand_kwh is None or thermal_output_kw is None or thermal_output_kw <= 0:
        return 0.0, [
            "Heat demand within range is unknown, or no output to match against; "
            "demand adequacy cannot be assessed."
        ]

    demand_ratio = annual_demand_kwh / (thermal_output_kw * 8760.0)
    # Ratio 1.0 means demand exactly equals the well's maximum annual output.
    if demand_ratio < 0.25:
        ratio_component = 0.10
        notes.append(
            f"Nearby annual demand ({annual_demand_kwh/1e6:.2f} GWh) is far below the "
            f"well's maximum annual output ({thermal_output_kw*8760/1e6:.2f} GWh). "
            "Most of the output would have no customer."
        )
    elif demand_ratio < 0.6:
        ratio_component = _piecewise(demand_ratio, [(0.25, 0.10), (0.6, 0.45)])
    elif demand_ratio <= 3.0:
        ratio_component = _piecewise(demand_ratio, [(0.6, 0.45), (1.0, 0.9), (3.0, 1.0)])
        notes.append(
            f"Nearby annual demand ({annual_demand_kwh/1e6:.2f} GWh) is a good match "
            f"for the estimated output."
        )
    else:
        ratio_component = 1.0
        notes.append(
            f"Nearby demand greatly exceeds output ({demand_ratio:.1f}x); the network "
            "would be heat-limited rather than source-limited, which is favourable."
        )

    # A single off-taker is a concentration risk regardless of total demand.
    if number_of_buildings is not None:
        if number_of_buildings <= 1:
            concentration = 0.35
            notes.append(
                "Only one candidate off-taker was identified. Losing it removes the "
                "entire revenue case."
            )
        elif number_of_buildings < 5:
            concentration = 0.65
        elif number_of_buildings < 20:
            concentration = 0.85
        else:
            concentration = 1.0
    else:
        concentration = 0.6
        notes.append("Number of candidate off-takers not established.")

    # Peak coincidence matters more than annual total for pipe sizing.
    peak_component = 0.8
    if peak_demand_kw is not None and thermal_output_kw > 0:
        peak_ratio = peak_demand_kw / thermal_output_kw
        if peak_ratio < 0.3:
            peak_component = 0.45
            notes.append(
                f"Peak demand ({peak_demand_kw:.0f} kW) is well below output, so the "
                "network will be oversized unless demand grows."
            )
        elif peak_ratio <= 1.5:
            peak_component = _piecewise(peak_ratio, [(0.3, 0.45), (0.6, 0.9), (1.5, 1.0)])
        else:
            peak_component = 0.7
            notes.append(
                "Peak demand exceeds the well output; a supplementary heat source "
                "would be required at peak."
            )

    base = 0.50 * ratio_component + 0.25 * concentration + 0.25 * peak_component

    conf_cap = {
        DataConfidence.HIGH.value: 1.0,
        DataConfidence.MEDIUM.value: 0.90,
        DataConfidence.LOW.value: 0.75,
        DataConfidence.VERY_LOW.value: 0.60,
        DataConfidence.UNKNOWN.value: 0.45,
    }.get(demand_confidence.lower(), 0.75)

    if conf_cap < 1.0:
        notes.append(
            f"Heat demand data confidence is {demand_confidence}; demand score capped "
            f"at {conf_cap:.0%}."
        )

    return _clamp(min(base, conf_cap)), notes


def network_score(
    *,
    distance_m: float | None,
    pipe_length_m: float | None = None,
    network_heat_loss_fraction: float | None = None,
    existing_network: bool = False,
    reinforcement_required: bool | None = None,
) -> tuple[float, list[str]]:
    """How practical the connection is.

    Distance dominates: below about 500 m most connections are straightforward,
    and beyond 3 km the pipe cost usually exceeds the value of the heat.
    """
    notes: list[str] = []

    if distance_m is None:
        return 0.0, ["Distance to demand is unknown; network feasibility cannot be assessed."]

    distance_component = _piecewise(
        distance_m, [(0.0, 1.0), (500.0, 0.9), (1500.0, 0.7), (3000.0, 0.45), (10000.0, 0.15)]
    )
    if distance_m > 3000:
        notes.append(
            f"Nearest demand is {distance_m/1000:.1f} km away. Beyond roughly 3 km the "
            "pipe cost per useful kWh rises steeply and usually rules the scheme out."
        )

    loss_component = 0.8
    if network_heat_loss_fraction is not None:
        loss_component = _piecewise(
            network_heat_loss_fraction, [(0.0, 0.7), (0.10, 1.0), (0.20, 0.6), (0.35, 0.25)]
        )
        if network_heat_loss_fraction > 0.25:
            notes.append(
                f"Distribution losses of {network_heat_loss_fraction:.0%} are high; "
                "insulation or a shorter route would be needed."
            )
    else:
        notes.append("Distribution losses not calculated.")

    existing_component = 1.0 if existing_network else 0.5
    if existing_network:
        notes.append("An existing heat network is present, which materially reduces connection cost.")
        # Reinforcement of an existing network still erodes the benefit of having
        # one, so this is checked independently of `existing_network`.
        if reinforcement_required:
            existing_component = 0.45
            notes.append(
                "The existing network would require reinforcement before it can accept "
                "this heat, so much of the connection-cost benefit is lost."
            )
    elif reinforcement_required:
        existing_component = 0.35
        notes.append("An existing network would require reinforcement before it can accept this heat.")

    score = (
        0.50 * distance_component + 0.25 * loss_component + 0.25 * existing_component
    )

    if pipe_length_m and pipe_length_m > 5000:
        score *= 0.85
        notes.append(
            f"Pipe route of {pipe_length_m/1000:.1f} km requires easements and multiple "
            "landowner agreements."
        )

    return _clamp(score), notes


def geometry_score(
    *,
    total_depth_m: float | None,
    tvd_m: float | None,
    md_m: float | None = None,
    max_deviation_deg: float | None = None,
    is_deviated: bool | None = None,
) -> tuple[float, list[str]]:
    """Wellbore geometry: is this a shape a heat circuit can use?

    A highly deviated or horizontal well drilled for production is a poor
    candidate for a simple doublet: installing a U-tube to TD becomes expensive
    and thermally inefficient. Vertical and deviated-but-recoverable wells are
    good candidates.
    """
    notes: list[str] = []

    if total_depth_m is None:
        return 0.0, ["Well depth is unknown; geometry cannot be assessed."]

    depth_component = _piecewise(
        total_depth_m, [(0.0, 0.35), (800.0, 0.7), (1500.0, 0.9), (3000.0, 1.0), (5000.0, 0.75)]
    )
    if total_depth_m > 4500:
        notes.append(
            f"Total depth of {total_depth_m:.0f} m increases steel cost and thermal loss "
            "in the riser significantly."
        )
    if total_depth_m < 600:
        notes.append(
            f"Total depth of {total_depth_m:.0f} m is shallow for a dedicated geothermal "
            "doublet, though adequate if the target is shallow sandstone."
        )

    # Deviation. Applied as a ceiling rather than only a weighted term: a strongly
    # deviated well is a poor doublet candidate however deep it is, so geometry
    # score must not be rescued by a favourable depth.
    deviation_component = 1.0
    deviation_ceiling = 1.0
    if is_deviated:
        deviation_component = 0.55
        deviation_ceiling = 0.7
        notes.append(
            "The well is deviated. Accessing TD for a geothermal completion is harder "
            "and may require re-drilling."
        )
    if max_deviation_deg is not None:
        if max_deviation_deg > 60:
            deviation_component = min(deviation_component, 0.3)
            deviation_ceiling = 0.45
            notes.append(
                f"Maximum deviation of {max_deviation_deg:.0f} deg makes this a poor "
                "doublet candidate."
            )
        elif max_deviation_deg > 30:
            deviation_component = min(deviation_component, 0.5)
            deviation_ceiling = 0.6

    # TVD vs MD consistency: a large gap means a long deviated section.
    tvd_md_component = 1.0
    if tvd_m is not None and md_m:
        ratio = tvd_m / md_m if md_m > 0 else 0
        if ratio < 0.5:
            tvd_md_component = 0.5
            notes.append(
                f"TVD is {ratio:.0%} of measured depth, indicating substantial "
                "horizontal extent."
            )
        elif ratio < 0.75:
            tvd_md_component = 0.8

    weighted = 0.5 * depth_component + 0.3 * deviation_component + 0.2 * tvd_md_component
    return _clamp(min(weighted, deviation_ceiling)), notes


def economics_score(
    *,
    lcoh_p_per_kwh: float | None,
    heat_price_p_per_kwh: float,
    npv_gbp: float | None = None,
    irr_pct: float | None = None,
    payback_years: float | None = None,
) -> tuple[float, list[str]]:
    """Whether the scheme clears the cost of heat against a saleable price.

    The primary test is LCOH against heat price, because that is the comparison
    a buyer of heat actually cares about. NPV, IRR and payback refine it.
    """
    notes: list[str] = []

    if lcoh_p_per_kwh is None:
        return 0.0, ["LCOH has not been calculated; economics cannot be assessed."]

    require_positive_price = max(heat_price_p_per_kwh, 0.01)

    # 1.0 when LCOH is 40% of price; 0.0 when it exceeds price by 50%.
    if lcoh_p_per_kwh <= require_positive_price * 0.4:
        lcoh_component = 1.0
    elif lcoh_p_per_kwh >= require_positive_price * 1.5:
        lcoh_component = 0.0
        notes.append(
            f"LCOH of {lcoh_p_per_kwh:.1f} p/kWh exceeds the assumed heat price of "
            f"{heat_price_p_per_kwh:.1f} p/kWh by more than 50%."
        )
    else:
        lcoh_component = 1.0 - (lcoh_p_per_kwh - require_positive_price * 0.4) / (
            require_positive_price * 1.1
        )

    npv_component = 0.6
    if npv_gbp is not None:
        if npv_gbp > 0:
            npv_component = 1.0
            notes.append(f"NPV is positive at GBP {npv_gbp:,.0f} on the base case inputs.")
        else:
            npv_component = 0.25
            notes.append(f"NPV is negative at GBP {npv_gbp:,.0f} on the base case inputs.")

    irr_component = 0.6
    if irr_pct is not None:
        irr_component = _piecewise(irr_pct, [(0.0, 0.2), (3.0, 0.4), (6.0, 0.6), (10.0, 0.85), (20.0, 1.0)])

    payback_component = 0.7
    if payback_years is not None:
        payback_component = _piecewise(
            payback_years, [(0.0, 1.0), (5.0, 0.9), (10.0, 0.6), (15.0, 0.3), (25.0, 0.05)]
        )
        if payback_years > 15:
            notes.append(
                f"Payback of {payback_years:.1f} years is long for heat infrastructure."
            )

    score = (
        0.50 * lcoh_component
        + 0.20 * npv_component
        + 0.15 * irr_component
        + 0.15 * payback_component
    )

    return _clamp(score), notes


def regulatory_score(
    *,
    mandatory_requirement_count: int = 0,
    estimated_approval_months: float | None = None,
    requires_planning_permission: bool | None = None,
    requires_abstraction_licence: bool = False,
    requires_discharge_consent: bool = False,
    is_mining_subsidence_area: bool = False,
    is_spa: bool = False,
    is_conservation_area: bool = False,
) -> tuple[float, list[str]]:
    """Consent burden and programme risk.

    A closed loop in England can often avoid the abstraction licence and
    discharge consent that an open loop needs, which is why the configuration is
    the first thing this function looks at.
    """
    notes: list[str] = []

    consent_component = 1.0
    if requires_abstraction_licence:
        consent_component -= 0.30
        notes.append(
            "An abstraction licence is required. In England, water below 23 degC at "
            "abstraction point requires a full licence and a permit to abstract in a "
            "drought-prone area."
        )
    if requires_discharge_consent:
        consent_component -= 0.20
        notes.append(
            "A discharge consent is required for reinjection or final discharge. Note "
            "that since 2018 the EA has generally not issued consents for the direct "
            "discharge of geothermal water; reinjection is usually required instead."
        )
    if requires_planning_permission:
        consent_component -= 0.15
        notes.append(
            "Planning permission is required. 28 days for a permitted "
            "development, longer otherwise."
        )

    if is_spa:
        consent_component -= 0.20
        notes.append("Site lies within or adjacent to a Special Protection Area; screening is required.")
    if is_conservation_area:
        consent_component -= 0.10
        notes.append("Site lies in a conservation area; additional heritage constraints may apply.")
    if is_mining_subsidence_area:
        consent_component -= 0.15
        notes.append(
            "Subsidence risk from legacy coal mining. Both a drilling hazard and an "
            "increased pipe failure risk over the asset life."
        )

    if mandatory_requirement_count:
        notes.append(f"{mandatory_requirement_count} mandatory regulatory requirements identified.")

    programme_component = 1.0
    if estimated_approval_months is not None:
        programme_component = _piecewise(
            estimated_approval_months,
            [(0.0, 1.0), (6.0, 0.85), (12.0, 0.6), (24.0, 0.3), (36.0, 0.1)],
        )
        if estimated_approval_months > 18:
            notes.append(
                f"Estimated approval programme of {estimated_approval_months:.0f} months "
                "is a material schedule risk."
            )

    return _clamp(0.65 * consent_component + 0.35 * programme_component), notes


# ------------------------------------------------------------ aggregate
@dataclass(frozen=True, slots=True)
class ScoreComponentResult:
    name: str
    score: float
    weight: float
    contribution: float
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeasibilityScore:
    """The deterministic score. ``final`` is the composite, 0-100."""

    final: float
    confidence_score: float
    components: tuple[ScoreComponentResult, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = ()
    score_version: str = SCORE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "final": round(self.final, 2),
            "confidence_score": round(self.confidence_score, 4),
            "score_version": self.score_version,
            "components": {
                c.name: {
                    "score": round(c.score, 4),
                    "weight": c.weight,
                    "contribution": round(c.contribution, 4),
                    "notes": list(c.notes),
                }
                for c in self.components
            },
            "notes": list(self.notes),
            "weights": dict(WEIGHTS),
        }

    def weakest_components(self, n: int = 2) -> list[str]:
        """Components dragging the score down, worst first.

        Used to generate the 'why' text and to prioritise validation actions.
        """
        ordered = sorted(self.components, key=lambda c: c.score * c.weight)
        return [c.name for c in ordered[:n]]


def composite_score(
    *,
    thermal: float,
    integrity: float,
    demand: float,
    economics: float,
    network: float,
    geometry: float,
    regulatory: float,
    data_confidence: float,
    weights: dict[str, float] | None = None,
) -> float:
    """Weighted sum of component scores, returned on a 0-100 scale.

    Kept as a separate pure function so that the weighting can be unit tested
    directly and so that a future per-tenant weight override has one place to
    live.
    """
    w = weights or WEIGHTS
    total = sum(w.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1.0, got {total}")

    composite = (
        thermal * w[ScoreComponent.THERMAL.value]
        + integrity * w[ScoreComponent.INTEGRITY.value]
        + demand * w[ScoreComponent.DEMAND.value]
        + economics * w[ScoreComponent.ECONOMICS.value]
        + network * w[ScoreComponent.NETWORK.value]
        + geometry * w[ScoreComponent.GEOMETRY.value]
        + regulatory * w[ScoreComponent.REGULATORY.value]
        + data_confidence * w[ScoreComponent.DATA_CONFIDENCE.value]
    )
    return _clamp(composite) * 100.0


def recommend(
    *,
    feasibility_score: float,
    confidence_score: float,
    critical_risk_count: int = 0,
    critical_integrity_risk: bool = False,
    data_gap_count: int = 0,
    lcoh_p_per_kwh: float | None = None,
    heat_price_p_per_kwh: float | None = None,
) -> tuple[Recommendation, tuple[str, ...]]:
    """Map score and evidence quality onto a prioritisation.

    Deliberately threshold-based rather than a continuous mapping, because the
    action attached to a band ("commission a temperature log") is discrete.

    Confidence gates the result: a high score on weak evidence is downgraded,
    because the sensible next step for an exciting but unmeasured well is to
    measure it, not to commit to it.

    A critical well-integrity risk is a hard gate, not a weight. However high
    the composite score, a well whose bore may be sealed, collapsed or
    unrecoverable cannot be ranked above LOW PRIORITY until that risk is
    retired by inspection, because no other component can compensate for a
    well that cannot be re-entered.
    """
    reasons: list[str] = []

    score_band = feasibility_score
    if confidence_score < 0.35:
        score_band *= 0.75
        reasons.append(
            f"Evidence confidence is low ({confidence_score:.0%}), so the feasibility "
            "score has been discounted by 25% before ranking."
        )

    if critical_risk_count >= 3:
        score_band *= 0.8
        reasons.append(
            f"{critical_risk_count} critical risks are open, which reduces priority "
            "until they are retired."
        )

    if score_band >= 65 and confidence_score >= 0.55:
        recommendation = Recommendation.HIGH_PRIORITY
        reasons.append(
            "Feasibility score and evidence confidence are both strong enough to "
            "justify detailed due diligence and a site visit."
        )
    elif score_band >= 45 and confidence_score >= 0.35:
        recommendation = Recommendation.MEDIUM_PRIORITY
        reasons.append(
            "The well shows promise but at least one material uncertainty remains. "
            "Targeted desktop work should resolve it before spending on fieldwork."
        )
    elif score_band >= 25:
        recommendation = Recommendation.LOW_PRIORITY
        reasons.append(
            "The case is weak on current evidence. It should be retained on a watch "
            "list and revisited if data improves, rather than actively progressed."
        )
    else:
        recommendation = Recommendation.DO_NOT_PURSUE
        reasons.append(
            "The well does not present a defensible case for geothermal reuse on the "
            "evidence available. Pursuing it would consume budget better spent "
            "elsewhere."
        )

    if critical_integrity_risk and recommendation in (
        Recommendation.HIGH_PRIORITY,
        Recommendation.MEDIUM_PRIORITY,
    ):
        recommendation = Recommendation.LOW_PRIORITY
        reasons.append(
            "A critical well-integrity risk is open. Integrity is a hard gate, so "
            "the recommendation is capped at LOW PRIORITY regardless of the "
            "feasibility score until the wellbore is inspected and the risk retired."
        )
    elif critical_integrity_risk:
        reasons.append(
            "A critical well-integrity risk is open and must be retired by "
            "inspection before this well could be progressed."
        )

    if lcoh_p_per_kwh is not None and heat_price_p_per_kwh:
        if lcoh_p_per_kwh > heat_price_p_per_kwh:
            reasons.append(
                f"Note that LCOH ({lcoh_p_per_kwh:.1f} p/kWh) exceeds the assumed heat "
                f"price ({heat_price_p_per_kwh:.1f} p/kWh), so the scheme is not "
                "commercially competitive at these inputs even before risk."
            )
        else:
            margin = (heat_price_p_per_kwh - lcoh_p_per_kwh) / heat_price_p_per_kwh
            reasons.append(
                f"LCOH of {lcoh_p_per_kwh:.1f} p/kWh sits {margin:.0%} below the "
                f"assumed heat price, before any risk premium."
            )

    if data_gap_count:
        reasons.append(
            f"{data_gap_count} material data gap(s) remain outstanding."
        )

    return recommendation, tuple(reasons)
