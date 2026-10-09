"""Calculation primitives: units, provenance labels and the traceable result type.

Every deterministic engineering function in this package returns a
:class:`CalcResult`. That is the mechanism by which the platform satisfies two
of its hard requirements at once:

* every calculation exposes its input, unit, formula, result, assumption and source;
* every calculation carries an epistemic label, so a `DERIVED` number can never be
  presented as a `MEASURED` one.

The LLM layer receives these objects as context and is forbidden from
recomputing any of them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.enums import EpistemicStatus

ENGINE_VERSION = "0.1.0"
"""Bumped whenever a formula changes. Stored on every trace and analysis."""


class Unit(StrEnum):
    """Canonical units. Functions convert at their boundary, not inside."""

    # Temperature
    CELSIUS = "degC"
    KELVIN = "K"
    DELTA_C = "delta_degC"
    GRADIENT_C_PER_KM = "degC_per_km"
    # Flow
    LITRES_PER_SECOND = "L/s"
    CUBIC_METRES_PER_SECOND = "m3/s"
    KILOGRAMMS_PER_SECOND = "kg/s"
    # Power / energy
    WATT = "W"
    KILOWATT = "kW"
    MEGAWATT = "MW"
    THERMAL_MEGAWATT = "MWt"
    ELECTRICAL_MEGAWATT = "MWe"
    KWH = "kWh"
    GWH = "GWh"
    MWH = "MWh"
    # Money
    GBP = "GBP"
    PENCE_PER_KWH = "p/kWh"
    # Misc
    YEARS = "years"
    PERCENT = "%"
    METRES = "m"
    DIMENSIONLESS = "-"
    HOURS = "h"
    PSI = "psi"
    BAR = "bar"
    MD_M = "m"
    CO2_KG_PER_KWH = "kgCO2e/kWh"


class CalculationError(ValueError):
    """Raised when inputs cannot support a defensible calculation.

    Raised rather than returning `None`, so that a missing input surfaces as a
    visible data gap instead of a silent zero propagating into the financials.
    """


@dataclass(frozen=True, slots=True)
class AssumptionRef:
    """Pointer to an assumption row, with the value actually used."""

    key: str
    value: Any
    unit: Unit | str | None = None
    rationale: str | None = None
    is_default: bool = True


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Pointer to the evidence or publication a value or formula comes from."""

    name: str
    url: str | None = None
    citation: str | None = None


@dataclass(frozen=True, slots=True)
class CalcResult:
    """The return type of every function in :mod:`app.engineering`.

    Attributes mirror the six exposures the specification requires, plus the
    provenance label and any warnings raised during the calculation.
    """

    function_name: str
    result: float | None
    result_unit: Unit | str
    inputs: dict[str, Any]
    input_units: dict[str, str]
    formula: str
    status: EpistemicStatus
    assumptions: tuple[AssumptionRef, ...] = ()
    sources: tuple[SourceRef, ...] = ()
    intermediate_values: dict[str, float] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    confidence: float | None = None
    engine_version: str = ENGINE_VERSION

    @property
    def is_valid(self) -> bool:
        """True when a finite, non-None result was produced."""
        return self.result is not None and math.isfinite(self.result)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for API responses, traces and agent context."""
        return {
            "function_name": self.function_name,
            "result": self.result,
            "result_unit": str(self.result_unit),
            "inputs": self.inputs,
            "input_units": self.input_units,
            "formula": self.formula,
            "status": str(self.status),
            "assumptions": [
                {
                    "key": a.key,
                    "value": a.value,
                    "unit": str(a.unit) if a.unit else None,
                    "rationale": a.rationale,
                    "is_default": a.is_default,
                }
                for a in self.assumptions
            ],
            "sources": [
                {"name": s.name, "url": s.url, "citation": s.citation} for s in self.sources
            ],
            "intermediate_values": self.intermediate_values,
            "warnings": list(self.warnings),
            "confidence": self.confidence,
            "engine_version": self.engine_version,
        }

    def raise_if_invalid(self) -> CalcResult:
        if not self.is_valid:
            raise CalculationError(
                f"{self.function_name} produced no usable result "
                f"(status={self.status}, warnings={self.warnings})"
            )
        return self


class CalculationContext:
    """Per-well collection of traces and warnings.

    Functions accept an optional context and append to it. This is how a full
    analysis accumulates an audit trail without threading a global.
    """

    __slots__ = ("traces", "warnings", "assumptions", "sources", "_seen_warnings")

    def __init__(self) -> None:
        self.traces: list[CalcResult] = []
        self.warnings: list[str] = []
        self.assumptions: dict[str, AssumptionRef] = {}
        self.sources: list[SourceRef] = []
        self._seen_warnings: set[str] = set()

    def record(self, result: CalcResult) -> CalcResult:
        self.traces.append(result)
        for w in result.warnings:
            self.add_warning(f"{result.function_name}: {w}")
        return result

    def add_warning(self, message: str) -> None:
        if message not in self._seen_warnings:
            self._seen_warnings.add(message)
            self.warnings.append(message)

    def add_assumption(self, ref: AssumptionRef) -> AssumptionRef:
        self.assumptions[ref.key] = ref
        return ref

    def add_source(self, source: SourceRef) -> None:
        if source not in self.sources:
            self.sources.append(source)

    def result_of(self, function_name: str) -> CalcResult | None:
        for trace in reversed(self.traces):
            if trace.function_name == function_name:
                return trace
        return None

    def value_of(self, function_name: str) -> float | None:
        trace = self.result_of(function_name)
        return trace.result if trace else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "traces": [t.to_dict() for t in self.traces],
            "warnings": list(self.warnings),
            "assumptions": {k: v.value for k, v in self.assumptions.items()},
            "sources": [{"name": s.name, "url": s.url} for s in self.sources],
            "engine_version": ENGINE_VERSION,
        }


def require_positive(value: float | None, name: str, *, allow_zero: bool = False) -> float:
    """Validate a strictly positive (or non-negative) input.

    Every engineering function starts with this on its inputs. It is the main
    defence against a negative flow rate producing a negative power figure.
    """
    if value is None:
        raise CalculationError(f"{name} is required but was None")
    if not math.isfinite(value):
        raise CalculationError(f"{name} must be finite, got {value}")
    if value < 0 or (value == 0 and not allow_zero):
        raise CalculationError(f"{name} must be {'>= 0' if allow_zero else '> 0'}, got {value}")
    return value


def warn_on_extrapolation(ctx: CalculationContext | None, message: str) -> None:
    if ctx is not None:
        ctx.add_warning(message)


def blend(*pairs: tuple[float, float]) -> float:
    """Weighted mean helper used by several scoring functions."""
    num = sum(value * weight for value, weight in pairs)
    den = sum(weight for _, weight in pairs)
    if den == 0:
        raise CalculationError("blend() requires a non-zero total weight")
    return num / den
