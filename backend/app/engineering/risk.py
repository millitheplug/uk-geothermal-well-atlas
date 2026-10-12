"""Risk register.

Two things distinguish this from a generic risk list:

1. Every probability is *derived from the well's data*, not from a fixed
   template. A well with a stabilised 1985 static temperature log and a casing
   record has a genuinely lower temperature-uncertainty probability than one
   with a single interpolated figure.
2. Every risk carries an `uncertainty` value alongside its probability. A risk
   whose probability is unknown is scored differently from a risk known to be
   low. That distinction is what stops "we don't know" from disappearing into
   the average.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.enums import (
    EpistemicStatus,
    Impact,
    Likelihood,
    RiskCategory,
    WellIntegrityStatus,
    WellStatus,
)

LIKELIHOOD_VALUES: dict[str, float] = {
    Likelihood.VERY_UNLIKELY.value: 0.05,
    Likelihood.UNLIKELY.value: 0.20,
    Likelihood.POSSIBLE.value: 0.50,
    Likelihood.LIKELY.value: 0.80,
    Likelihood.VERY_LIKELY.value: 0.95,
}

IMPACT_VALUES: dict[str, float] = {
    Impact.NEGLIGIBLE.value: 0.05,
    Impact.MINOR.value: 0.20,
    Impact.MODERATE.value: 0.50,
    Impact.MAJOR.value: 0.80,
    Impact.SEVERE.value: 1.00,
}

SEVERITY_BANDS: list[tuple[float, str]] = [
    (0.75, "critical"),
    (0.50, "high"),
    (0.25, "medium"),
    (0.10, "low"),
    (0.00, "negligible"),
]


@dataclass(frozen=True, slots=True)
class RiskItem:
    category: str
    title: str
    description: str
    likelihood: str
    probability: float
    impact: str
    impact_value: float
    uncertainty: float
    evidence: tuple[str, ...] = ()
    mitigation: str | None = None
    addresses_data_gap: str | None = None

    @property
    def risk_score(self) -> float:
        """Probability x impact, 0-1.

        Uncertainty is deliberately *not* folded in here: the raw score
        answers "how bad is this if it happens", while
        :attr:`uncertainty_adjusted_score` answers "how worried should we be
        that we do not know".
        """
        return self.probability * self.impact_value

    @property
    def uncertainty_adjusted_score(self) -> float:
        """Raw score widened by how little is known about the probability.

        ``score * (1 + uncertainty * 0.5)``, capped at 1. An unknown probability
        therefore surfaces as a high adjusted score and generates a validation
        action, rather than averaging away to nothing.
        """
        return min(1.0, self.risk_score * (1.0 + self.uncertainty * 0.5))

    @property
    def severity(self) -> str:
        for threshold, label in SEVERITY_BANDS:
            if self.risk_score >= threshold:
                return label
        return "negligible"

    @property
    def is_critical(self) -> bool:
        return self.severity == "critical" or self.uncertainty_adjusted_score >= 0.75

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "likelihood": self.likelihood,
            "probability": round(self.probability, 3),
            "impact": self.impact,
            "impact_value": self.impact_value,
            "uncertainty": round(self.uncertainty, 3),
            "risk_score": round(self.risk_score, 3),
            "uncertainty_adjusted_score": round(self.uncertainty_adjusted_score, 3),
            "severity": self.severity,
            "is_critical": self.is_critical,
            "evidence": list(self.evidence),
            "mitigation": self.mitigation,
            "addresses_data_gap": self.addresses_data_gap,
        }


@dataclass
class RiskAssessment:
    risks: list[RiskItem] = field(default_factory=list)

    @property
    def aggregate_score(self) -> float:
        """Aggregate exposure, 0-1.

        Uses the expected-loss form rather than a simple mean: ``1 - (1 - s_i)``
        accumulates across risks so that many moderate risks matter, while
        ``sum`` would saturate. Capped at 1.
        """
        remaining = 1.0
        for risk in self.risks:
            remaining *= 1.0 - risk.uncertainty_adjusted_score
        return 1.0 - remaining

    @property
    def critical_risks(self) -> list[RiskItem]:
        return [r for r in self.risks if r.is_critical]

    def by_category(self) -> dict[str, list[RiskItem]]:
        grouped: dict[str, list[RiskItem]] = {}
        for risk in self.risks:
            grouped.setdefault(risk.category, []).append(risk)
        return grouped

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_score": round(self.aggregate_score, 4),
            "risk_count": len(self.risks),
            "critical_count": len(self.critical_risks),
            "risks": [r.to_dict() for r in self.risks],
        }


def _likelihood_from_probability(p: float) -> str:
    """Snap a computed probability onto the ordinal ladder, for readability."""
    if p < 0.10:
        return Likelihood.VERY_UNLIKELY.value
    if p < 0.35:
        return Likelihood.UNLIKELY.value
    if p < 0.65:
        return Likelihood.POSSIBLE.value
    if p < 0.88:
        return Likelihood.LIKELY.value
    return Likelihood.VERY_LIKELY.value


class RiskBuilder:
    """Builds the risk register for one well from its actual data."""

    def __init__(
        self,
        *,
        well_status: str | None = None,
        integrity_status: str | None = None,
        temperature_status: str = EpistemicStatus.UNKNOWN.value,
        temperature_confidence: str = "unknown",
        temperature_variability_c: float | None = None,
        drilling_year: int | None = None,
        total_depth_m: float | None = None,
        has_casing_record: bool = False,
        water_salinity_ppt: float | None = None,
        water_ph: float | None = None,
        scaling_tendency: str | None = None,
        corrosion_tendency: str | None = None,
        distance_to_demand_m: float | None = None,
        annual_demand_kwh: float | None = None,
        demand_confidence: str = "unknown",
        capex_gbp: float | None = None,
        lcoh_p_per_kwh: float | None = None,
        heat_price_p_per_kwh: float | None = None,
        requires_abstraction_licence: bool = False,
        is_spa: bool = False,
        is_conservation_area: bool = False,
        is_mining_subsidence_area: bool = False,
        is_heritage_asset: bool = False,
        number_of_off_takers: int | None = None,
        is_mock_data: bool = False,
    ) -> None:
        self.well_status = well_status
        self.integrity_status = integrity_status
        self.temperature_status = temperature_status
        self.temperature_confidence = temperature_confidence
        self.temperature_variability_c = temperature_variability_c
        self.drilling_year = drilling_year
        self.total_depth_m = total_depth_m
        self.has_casing_record = has_casing_record
        self.water_salinity_ppt = water_salinity_ppt
        self.water_ph = water_ph
        self.scaling_tendency = scaling_tendency
        self.corrosion_tendency = corrosion_tendency
        self.distance_to_demand_m = distance_to_demand_m
        self.annual_demand_kwh = annual_demand_kwh
        self.demand_confidence = demand_confidence
        self.capex_gbp = capex_gbp
        self.lcoh_p_per_kwh = lcoh_p_per_kwh
        self.heat_price_p_per_kwh = heat_price_p_per_kwh
        self.requires_abstraction_licence = requires_abstraction_licence
        self.is_spa = is_spa
        self.is_conservation_area = is_conservation_area
        self.is_mining_subsidence_area = is_mining_subsidence_area
        self.is_heritage_asset = is_heritage_asset
        self.number_of_off_takers = number_of_off_takers
        self.is_mock_data = is_mock_data

    # ---- Individual risk constructors -----------------------------------
    def _well_integrity(self) -> RiskItem:
        status = self.integrity_status or WellIntegrityStatus.UNKNOWN.value
        abandoned = self.well_status in (
            WellStatus.PLUGGED_ABANDONED.value,
            WellStatus.ABANDONED.value,
        )
        inaccessible = self.well_status in (
            WellStatus.ABANDONED.value,
            WellStatus.SUSPENDED.value,
        )

        if status == WellIntegrityStatus.GOOD_CONDITION.value:
            probability, uncertainty = 0.15, 0.25
        elif status == WellIntegrityStatus.PARTIALLY_MECHANICAL.value:
            probability, uncertainty = 0.45, 0.30
        elif status in (
            WellIntegrityStatus.ABANDONED_NO_ACCESS.value,
            WellIntegrityStatus.POOR_UNKNOWN.value,
        ):
            probability, uncertainty = 0.80, 0.20
        elif abandoned or inaccessible:
            probability, uncertainty = 0.70, 0.45
        else:
            probability, uncertainty = 0.50, 0.70

        evidence: list[str] = []
        if not self.has_casing_record:
            evidence.append("No casing string is recorded for this well.")
        if status == WellIntegrityStatus.UNKNOWN.value:
            evidence.append("No integrity assessment has been performed.")
        if abandoned:
            evidence.append(f"Well status is '{self.well_status}'.")
        if self.drilling_year:
            age = 2026 - self.drilling_year
            evidence.append(f"Drilled in {self.drilling_year}, {age} years old.")
            if age > 40:
                probability = min(0.95, probability + 0.10)

        # When the integrity record itself says the bore has no access or is in
        # poor condition, failure is not a cost overrun but the loss of the
        # opportunity: the impact is severe, which makes the risk critical and
        # engages the recommendation's hard integrity gate. Every other status
        # keeps a major impact.
        impact = Impact.MAJOR.value
        if status in (
            WellIntegrityStatus.ABANDONED_NO_ACCESS.value,
            WellIntegrityStatus.POOR_UNKNOWN.value,
        ):
            impact = Impact.SEVERE.value
            evidence.append(
                f"Integrity status is '{status}': the wellbore may not be re-enterable."
            )

        return RiskItem(
            category=RiskCategory.WELL_INTEGRITY.value,
            title="Wellbore integrity failure or unrecoverable completion",
            description=(
                "The existing casing or completion may not withstand thermal cycling, "
                "may be corroded, or may be inaccessible. Failure would require either "
                "recompletion or abandonment of the opportunity."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=impact,
            impact_value=IMPACT_VALUES[impact],
            uncertainty=uncertainty,
            evidence=tuple(evidence),
            mitigation=(
                "Commission a casing inspection (wireline or caliper survey) and obtain "
                "the completion record. This is the highest-value single validation "
                "action for an abandoned well."
            ),
            addresses_data_gap="well_integrity",
        )

    def _temperature_uncertainty(self) -> RiskItem:
        measured = self.temperature_status == EpistemicStatus.MEASURED.value
        if measured:
            uncertainty = 0.15
            probability = 0.15
        else:
            probability = 0.65
            conf = self.temperature_confidence.lower()
            uncertainty = {
                "high": 0.30,
                "medium": 0.55,
                "low": 0.75,
                "very_low": 0.85,
                "unknown": 0.90,
            }.get(conf, 0.80)

        if self.temperature_variability_c and self.temperature_variability_c > 10:
            probability = min(0.95, probability + 0.10)

        evidence: list[str] = []
        if not measured:
            evidence.append(
                f"Temperature status is '{self.temperature_status}', not MEASURED."
            )
            evidence.append(
                "Thermal output scales linearly with usable temperature swing, so an "
                "unmeasured temperature makes every power figure an estimate."
            )
        else:
            evidence.append("A direct temperature measurement exists for this well.")

        return RiskItem(
            category=RiskCategory.TEMPERATURE_UNCERTAINTY.value,
            title="Source temperature is not established to the required precision",
            description=(
                "If the temperature is estimated rather than measured, every downstream "
                "figure - thermal output, COP, LCOH - inherits that uncertainty, and "
                "the sign of the error is unknown."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=Impact.MAJOR.value,
            impact_value=IMPACT_VALUES[Impact.MAJOR.value],
            uncertainty=uncertainty,
            evidence=tuple(evidence),
            mitigation=(
                "Run a temperature log. If the well is abandoned and cannot be logged, "
                "seek static bottom-hole survey data from the original operator under "
                "the NSTA data-sharing provisions before any other spend."
            ),
            addresses_data_gap="temperature",
        )

    def _thermal_decline(self) -> RiskItem:
        shallow = bool(self.total_depth_m and self.total_depth_m < 1200)
        if shallow:
            probability, impact = 0.45, Impact.MODERATE
            description = (
                "At this depth the well is unlikely to be fully penetrated through the "
                "productive interval, so a large part of the accessible heat may already "
                "have been produced by the original operation."
            )
        else:
            probability, impact = 0.15, Impact.MODERATE
            description = (
                "Re-entry into a formation that has already been produced may yield a "
                "lower and declining temperature than historical measurements suggest."
            )

        return RiskItem(
            category=RiskCategory.THERMAL_DECLINE.value,
            title="Production history has depleted or cooled the accessible resource",
            description=description,
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=impact,
            impact_value=IMPACT_VALUES[impact],
            uncertainty=0.55,
            evidence=(
                f"Well drilled in {self.drilling_year}." if self.drilling_year else
                "No drilling year recorded, so depletion cannot be considered.",
            ),
            mitigation=(
                "Review production records and any temperature trend data. Compare "
                "bottom-hole pressures before and after primary depletion where both "
                "exist."
            ),
            addresses_data_gap="production_history",
        )

    def _corrosion(self) -> RiskItem:
        if self.corrosion_tendency and self.corrosion_tendency.lower() in ("high", "severe"):
            probability = 0.75
            evidence = [f"Water chemistry indicates '{self.corrosion_tendency}' corrosion tendency."]
        elif self.water_ph is not None and self.water_ph < 5.5:
            probability = 0.60
            evidence = [f"Water pH of {self.water_ph:.1f} is corrosive to carbon steel."]
        elif self.water_ph is not None and self.water_ph < 7.0:
            probability = 0.40
            evidence = [f"Water pH of {self.water_ph:.1f} is mildly corrosive."]
        else:
            probability = 0.30
            evidence = ["No water chemistry is available for this well."]

        return RiskItem(
            category=RiskCategory.CORROSION.value,
            title="Corrosion of casing, tubing or secondary circuit",
            description=(
                "Corrosive formation water can perforate casing, block flow with "
                "deposits, or fail the plate heat exchangers, with the consequence "
                "that the well must be worked over at significant cost."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=Impact.MAJOR.value,
            impact_value=IMPACT_VALUES[Impact.MAJOR.value],
            uncertainty=0.60 if self.water_ph is None else 0.30,
            evidence=tuple(evidence),
            mitigation=(
                "Obtain a water chemistry analysis from the original drilling reports, "
                "and specify corrosion-resistant materials and inhibitor dosing in the "
                "design."
            ),
            addresses_data_gap="water_chemistry",
        )

    def _scaling(self) -> RiskItem:
        if self.scaling_tendency and self.scaling_tendency.lower() in ("high", "severe"):
            probability = 0.75
            evidence = [f"Water chemistry indicates '{self.scaling_tendency}' scaling tendency."]
        elif self.water_salinity_ppt and self.water_salinity_ppt > 100:
            probability = 0.65
            evidence = [
                f"Formation water salinity of {self.water_salinity_ppt:.0f} "
                "ppt drives carbonate scaling."
            ]
        elif self.water_salinity_ppt and self.water_salinity_ppt > 35:
            probability = 0.45
            evidence = [f"Formation water salinity of {self.water_salinity_ppt:.0f} ppt."]
        else:
            probability = 0.25
            evidence = ["No water chemistry is available for this well."]

        return RiskItem(
            category=RiskCategory.SCALING.value,
            title="Mineral scaling reduces flow rate and heat transfer",
            description=(
                "Carbonate and sulphate scales build on hot surfaces, progressively "
                "reducing flow and raising pumping power. Scaling is the most common "
                "cause of geothermal plant underperformance."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=Impact.MODERATE.value,
            impact_value=IMPACT_VALUES[Impact.MODERATE.value],
            uncertainty=0.65 if self.water_salinity_ppt is None else 0.35,
            evidence=tuple(evidence),
            mitigation=(
                "Model saturation indices from a full water analysis, and specify plate "
                "heat exchangers sized for a cleaning frequency, or magnetic filtration."
            ),
            addresses_data_gap="water_chemistry",
        )

    def _groundwater(self) -> RiskItem:
        if self.requires_abstraction_licence:
            return RiskItem(
                category=RiskCategory.GROUNDWATER.value,
                title="Groundwater abstraction licence and reinjection constraint",
                description=(
                    "An open loop abstracts groundwater and must return it to the same "
                    "aquifer. The Environment Agency has generally not consented to "
                    "discharge geothermal water to surface waters since 2018, so a "
                    "reinjection well in a different aquifer may be required."
                ),
                likelihood=Likelihood.LIKELY.value,
                probability=LIKELIHOOD_VALUES[Likelihood.LIKELY.value],
                impact=Impact.MAJOR.value,
                impact_value=IMPACT_VALUES[Impact.MAJOR.value],
                uncertainty=0.35,
                evidence=(
                    "An open loop configuration requires an abstraction licence.",
                    "Since 2018 the Environment Agency has generally not consented to "
                    "the direct discharge of geothermal water, so a second well in a "
                    "different aquifer is likely to be needed for reinjection.",
                ),
                mitigation=(
                    "Confirm the licensing route and reinjection feasibility with the "
                    "Environment Agency before committing to an open loop. Consider a "
                    "closed loop plus heat pump, which avoids abstraction entirely."
                ),
            )
        return RiskItem(
            category=RiskCategory.GROUNDWATER.value,
            title="Groundwater interaction and contamination pathway",
            description=(
                "Even a closed loop exchanges heat with the formation. Where potable "
                "aquifers are present, an inadvertent pathway to a spring or borehole "
                "would require remediation."
            ),
            likelihood=Likelihood.UNLIKELY.value,
            probability=LIKELIHOOD_VALUES[Likelihood.UNLIKELY.value],
            impact=Impact.SEVERE.value,
            impact_value=IMPACT_VALUES[Impact.SEVERE.value],
            uncertainty=0.50,
            evidence=("Closed loop configuration: no water abstraction or discharge.",),
            mitigation=(
                "Complete a hydrogeological assessment and check for private water "
                "abstractions and potable sources within the zone of influence."
            ),
        )

    def _network_distance(self) -> RiskItem:
        d = self.distance_to_demand_m
        if d is None:
            probability, uncertainty = 0.50, 0.85
            title = "Distance to heat demand is unknown"
            description = "No demand location has been matched to this well."
            evidence = ("No building or heat demand record is associated with this well.",)
        elif d < 500:
            probability, uncertainty = 0.10, 0.20
            title = "Short connection distance"
            description = "The nearest demand is close enough that connection cost is modest."
            evidence = (f"Nearest demand is {d:.0f} m away.",)
        elif d < 2000:
            probability, uncertainty = 0.35, 0.25
            title = "Moderate connection distance"
            description = "Connection is viable but pipe cost is material."
            evidence = (f"Nearest demand is {d:.0f} m away.",)
        else:
            probability, uncertainty = 0.70, 0.30
            title = "Long connection distance to demand"
            description = (
                f"At {d/1000:.1f} km, the pipe cost per useful kWh is likely to exceed "
                "the value of the heat."
            )
            evidence = (f"Nearest demand is {d/1000:.1f} km away.",)

        impact = Impact.MODERATE if (d or 0) < 5000 else Impact.MAJOR

        return RiskItem(
            category=RiskCategory.NETWORK_DISTANCE.value,
            title=title,
            description=description,
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=impact,
            impact_value=IMPACT_VALUES[impact],
            uncertainty=uncertainty,
            evidence=tuple(evidence),
            mitigation=(
                "Carry out a route survey and confirm land ownership along the "
                "alignment. Consider aggregating several wells behind one heat centre."
            ),
            addresses_data_gap="network_route",
        )

    def _heat_demand_uncertainty(self) -> RiskItem:
        conf = self.demand_confidence.lower()
        if self.annual_demand_kwh is None:
            probability, uncertainty = 0.60, 0.85
            evidence = ["No heat demand figure is associated with this well."]
        else:
            probability = {
                "high": 0.10, "medium": 0.25, "low": 0.50,
                "very_low": 0.65, "unknown": 0.75,
            }.get(conf, 0.45)
            uncertainty = {
                "high": 0.20, "medium": 0.40, "low": 0.60,
                "very_low": 0.80, "unknown": 0.90,
            }.get(conf, 0.55)
            evidence = [f"Demand confidence recorded as '{self.demand_confidence}'."]

        if self.number_of_off_takers is not None and self.number_of_off_takers <= 1:
            probability = min(0.95, probability + 0.20)
            evidence.append(
                "Only one candidate off-taker was identified, so the revenue case "
                "concentrates on a single counterparty."
            )
        evidence.append(
            "Demand figures at this stage are modelled estimates, not metered data, "
            "unless an off-take agreement has been signed."
        )

        return RiskItem(
            category=RiskCategory.HEAT_DEMAND_UNCERTAINTY.value,
            title="Heat demand is smaller, later or less certain than assumed",
            description=(
                "District schemes fail commercially far more often on demand than on "
                "the resource. A scheme sized on modelled demand that does not "
                "materialise will not cover its fixed costs."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=Impact.MAJOR.value,
            impact_value=IMPACT_VALUES[Impact.MAJOR.value],
            uncertainty=uncertainty,
            evidence=tuple(evidence),
            mitigation=(
                "Obtain a signed or letter-of-intent off-take position before "
                "investment decision, and survey the actual buildings rather than "
                "relying on modelled demand."
            ),
            addresses_data_gap="heat_demand",
        )

    def _capex(self) -> RiskItem:
        if self.capex_gbp is None:
            probability, uncertainty = 0.50, 0.80
            evidence = ["Capital cost has not been estimated."]
        else:
            # Larger schemes carry proportionally more absolute variance.
            if self.capex_gbp > 3_000_000:
                probability = 0.65
            elif self.capex_gbp > 1_000_000:
                probability = 0.50
            else:
                probability = 0.40
            uncertainty = 0.55
            evidence = [f"Estimated capital cost GBP {self.capex_gbp:,.0f}."]

        return RiskItem(
            category=RiskCategory.CAPEX.value,
            title="Capital cost exceeds the screening estimate",
            description=(
                "The estimate is Class 3. Well condition, ground access, route "
                "permissions and procurement are all uncharacterised, and each can "
                "move the total by 30% or more."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=Impact.MAJOR.value,
            impact_value=IMPACT_VALUES[Impact.MAJOR.value],
            uncertainty=uncertainty,
            evidence=tuple(evidence),
            mitigation=(
                "Obtain a Class 2 estimate with a site visit and a route survey before "
                "investment decision. Confirm well accessibility with the landowner."
            ),
            addresses_data_gap="capex_estimate",
        )

    def _electricity_price(self) -> RiskItem:
        return RiskItem(
            category=RiskCategory.ELECTRICITY_PRICE.value,
            title="Electricity price increases erode the margin",
            description=(
                "Where a heat pump is fitted, the margin is set by the spread between "
                "the heat price and the electricity price. Because both are variable, "
                "the spread can compress or invert."
            ),
            likelihood=Likelihood.POSSIBLE.value,
            probability=LIKELIHOOD_VALUES[Likelihood.POSSIBLE.value],
            impact=Impact.MAJOR.value,
            impact_value=IMPACT_VALUES[Impact.MAJOR.value],
            uncertainty=0.40,
            evidence=(
                "Electricity price is a scenario input, not a contracted price.",
            ),
            mitigation=(
                "Model the scheme at high electricity prices, contract supply where "
                "practical, and quantify the electricity price at which the scheme "
                "breaks even."
            ),
        )

    def _heat_price(self) -> RiskItem:
        if self.lcoh_p_per_kwh is not None and self.heat_price_p_per_kwh is not None:
            if self.lcoh_p_per_kwh > self.heat_price_p_per_kwh:
                probability = 0.85
                evidence = [
                    f"LCOH of {self.lcoh_p_per_kwh:.1f} p/kWh already exceeds the "
                    f"assumed heat price of {self.heat_price_p_per_kwh:.1f} p/kWh."
                ]
            elif self.lcoh_p_per_kwh > self.heat_price_p_per_kwh * 0.8:
                probability = 0.60
                evidence = [
                    f"LCOH of {self.lcoh_p_per_kwh:.1f} p/kWh leaves little margin "
                    f"against a {self.heat_price_p_per_kwh:.1f} p/kWh heat price."
                ]
            else:
                probability = 0.25
                evidence = [
                    f"LCOH of {self.lcoh_p_per_kwh:.1f} p/kWh sits comfortably below "
                    f"the assumed heat price of {self.heat_price_p_per_kwh:.1f} p/kWh."
                ]
        else:
            probability = 0.50
            evidence = ["Neither LCOH nor a heat price is available for comparison."]

        return RiskItem(
            category=RiskCategory.HEAT_PRICE.value,
            title="Achievable heat price is below the modelled level",
            description=(
                "Domestic heat buyers resist paying a premium over gas. The price they "
                "will accept is the single most important commercial unknown and it is "
                "not observable from desk study."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=Impact.SEVERE.value,
            impact_value=IMPACT_VALUES[Impact.SEVERE.value],
            uncertainty=0.50,
            evidence=tuple(evidence),
            mitigation=(
                "Run a customer survey or market sounding on willingness to pay, and "
                "anchor the scheme on anchor tenants rather than household sales."
            ),
        )

    def _regulation(self) -> RiskItem:
        if self.requires_abstraction_licence:
            probability, duration = 0.55, "18-30 months"
        else:
            probability, duration = 0.30, "3-9 months"

        return RiskItem(
            category=RiskCategory.REGULATION.value,
            title="Consent process takes longer or on more onerous terms than assumed",
            description=(
                "Abstraction licensing, discharge consent and planning conditions can "
                f"each extend the programme. Current expectation is {duration}."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=Impact.MODERATE.value,
            impact_value=IMPACT_VALUES[Impact.MODERATE.value],
            uncertainty=0.50,
            evidence=(f"Expected consent programme: {duration}.",),
            mitigation=(
                "Make early pre-application contact with the Environment Agency and the "
                "local planning authority before committing capital."
            ),
        )

    def _planning(self) -> RiskItem:
        probability = 0.35
        impact = Impact.MODERATE
        evidence: list[str] = []
        if self.is_heritage_asset:
            probability = 0.65
            evidence.append("The site is a listed or scheduled monument, or in a conservation area.")
        if self.is_conservation_area:
            probability = min(0.8, probability + 0.20)
            evidence.append("The site lies in a conservation area.")
        if self.is_spa:
            probability = min(0.85, probability + 0.25)
            evidence.append("The site lies in or adjacent to a Special Protection Area.")
        if not evidence:
            evidence.append(
                "No planning constraints have been identified, but none have "
                "been formally checked."
            )

        return RiskItem(
            category=RiskCategory.PLANNING.value,
            title="Planning refusal or onerous conditions",
            description=(
                "A groundworks and pumping station consent could be refused, or granted "
                "with conditions that compromise the scheme, including noise limits and "
                "landscape requirements."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=impact,
            impact_value=IMPACT_VALUES[impact],
            uncertainty=0.55,
            evidence=tuple(evidence),
            mitigation=(
                "Pre-application consultation with the local planning authority, and a "
                "full constraints check against the planning layers before ranking."
            ),
        )

    def _land_access(self) -> RiskItem:
        if self.is_mock_data:
            note = " This assessment is based on synthetic development data."
        else:
            note = ""
        return RiskItem(
            category=RiskCategory.LAND_ACCESS.value,
            title="Land access, easements or lease cannot be secured",
            description=(
                "Both the wellsite and the pipe route require landowner agreement. A "
                "single refusal can strand the scheme even where the resource is good."
            ),
            likelihood=Likelihood.POSSIBLE.value,
            probability=LIKELIHOOD_VALUES[Likelihood.POSSIBLE.value],
            impact=Impact.MAJOR.value,
            impact_value=IMPACT_VALUES[Impact.MAJOR.value],
            uncertainty=0.60,
            evidence=(
                "Land ownership has not been verified for this well." + note,
            ),
            mitigation=(
                "Identify the landowner and route parcels from the Land Registry, and "
                "secure options over the route before committing to a scheme location."
            ),
        )

    def _customer_connection(self) -> RiskItem:
        if self.number_of_off_takers is None:
            probability = 0.55
        elif self.number_of_off_takers == 1:
            probability = 0.60
        elif self.number_of_off_takers < 5:
            probability = 0.40
        else:
            probability = 0.25

        return RiskItem(
            category=RiskCategory.CUSTOMER_CONNECTION.value,
            title="Customers fail to connect or switch off after installation",
            description=(
                "Domestic heat customers disconnect when bills exceed their gas "
                "alternative. Commercial customers may relocate. Either leaves the "
                "scheme short of the load its pipes were sized for."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=Impact.MAJOR.value,
            impact_value=IMPACT_VALUES[Impact.MAJOR.value],
            uncertainty=0.55,
            evidence=(
                f"{self.number_of_off_takers} candidate off-taker(s) identified."
                if self.number_of_off_takers is not None
                else "The number of candidate off-takers has not been established.",
            ),
            mitigation=(
                "Anchor the scheme on signed commercial or institutional offtake, and "
                "keep household connections to a phase that is only built once "
                "take-up is proven."
            ),
        )

    def _construction(self) -> RiskItem:
        if self.total_depth_m and self.total_depth_m > 3000:
            probability = 0.50
            evidence = [f"Total depth of {self.total_depth_m:.0f} m requires a suitable rig and crew."]
        elif self.total_depth_m and self.total_depth_m > 1800:
            probability = 0.35
            evidence = [f"Total depth of {self.total_depth_m:.0f} m."]
        else:
            probability = 0.25
            evidence = [
                f"Total depth of {self.total_depth_m:.0f} m is within routine rig capability."
                if self.total_depth_m
                else "Depth is unknown."
            ]
        if self.is_mining_subsidence_area:
            probability = min(0.9, probability + 0.20)
            evidence.append("Legacy mining in the area adds to construction difficulty.")

        return RiskItem(
            category=RiskCategory.CONSTRUCTION.value,
            title="Construction or intervention is harder or costlier than planned",
            description=(
                "Rig availability for deep wells, weather, and access for a crane and "
                "pipe-laying fleet all affect the programme."
            ),
            likelihood=_likelihood_from_probability(probability),
            probability=probability,
            impact=Impact.MODERATE.value,
            impact_value=IMPACT_VALUES[Impact.MODERATE.value],
            uncertainty=0.45,
            evidence=tuple(evidence),
            mitigation=(
                "Secure a rig option early, and confirm hardstanding requirements "
                "before committing the design."
            ),
        )

    def _operations(self) -> RiskItem:
        return RiskItem(
            category=RiskCategory.OPERATIONS.value,
            title="Scheme underperforms or suffers unplanned downtime",
            description=(
                "Geothermal plant requires skilled operation and prompt response to "
                "scaling, fouling and controls faults. Under-resourced operation is a "
                "common cause of poor availability."
            ),
            likelihood=Likelihood.POSSIBLE.value,
            probability=LIKELIHOOD_VALUES[Likelihood.POSSIBLE.value],
            impact=Impact.MODERATE.value,
            impact_value=IMPACT_VALUES[Impact.MODERATE.value],
            uncertainty=0.45,
            evidence=("Availability has not been demonstrated on any comparable scheme.",),
            mitigation=(
                "Establish an operating and maintenance regime with defined response "
                "times, and include availability guarantees in any supply contract."
            ),
        )

    # ---- Assembly -------------------------------------------------------
    def build(self) -> RiskAssessment:
        """Construct the full register, covering all sixteen required categories."""
        risks = [
            self._well_integrity(),
            self._temperature_uncertainty(),
            self._thermal_decline(),
            self._corrosion(),
            self._scaling(),
            self._groundwater(),
            self._network_distance(),
            self._heat_demand_uncertainty(),
            self._capex(),
            self._electricity_price(),
            self._heat_price(),
            self._regulation(),
            self._planning(),
            self._land_access(),
            self._customer_connection(),
            self._construction(),
            self._operations(),
        ]
        return RiskAssessment(risks=risks)


def required_categories() -> list[str]:
    """Every risk category in the taxonomy. Used by tests to check coverage."""
    return sorted(c.value for c in RiskCategory)
