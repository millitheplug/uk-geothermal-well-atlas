"""Evidence confidence, computed independently of feasibility.

A well can be an excellent candidate that nobody has measured, or a poor one
that has been studied in detail. Those two wells must not get the same score,
and the platform must be able to say which one it is looking at. That is what
this module produces.

Five axes, per the specification:

``source_reliability``
    How trusted the underlying sources are.
``data_completeness``
    How many of the fields that matter are actually populated.
``measurement_quality``
    How well the temperature was measured - method, equilibration, depth.
``recency``
    How old the data is. A 1968 static temperature log for a well now plugged
    and abandoned describes a state that no longer exists.
``cross_source_agreement``
    Whether independent sources tell the same story.

Reported separately from feasibility and never folded into it, except through
the explicit 5% weight the specification requires.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from app.core.enums import DataConfidence, EpistemicStatus

CONFIDENCE_VERSION = "0.1.0"

#: Fields whose presence materially changes how much can be concluded.
REQUIRED_FIELDS: tuple[str, ...] = (
    "temperature_c",
    "total_depth_m",
    "tvd_m",
    "status",
    "original_purpose",
    "drilling_year",
    "operator",
    "licence",
    "formation",
    "casing_string",
)

#: Fields that are desirable but whose absence does not invalidate a screen.
DESIRABLE_FIELDS: tuple[str, ...] = (
    "bottomhole_pressure_bar",
    "md_m",
    "max_deviation_deg",
    "completion_type",
    "latitude_offset_checked",
    "pressure_status",
)

#: Half-life in years for the recency axis. Data older than this scores 0.
RECENCY_HALF_LIFE_YEARS = 25.0


@dataclass(frozen=True, slots=True)
class ConfidenceComponent:
    name: str
    score: float
    weight: float
    contribution: float
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    """Overall confidence plus the five axis scores and their reasoning."""

    score: float
    band: str
    components: tuple[ConfidenceComponent, ...] = field(default_factory=tuple)
    conflicting_sources: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    confidence_version: str = CONFIDENCE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "band": self.band,
            "confidence_version": self.confidence_version,
            "axes": {
                c.name: {
                    "score": round(c.score, 4),
                    "weight": c.weight,
                    "contribution": round(c.contribution, 4),
                    "notes": list(c.notes),
                }
                for c in self.components
            },
            "conflicting_sources": list(self.conflicting_sources),
            "unknowns": list(self.unknowns),
        }


CONFIDENCE_WEIGHTS: dict[str, float] = {
    "source_reliability": 0.25,
    "data_completeness": 0.25,
    "measurement_quality": 0.25,
    "recency": 0.10,
    "cross_source_agreement": 0.15,
}

assert abs(sum(CONFIDENCE_WEIGHTS.values()) - 1.0) < 1e-9


def band_for(score: float) -> str:
    """Map a 0-1 confidence score to the ordinal band used in the UI."""
    if score >= 0.75:
        return DataConfidence.HIGH.value
    if score >= 0.55:
        return DataConfidence.MEDIUM.value
    if score >= 0.35:
        return DataConfidence.LOW.value
    if score > 0.0:
        return DataConfidence.VERY_LOW.value
    return DataConfidence.UNKNOWN.value


def source_reliability_axis(reliabilities: list[float] | None) -> tuple[float, list[str]]:
    """Aggregate source trust.

    The mean is discounted when there is only one source, because a single
    uncorroborated source cannot be cross-checked. Two or more independent
    sources earn a modest bonus.
    """
    notes: list[str] = []
    if not reliabilities:
        return 0.15, ["No sources are recorded for this well; reliability cannot be established."]

    mean = sum(reliabilities) / len(reliabilities)

    if len(reliabilities) == 1:
        score = mean * 0.8
        notes.append(
            "Only one source is recorded. A single source cannot be corroborated, so "
            "reliability is discounted by 20%."
        )
    else:
        bonus = min(0.10, 0.05 * (len(reliabilities) - 1))
        score = min(1.0, mean + bonus)
        notes.append(f"{len(reliabilities)} sources recorded, giving a corroboration bonus.")

    best = max(reliabilities)
    if best >= 0.9:
        notes.append("At least one primary regulator or operator source is present.")
    elif best < 0.6:
        notes.append(
            "No primary or regulator source is present; all data is secondary or unverified."
        )

    return max(0.0, min(1.0, score)), notes


def data_completeness_axis(
    present_fields: dict[str, Any],
    *,
    integrity_assessed: bool = False,
    demand_data_present: bool = False,
    logs_available: bool = False,
) -> tuple[float, list[str]]:
    """How much of what we need is actually there.

    Required fields dominate. Desirable fields contribute a smaller share. Two
    structural bonuses apply: an integrity assessment and a nearby demand
    figure, because without either of those no conclusion is possible at all.
    """
    notes: list[str] = []

    required_present = sum(1 for f in REQUIRED_FIELDS if present_fields.get(f) is not None)
    required_ratio = required_present / len(REQUIRED_FIELDS)

    desirable_present = sum(1 for f in DESIRABLE_FIELDS if present_fields.get(f) is not None)
    desirable_ratio = desirable_present / len(DESIRABLE_FIELDS)

    score = 0.75 * required_ratio + 0.25 * desirable_ratio

    missing = [f for f in REQUIRED_FIELDS if present_fields.get(f) is None]
    if missing:
        notes.append(f"Missing required fields: {', '.join(missing)}.")

    if not integrity_assessed:
        score *= 0.8
        notes.append(
            "Well integrity has not been assessed, which reduces completeness by 20%."
        )
    if not demand_data_present:
        score *= 0.85
        notes.append("No heat demand data is associated with this well's location.")
    if logs_available:
        bonus = 0.10
        score = min(1.0, score + bonus)
        notes.append("Well logs are available and would support verification of key fields.")

    return max(0.0, min(1.0, score)), notes


def measurement_quality_axis(
    *,
    temperature_status: str = EpistemicStatus.UNKNOWN.value,
    measurement_method: str | None = None,
    is_final_stabilised: bool | None = None,
    temperature_variability_c: float | None = None,
    measured_depth_m: float | None = None,
    total_depth_m: float | None = None,
    has_flow_test: bool = False,
) -> tuple[float, list[str]]:
    """How well the temperature itself was established.

    This is the axis that separates "we know it is hot" from "somebody thinks
    it is hot". Static stabilised bottom-hole surveys rank highest; regional
    estimates rank lowest.
    """
    notes: list[str] = []

    method_scores = {
        "static_bht": 0.95,
        "circulation_test": 0.90,
        "max_dynamic": 0.80,
        "production_log": 0.75,
        "dts_reprocessed": 0.70,
        "regional_estimate": 0.30,
        "depth_extrapolation": 0.25,
        "analogous_well": 0.20,
    }

    if temperature_status in (EpistemicStatus.UNKNOWN.value,):
        return 0.05, ["No temperature measurement of any kind is recorded."]

    base = method_scores.get(measurement_method or "", 0.45)
    notes.append(f"Measurement method '{measurement_method}' scores {base:.2f} on method quality.")

    if temperature_status == EpistemicStatus.ESTIMATE.value:
        base *= 0.75
        notes.append("The temperature is an estimate rather than a direct measurement.")
    elif temperature_status == EpistemicStatus.MEASURED.value:
        base *= 1.0
    elif temperature_status == EpistemicStatus.DERIVED.value:
        base *= 0.85
        notes.append("The temperature is derived from other measurements, not read directly.")

    if is_final_stabilised is False:
        base *= 0.7
        notes.append(
            "The reading was not thermally stabilised, so it likely overstates the "
            "sustained reservoir temperature."
        )
    elif is_final_stabilised is True:
        notes.append("The reading was recorded after thermal equilibration.")

    if temperature_variability_c is not None:
        if temperature_variability_c > 15.0:
            base *= 0.75
            notes.append(
                f"Temperature varies by {temperature_variability_c:.0f} K across "
                "measurements, indicating a heterogeneous or poorly characterised zone."
            )
        elif temperature_variability_c < 3.0:
            notes.append("Temperature measurements are highly repeatable.")

    # A temperature measured far shallower than TD may not represent the
    # reservoir; not penalised, but noted.
    if measured_depth_m and total_depth_m:
        depth_fraction = measured_depth_m / total_depth_m if total_depth_m > 0 else 0
        if depth_fraction < 0.7:
            base *= 0.9
            notes.append(
                f"Temperature was measured at {depth_fraction:.0%} of total depth; "
                "the reservoir at TD may differ."
            )

    if has_flow_test:
        base = min(1.0, base + 0.15)
        notes.append(
            "A flow test exists, so the well has demonstrated deliverability at "
            "temperature, which is the strongest possible evidence for this axis."
        )

    return max(0.0, min(1.0, base)), notes


def recency_axis(
    *,
    measurement_date: datetime | date | None,
    well_status: str | None = None,
    reference_date: datetime | date | None = None,
) -> tuple[float, list[str]]:
    """Age of the newest relevant data.

    Applies an exponential decay with a 25-year half-life, then an additional
    penalty for wells whose status has changed since the data was collected.
    """
    notes: list[str] = []

    if measurement_date is None:
        return 0.25, ["No measurement date is recorded; data age cannot be established."]

    ref = reference_date or datetime.now(timezone.utc)
    if isinstance(measurement_date, datetime):
        measured = measurement_date
        if measured.tzinfo is None:
            measured = measured.replace(tzinfo=timezone.utc)
    else:
        measured = datetime.combine(measurement_date, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(ref, datetime):
        ref_dt = ref
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)
    else:
        ref_dt = datetime.combine(ref, datetime.min.time(), tzinfo=timezone.utc)

    age_years = (ref_dt - measured).days / 365.25
    if age_years < 0:
        return 0.9, ["Measurement date is in the future; treated as recent."]

    score = math.pow(0.5, age_years / RECENCY_HALF_LIFE_YEARS)

    if age_years > 30:
        score *= 0.7
        notes.append(
            f"Data is {age_years:.0f} years old. A discounted rate applies on top of "
            "the normal decay."
        )
    elif age_years < 5:
        notes.append(f"Data is recent ({age_years:.1f} years old).")

    # Status changes invalidate old data more than age alone would suggest.
    if well_status in ("plugged_abandoned", "abandoned") and age_years > 10:
        score *= 0.6
        notes.append(
            "The well has since been abandoned. Data describing it in production "
            "describes a physical state that no longer exists."
        )

    return max(0.0, min(1.0, score)), notes


def cross_source_agreement_axis(
    *,
    temperature_values_c: list[float] | None,
    sources: list[str] | None,
    tolerance_c: float = 5.0,
) -> tuple[float, tuple[str], list[str]]:
    """Do independent sources agree?

    Returns ``(score, conflicting_sources, notes)``. The spread of reported
    temperatures is compared against a tolerance: within tolerance scores well,
    beyond it is penalised in proportion to the disagreement, because a 20 K
    spread between sources means the temperature is not yet known to the
    precision the engineering model needs.
    """
    notes: list[str] = []

    if not sources or len(sources) < 2:
        return 0.4, (), [
            "Only one source is available, so agreement between sources cannot be tested."
        ]

    if not temperature_values_c or len(temperature_values_c) < 2:
        # Sources agree trivially, but nothing corroborates the temperature.
        return 0.45, (), [
            f"{len(sources)} sources exist but they do not report independent "
            "temperatures, so agreement cannot be assessed on the key quantity."
        ]

    spread = max(temperature_values_c) - min(temperature_values_c)
    mean = sum(temperature_values_c) / len(temperature_values_c)

    conflicts: list[str] = []
    if spread <= tolerance_c:
        score = 1.0 - 0.1 * (spread / tolerance_c)
        notes.append(
            f"Sources agree within {spread:.1f} K (tolerance {tolerance_c:.0f} K)."
        )
    else:
        ratio = (spread - tolerance_c) / tolerance_c
        score = max(0.05, 0.6 / (1 + ratio))
        conflicts.append(
            f"Temperature sources span {spread:.1f} K (mean {mean:.1f} degC, "
            f"range {min(temperature_values_c):.1f}-{max(temperature_values_c):.1f} degC)."
        )
        notes.append(
            f"Sources disagree by {spread:.1f} K, beyond the {tolerance_c:.0f} K tolerance. "
            "Confidence is reduced in proportion to the disagreement."
        )

    if len(sources) >= 3 and not conflicts:
        score = min(1.0, score + 0.05)
        notes.append("Three or more independent sources agree.")

    return max(0.0, min(1.0, score)), tuple(conflicts), notes


def assess_confidence(
    *,
    source_reliabilities: list[float] | None = None,
    present_fields: dict[str, Any] | None = None,
    integrity_assessed: bool = False,
    demand_data_present: bool = False,
    logs_available: bool = False,
    temperature_status: str = EpistemicStatus.UNKNOWN.value,
    measurement_method: str | None = None,
    is_final_stabilised: bool | None = None,
    temperature_variability_c: float | None = None,
    measured_depth_m: float | None = None,
    total_depth_m: float | None = None,
    has_flow_test: bool = False,
    measurement_date: datetime | date | None = None,
    well_status: str | None = None,
    temperature_values_c: list[float] | None = None,
    sources: list[str] | None = None,
    unknowns: list[str] | None = None,
) -> ConfidenceAssessment:
    """Compute the full confidence assessment.

    Returns the composite 0-1 score, its ordinal band, per-axis detail, any
    conflicts found between sources, and the unknowns that could not be
    resolved. Every parameter is optional and defaults to the pessimistic case.
    """
    reliability, reliability_notes = source_reliability_axis(source_reliabilities)
    completeness, completeness_notes = data_completeness_axis(
        present_fields or {},
        integrity_assessed=integrity_assessed,
        demand_data_present=demand_data_present,
        logs_available=logs_available,
    )
    measurement, measurement_notes = measurement_quality_axis(
        temperature_status=temperature_status,
        measurement_method=measurement_method,
        is_final_stabilised=is_final_stabilised,
        temperature_variability_c=temperature_variability_c,
        measured_depth_m=measured_depth_m,
        total_depth_m=total_depth_m,
        has_flow_test=has_flow_test,
    )
    recency, recency_notes = recency_axis(
        measurement_date=measurement_date, well_status=well_status
    )
    agreement, conflicts, agreement_notes = cross_source_agreement_axis(
        temperature_values_c=temperature_values_c, sources=sources
    )

    axes: list[ConfidenceComponent] = [
        ConfidenceComponent("source_reliability", reliability, CONFIDENCE_WEIGHTS["source_reliability"],
                            reliability * CONFIDENCE_WEIGHTS["source_reliability"], tuple(reliability_notes)),
        ConfidenceComponent("data_completeness", completeness, CONFIDENCE_WEIGHTS["data_completeness"],
                            completeness * CONFIDENCE_WEIGHTS["data_completeness"], tuple(completeness_notes)),
        ConfidenceComponent("measurement_quality", measurement, CONFIDENCE_WEIGHTS["measurement_quality"],
                            measurement * CONFIDENCE_WEIGHTS["measurement_quality"], tuple(measurement_notes)),
        ConfidenceComponent("recency", recency, CONFIDENCE_WEIGHTS["recency"],
                            recency * CONFIDENCE_WEIGHTS["recency"], tuple(recency_notes)),
        ConfidenceComponent("cross_source_agreement", agreement, CONFIDENCE_WEIGHTS["cross_source_agreement"],
                            agreement * CONFIDENCE_WEIGHTS["cross_source_agreement"], tuple(agreement_notes)),
    ]

    score = sum(c.contribution for c in axes)
    score = max(0.0, min(1.0, score))

    # A well with no temperature at all cannot have high confidence no matter
    # how good its other records are, because temperature is the whole question.
    if temperature_status == EpistemicStatus.UNKNOWN.value and score > 0.5:
        score *= 0.6
        axes.append(
            ConfidenceComponent(
                "temperature_presence",
                0.05,
                0.0,
                0.0,
                (
                    "No temperature measurement exists for this well. Overall confidence "
                    "is capped regardless of how complete the other records are.",
                ),
            )
        )

    return ConfidenceAssessment(
        score=score,
        band=band_for(score),
        components=tuple(axes),
        conflicting_sources=conflicts,
        unknowns=tuple(unknowns or []),
    )
