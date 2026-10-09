"""Default parameters for the engineering model.

Every default here is an ASSUMPTION and is reported as one. They are collected
in one module so that a user can see the full set in one place, override any of
them through a scenario, and trace any figure in the output back to a specific
default rather than to a literal buried in a function.

Values are grounded in published UK guidance where one exists, and in stated
engineering judgement where none does. Where judgement is used, the rationale
field says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.enums import GeothermalConfiguration
from app.engineering.base import AssumptionRef


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    key: str
    value: Any
    unit: str
    rationale: str
    source: str | None = None
    low: float | None = None
    high: float | None = None
    distribution: str | None = None

    def to_assumption(self, *, is_default: bool = True) -> AssumptionRef:
        return AssumptionRef(
            key=self.key,
            value=self.value,
            unit=self.unit,
            rationale=self.rationale,
            is_default=is_default,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "unit": self.unit,
            "rationale": self.rationale,
            "source": self.source,
            "low": self.low,
            "high": self.high,
            "distribution": self.distribution,
        }


DEFAULTS: tuple[ParameterSpec, ...] = (
    # ---- Thermal -------------------------------------------------------
    ParameterSpec(
        key="flow_rate_lps",
        value=20.0,
        unit="L/s",
        rationale=(
            "Nominal flow through an existing production string. A 7 inch tube at a "
            "reasonable velocity carries roughly 20 L/s. This is a starting point, "
            "not a measurement: the achievable rate depends on the completion and "
            "formation, neither of which is characterised at screening stage."
        ),
        source="Engineering judgement based on standard production tubing hydraulics",
        low=5.0,
        high=60.0,
        distribution="triangular",
    ),
    ParameterSpec(
        key="source_temperature_c",
        value=None,
        unit="degC",
        rationale=(
            "Taken from the well's temperature record when one exists. Never defaulted: "
            "a well with no temperature gets no temperature."
        ),
    ),
    ParameterSpec(
        key="return_temperature_c",
        value=None,
        unit="degC",
        rationale=(
            "Computed as source temperature minus the usable swing implied by the "
            "target supply temperature. Never defaulted independently."
        ),
    ),
    ParameterSpec(
        key="utilisation_factor",
        value=0.85,
        unit="-",
        rationale=(
            "Accounts for downtime and distribution losses as a proportion of "
            "theoretical output. 15% is typical for a well-run plant and is "
            "conservative for a first-of-a-kind scheme."
        ),
        source="BEIS Energy Technology List availability assumptions",
        low=0.65,
        high=0.95,
        distribution="triangular",
    ),
    ParameterSpec(
        key="capacity_factor",
        value=0.55,
        unit="-",
        rationale=(
            "Fraction of heating season hours at useful output. UK space heating is "
            "weather-driven with a pronounced shoulder-season plateau, so average "
            "load is well below peak."
        ),
        source="UK domestic heating load profiles",
        low=0.35,
        high=0.70,
        distribution="triangular",
    ),
    ParameterSpec(
        key="operating_hours_per_year",
        value=3300.0,
        unit="h",
        rationale=(
            "Hours in a UK heating season including shoulder months. Geothermal plant "
            "commonly runs September to June. Engineering judgement based on UK "
            "heating-season norms rather than a published single figure."
        ),
        low=2500.0,
        high=4000.0,
        distribution="triangular",
    ),
    ParameterSpec(
        key="target_supply_temperature_c",
        value=70.0,
        unit="degC",
        rationale=(
            "Modern low-temperature district heating designs for 70 degC flow and 40 "
            "degC return, supported by heat pumps on the customer side. Older 80/60 "
            "networks demand more from the source."
        ),
        source="CIBSE CP1 District Heating",
        low=55.0,
        high=85.0,
        distribution="uniform",
    ),
    ParameterSpec(
        key="heat_pump_carnot_ratio",
        value=0.45,
        unit="-",
        rationale=(
            "Real-machine performance as a fraction of Carnot at geothermal lifts. "
            "Industry-quoted efficiency is often 0.5-0.6; 0.45 is used to avoid "
            "overstating performance from a table lookup."
        ),
        source="IEA Future of Heat Pumps",
        low=0.35,
        high=0.55,
        distribution="triangular",
    ),
    # ---- Network -------------------------------------------------------
    ParameterSpec(
        key="network_length_m",
        value=None,
        unit="m",
        rationale=(
            "Computed from the matched off-taker geometry when buildings are available. "
            "Never defaulted independently."
        ),
    ),
    ParameterSpec(
        key="ground_temperature_c",
        value=10.0,
        unit="degC",
        rationale=(
            "UK annual mean shallow ground temperature at typical pipe burial depth. "
            "The observed range across the UK is roughly 8-14 degC."
        ),
        source="BGS geothermal catalogue",
        low=8.0,
        high=14.0,
        distribution="triangular",
    ),
    ParameterSpec(
        key="linear_loss_w_per_m_per_k",
        value=0.20,
        unit="W/(m.K)",
        rationale=(
            "Pre-insulated twin pipe at district heating temperatures. Higher for "
            "older or single pipe systems."
        ),
        source="BEIS DUKES district heating loss conventions",
        low=0.12,
        high=0.40,
        distribution="triangular",
    ),
    # ---- Economics -----------------------------------------------------
    ParameterSpec(
        key="discount_rate",
        value=0.08,
        unit="-",
        rationale=(
            "Real discount rate for screening. The Green Book advises a lower rate "
            "for low-risk assets, but 8% is used here because most of these projects "
            "carry genuine development risk at screening stage."
        ),
        source="HM Treasury Green Book",
        low=0.05,
        high=0.12,
        distribution="triangular",
    ),
    ParameterSpec(
        key="project_lifetime_years",
        value=20,
        unit="years",
        rationale=(
            "Conservative asset life for a geothermal doublet. The borehole itself "
            "should last far longer, but the heat pump, plate exchangers and "
            "controls have shorter lives. Engineering judgement: 20 years matches "
            "typical heat pump warranty and replacement cycles."
        ),
        source="BEIS Energy Technology List asset life assumptions",
        low=15.0,
        high=30.0,
        distribution="uniform",
    ),
    ParameterSpec(
        key="electricity_price_p_per_kwh",
        value=15.0,
        unit="p/kWh",
        rationale=(
            "Non-domestic electricity tariff including levies. Where a heat pump is "
            "fitted this drives the operating margin directly."
        ),
        source="Ofgem tariff data",
        low=9.0,
        high=28.0,
        distribution="triangular",
    ),
    ParameterSpec(
        key="heat_price_p_per_kwh",
        value=8.5,
        unit="p/kWh",
        rationale=(
            "Achievable heat sale price. Domestic customers compare against gas at "
            "roughly 6-7 p/kWh and will pay a modest premium for comfort and "
            "carbon. Commercial offtake can support more."
        ),
        source="BEIS Heat Networks market analysis",
        low=5.0,
        high=14.0,
        distribution="triangular",
    ),
    ParameterSpec(
        key="contingency_fraction",
        value=0.20,
        unit="-",
        rationale=(
            "Class 3 estimate contingency per AACE International recommended practice "
            "for a project at this stage of definition."
        ),
        source="AACE International Recommended Practice 18R-97",
        low=0.10,
        high=0.35,
        distribution="triangular",
    ),
    ParameterSpec(
        key="fuel_price_p_per_kwh",
        value=None,
        unit="p/kWh",
        rationale=(
            "Not modelled. The displaced-fuel comparison belongs in the report's "
            "context section, not in the cash flow, because the platform does not "
            "claim a fuel switching benefit without a contracted fuel price."
        ),
    ),
)

DEFAULTS_BY_KEY: dict[str, ParameterSpec] = {p.key: p for p in DEFAULTS}


@dataclass
class ParameterSet:
    """Resolved parameters for one run.

    Values come from, in order of precedence: explicit user overrides, then
    scenario overrides, then the defaults above. ``overrides_applied`` records
    which is which so the report can state it.
    """

    values: dict[str, Any] = field(default_factory=dict)
    overrides_applied: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        overrides: dict[str, Any] | None = None,
        scenario: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ParameterSet:
        values: dict[str, Any] = {}
        applied: dict[str, bool] = {}

        for spec in DEFAULTS:
            values[spec.key] = spec.value
            applied[spec.key] = False

        for source_dict, is_user in (
            (scenario or {}, False),
            (overrides or {}, True),
            (extra or {}, True),
        ):
            for key, value in source_dict.items():
                if value is not None:
                    values[key] = value
                    applied[key] = is_user

        return cls(values=values, overrides_applied=applied)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value
        self.overrides_applied[key] = True

    def as_assumptions(self) -> tuple[AssumptionRef, ...]:
        """Every non-None parameter as a traceable assumption."""
        refs: list[AssumptionRef] = []
        for key, value in self.values.items():
            if value is None:
                continue
            spec = DEFAULTS_BY_KEY.get(key)
            refs.append(
                AssumptionRef(
                    key=key,
                    value=value,
                    unit=spec.unit if spec else None,
                    rationale=spec.rationale if spec else "User-supplied value.",
                    is_default=not self.overrides_applied.get(key, False),
                )
            )
        return tuple(refs)

    def unknowns(self) -> list[str]:
        """Parameters that have no value and must not be guessed."""
        return [k for k, v in self.values.items() if v is None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": self.values,
            "overrides_applied": self.overrides_applied,
        }


#: Configuration-specific overrides applied on top of the base defaults.
CONFIGURATION_OVERRIDES: dict[str, dict[str, Any]] = {
    GeothermalConfiguration.CLOSED_LOOP.value: {
        "utilisation_factor": 0.80,
    },
    GeothermalConfiguration.OPEN_LOOP.value: {
        "utilisation_factor": 0.88,
    },
    GeothermalConfiguration.CLOSED_LOOP_PLUS_HEAT_PUMP.value: {
        "utilisation_factor": 0.85,
    },
    GeothermalConfiguration.OPEN_LOOP_PLUS_HEAT_PUMP.value: {
        "utilisation_factor": 0.90,
    },
}


def parameters_for_configuration(
    configuration: str,
    overrides: dict[str, Any] | None = None,
) -> ParameterSet:
    """Resolve the parameter set for a specific configuration."""
    base = ParameterSet.build(overrides=overrides)
    config_overrides = CONFIGURATION_OVERRIDES.get(configuration, {})
    for key, value in config_overrides.items():
        if not base.overrides_applied.get(key):
            base[key] = value
    return base
