"""Financial calculations.

Pure Python, no numpy, no external solver, so that every figure is reproducible
from the printed formula. `irr` uses a bracketed bisection on NPV, which cannot
fail to converge the way a naive Newton iteration can on the shallow, almost
linear cash flows typical of heat projects.

Rule enforced throughout: these functions answer "does the arithmetic work?".
They never answer "is this a good investment?". That judgement needs the
evidence confidence, the risk register and human review, and it is made
elsewhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from app.core.enums import EpistemicStatus
from app.engineering.base import (
    CalcResult,
    CalculationContext,
    CalculationError,
    SourceRef,
    Unit,
    require_positive,
)

SOURCE_FIN = SourceRef(
    name="HM Treasury Green Book and standard discounted cash flow methodology",
    url="https://www.gov.uk/government/publications/the-green-book-appraisal-and-evaluation-in-central-government",
    citation="Real discount rate for low-risk energy infrastructure commonly 3-8%; "
    "8% used as a screening rate",
)

DISCOUNT_RATE_DEFAULT = 0.08


class IrrResult(StrEnum):
    """Outcome of an IRR solution attempt."""

    SOLVED = "solved"
    NO_SIGN_CHANGE = "no_sign_change"
    MULTIPLE_ROOTS = "multiple_roots"
    NOT_CONVERGED = "not_converged"


@dataclass(frozen=True, slots=True)
class CashFlow:
    year: int
    capex: float
    opex: float
    revenue: float

    @property
    def net(self) -> float:
        return self.revenue - self.opex - self.capex


def lcoh(
    *,
    capex_gbp: float,
    annual_opex_gbp: float,
    annual_heat_kwh: float,
    discount_rate: float = DISCOUNT_RATE_DEFAULT,
    project_lifetime_years: int = 20,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Levelised cost of heat, in pence per kWh.

    Computed as the *equivalent uniform annual cost* divided by annual heat,
    which is the standard formulation:

    ``EUAC = capex * (r * (1+r)^n) / ((1+r)^n - 1) + opex``
    ``LCOH = EUAC / annual_heat_kwh * 100``

    This is preferred over ``capex / (heat * lifetime)`` because it accounts for
    the time value of money and so is directly comparable with a heat price.

    Args:
        capex_gbp: Total installed capital cost.
        annual_opex_gbp: Annual operating cost.
        annual_heat_kwh: Annual heat delivered to customers, after losses.
        discount_rate: Real discount rate as a fraction, e.g. 0.08.
        project_lifetime_years: Asset life used for capital recovery.

    Returns:
        CalcResult in p/kWh.

    Example:
        GBP 1.2m capex, GBP 45k/yr opex, 1.4 GWh/yr, 8%, 20 yr -> about 6.1 p/kWh.
    """
    require_positive(capex_gbp, "capex_gbp")
    require_positive(annual_opex_gbp, "annual_opex_gbp", allow_zero=True)
    require_positive(annual_heat_kwh, "annual_heat_kwh")
    require_positive(project_lifetime_years, "project_lifetime_years")
    if discount_rate <= -1.0:
        raise CalculationError(f"discount_rate must be > -1, got {discount_rate}")
    if discount_rate == 0.0:
        raise CalculationError(
            "discount_rate of zero is not supported; use lcoh_no_discounting()"
        )

    r = discount_rate
    n = project_lifetime_years
    annuity_factor = (r * (1 + r) ** n) / ((1 + r) ** n - 1)

    capital_recovery = capex_gbp * annuity_factor
    euac = capital_recovery + annual_opex_gbp
    cost_per_kwh = euac / annual_heat_kwh
    pence = cost_per_kwh * 100.0

    result = CalcResult(
        function_name="lcoh",
        result=pence,
        result_unit=Unit.PENCE_PER_KWH,
        inputs={
            "capex_gbp": capex_gbp,
            "annual_opex_gbp": annual_opex_gbp,
            "annual_heat_kwh": annual_heat_kwh,
            "discount_rate": discount_rate,
            "project_lifetime_years": n,
        },
        input_units={
            "capex_gbp": Unit.GBP,
            "annual_opex_gbp": Unit.GBP,
            "annual_heat_kwh": Unit.KWH,
            "discount_rate": Unit.DIMENSIONLESS,
            "project_lifetime_years": Unit.YEARS,
        },
        formula=(
            "EUAC = CAPEX * [r(1+r)^n / ((1+r)^n - 1)] + OPEX; "
            "LCOH = EUAC / annual_heat_kWh * 100"
        ),
        status=EpistemicStatus.DERIVED,
        sources=(SOURCE_FIN,),
        intermediate_values={
            "annuity_factor": annuity_factor,
            "capital_recovery_gbp": capital_recovery,
            "equivalent_uniform_annual_cost_gbp": euac,
            "cost_per_kwh_gbp": cost_per_kwh,
        },
        warnings=(
            "LCOH is computed from estimated capex, opex and heat output. It inherits "
            "the uncertainty of all three and is a screening indicator, not a tariff.",
        ),
        confidence=0.35,
    )
    return ctx.record(result) if ctx else result


def npv(
    *,
    initial_capex_gbp: float,
    cash_flows: list[float],
    discount_rate: float = DISCOUNT_RATE_DEFAULT,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Net present value of a cash flow series.

    ``NPV = sum_{t=1..n} CF_t / (1 + r)^t``

    Args:
        initial_capex_gbp: Outflow at t=0, positive number.
        cash_flows: Net cash flow for years 1..n. Negative values are permitted
            for years where major maintenance falls.
        discount_rate: Real discount rate as a fraction.

    Returns:
        CalcResult in GBP. A negative result means the scheme does not clear the
        discount rate on these inputs.
    """
    require_positive(initial_capex_gbp, "initial_capex_gbp", allow_zero=True)
    if not cash_flows:
        raise CalculationError("cash_flows must contain at least one year")
    if discount_rate <= -1.0:
        raise CalculationError(f"discount_rate must be > -1, got {discount_rate}")

    discounted = [cf / (1 + discount_rate) ** (t + 1) for t, cf in enumerate(cash_flows)]
    value = sum(discounted) - initial_capex_gbp

    result = CalcResult(
        function_name="npv",
        result=value,
        result_unit=Unit.GBP,
        inputs={
            "initial_capex_gbp": initial_capex_gbp,
            "cash_flows": cash_flows,
            "discount_rate": discount_rate,
        },
        input_units={
            "initial_capex_gbp": Unit.GBP,
            "cash_flows": "GBP per year",
            "discount_rate": Unit.DIMENSIONLESS,
        },
        formula="NPV = sum_{t=1..n} CF_t / (1 + r)^t - CAPEX_0",
        status=EpistemicStatus.DERIVED,
        sources=(SOURCE_FIN,),
        intermediate_values={
            "discounted_cash_flows": discounted,
            "pv_of_cash_flows": sum(discounted),
            "cumulative_discounted": sum(discounted) - initial_capex_gbp,
        },
        warnings=(
            "NPV is highly sensitive to the discount rate and to the assumed heat "
            "sales price. Both are assumptions at screening stage.",
        ),
        confidence=0.3,
    )
    return ctx.record(result) if ctx else result


def irr(
    *,
    initial_capex_gbp: float,
    cash_flows: list[float],
    low: float = -0.95,
    high: float = 10.0,
    tolerance: float = 1e-7,
    max_iterations: int = 300,
    max_bracket_expansions: int = 60,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Internal rate of return by bracketed bisection.

    ``IRR`` is the discount rate at which NPV = 0. Solved by bisection on a
    bracketed interval rather than Newton-Raphson because heat project cash
    flows are shallow and monotonic enough that bisection is both robust and
    trivially reproducible by hand.

    The bracket is expanded before solving. A fixed upper bound of, say, 1000%
    fails for a perfectly ordinary project: a 20-year annuity of 320 kW against
    a 2m outlay returns about 14%, but NPV is still positive at 1000% because a
    20-year annuity discounted at that rate still has substantial present
    value. A fixed bracket would report "no IRR exists" for a viable scheme.
    The bracket therefore widens until NPV actually changes sign, or until it is
    clear no plausible rate exists.

    Handles the realistic failure modes explicitly rather than returning ``NaN``:

    * every cash flow is positive, or none is: no IRR exists.
    * the cash flows change sign more than once: IRR is ambiguous and is not
      reported.
    * NPV never changes sign in any plausible range: no IRR exists, reported
      with the range that was searched.

    Returns:
        CalcResult where ``result`` is the IRR as a fraction (0.082 = 8.2%), or
        ``None`` when no valid IRR exists, with the reason in ``warnings`` and
        the outcome string in ``intermediate_values['outcome']``.
    """
    if not cash_flows:
        raise CalculationError("cash_flows must contain at least one year")

    # Build the sign profile of the whole project, t=0 included. The t=0 entry
    # is always an outflow, so it is unconditionally negative regardless of how
    # `initial_capex_gbp` is signed as an argument.
    #
    # Counting sign changes over the operating years alone would find zero
    # changes in every conventional project - outflow at t=0, inflows thereafter -
    # and would then wrongly report that no IRR exists.
    signs = [False] + [cf > 0 for cf in cash_flows]
    sign_changes = sum(1 for a, b in zip(signs, signs[1:], strict=False) if a != b)

    if all(signs) or not any(signs):
        reason = (
            "every cash flow in the project is an outflow or every one is an "
            "inflow, so the investment never turns from spending to earning and "
            "no IRR exists"
        )
        return _irr_failure(reason, IrrResult.NO_SIGN_CHANGE, ctx)

    if sign_changes > 1:
        reason = (
            f"cash flows change sign {sign_changes} times; IRR is ambiguous and is "
            "not reported. Use NPV and payback instead."
        )
        return _irr_failure(reason, IrrResult.MULTIPLE_ROOTS, ctx)

    def npv_at(rate: float) -> float:
        if rate <= -1.0:
            return float("inf")
        return sum(cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cash_flows)) - (
            initial_capex_gbp or 0.0
        )

    f_low = npv_at(low)

    # Widen the bracket until NPV changes sign. A long-life annuity can stay
    # NPV-positive at absurd discount rates, so a fixed upper bound would
    # wrongly declare a viable project to have no IRR.
    expansions = 0
    f_high = npv_at(high)
    while f_low * f_high > 0 and expansions < max_bracket_expansions:
        if f_low > 0 and f_high > 0:
            # Positive everywhere sampled: the capex is fully recovered even at
            # absurd rates, so the upper bound must move out. NPV tends to
            # -capex as the rate goes to infinity, so this terminates.
            high = high * 4.0 + 1.0 if high > 0 else 1.0
        elif f_low < 0 and f_high < 0:
            # Negative everywhere sampled: the capex is never recovered. The root
            # can only lie below `low`, so extend downwards instead.
            low = -0.95 if low > -0.9 else (1 + low) * 2.0 - 1.0
        else:
            break
        expansions += 1
        f_low, f_high = npv_at(low), npv_at(high)
        if low <= -1.0:
            break

    if math.isnan(f_low) or math.isnan(f_high):
        return _irr_failure("NPV is not defined at the bracket bounds", IrrResult.NOT_CONVERGED, ctx)

    if f_low * f_high > 0:
        if f_low > 0 and f_high > 0:
            reason = (
                f"NPV stays positive even at a discount rate of {high:.0%}, so the "
                "project does not have a finite IRR within any plausible range. "
                "Use NPV and payback instead."
            )
        else:
            reason = (
                f"NPV stays negative across the search range {low:.0%} to {high:.0%}. "
                "The project does not return the cost of capital at any rate in "
                "that range."
            )
        return _irr_failure(reason, IrrResult.NOT_CONVERGED, ctx)

    # Normalise so that `low` is always the numerically smaller bound. Swapping
    # the *values* without swapping which one carries f_low would break the
    # bisection invariant below and collapse the search onto the wrong interval.
    if low > high:
        low, high = high, low
        f_low, f_high = f_high, f_low

    iterations = 0
    mid = 0.0
    for iterations in range(1, max_iterations + 1):
        mid = (low + high) / 2.0
        f_mid = npv_at(mid)
        if abs(f_mid) < tolerance or (high - low) / 2.0 < tolerance:
            break
        # Retain whichever half still brackets the root.
        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid

    result = CalcResult(
        function_name="irr",
        result=mid,
        result_unit=Unit.DIMENSIONLESS,
        inputs={
            "initial_capex_gbp": initial_capex_gbp,
            "cash_flows": cash_flows,
            "bracket": [low, high],
            "tolerance": tolerance,
        },
        input_units={
            "initial_capex_gbp": Unit.GBP,
            "cash_flows": "GBP per year",
            "bracket": "-",
            "tolerance": Unit.GBP,
        },
        formula="IRR solves sum_{t=1..n} CF_t / (1 + IRR)^t - CAPEX_0 = 0 by bisection",
        status=EpistemicStatus.DERIVED,
        sources=(SOURCE_FIN,),
        intermediate_values={
            "iterations": float(iterations),
            "npv_at_irr": npv_at(mid),
            "outcome": str(IrrResult.SOLVED),
            "sign_changes": float(sign_changes),
            "bracket_expansions": float(expansions),
            "final_bracket": [low, high],
        },
        warnings=(
            "IRR assumes a conventional single-sign-change cash flow profile and a "
            "constant discount rate. It is not a measure of risk.",
        ),
        confidence=0.3,
    )
    return ctx.record(result) if ctx else result


def _irr_failure(reason: str, outcome: IrrResult, ctx: CalculationContext | None) -> CalcResult:
    result = CalcResult(
        function_name="irr",
        result=None,
        result_unit=Unit.DIMENSIONLESS,
        inputs={},
        input_units={},
        formula="IRR solves sum_{t=1..n} CF_t / (1 + IRR)^t - CAPEX_0 = 0",
        status=EpistemicStatus.UNKNOWN,
        intermediate_values={"outcome": str(outcome)},
        warnings=(reason,),
        confidence=0.0,
    )
    return ctx.record(result) if ctx else result


def payback(
    *,
    initial_capex_gbp: float,
    annual_cash_flow_gbp: float,
    discount_rate: float | None = None,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Simple and discounted payback, in years.

    ``simple_payback = capex / annual_net_cash_flow``
    ``discounted_payback``: year in which cumulative discounted cash flow first
    turns non-negative.

    Args:
        initial_capex_gbp: Outflow at t=0.
        annual_cash_flow_gbp: Constant net cash flow per year. Pass the actual
            series to :func:`discounted_payback` when cash flows vary.
        discount_rate: When supplied, a discounted payback is also reported in
            ``intermediate_values``.

    Returns:
        CalcResult in years. A payback longer than the project life is reported
        with a warning rather than clipped, so the reader sees the whole picture.
    """
    require_positive(initial_capex_gbp, "initial_capex_gbp", allow_zero=True)
    if annual_cash_flow_gbp is None or not math.isfinite(annual_cash_flow_gbp):
        raise CalculationError(
            f"annual_cash_flow_gbp must be a finite number, got {annual_cash_flow_gbp!r}"
        )
    require_positive(initial_capex_gbp, "initial_capex_gbp", allow_zero=True)

    if annual_cash_flow_gbp == 0:
        result = CalcResult(
            function_name="payback",
            result=None,
            result_unit=Unit.YEARS,
            inputs={
                "initial_capex_gbp": initial_capex_gbp,
                "annual_cash_flow_gbp": annual_cash_flow_gbp,
                "discount_rate": discount_rate,
            },
            input_units={
                "initial_capex_gbp": Unit.GBP,
                "annual_cash_flow_gbp": Unit.GBP,
                "discount_rate": Unit.DIMENSIONLESS,
            },
            formula="simple_payback = CAPEX / annual_net_cash_flow",
            status=EpistemicStatus.UNKNOWN,
            intermediate_values={"annual_cash_flow_gbp": 0.0},
            warnings=("Annual net cash flow is zero, so the capex is never recovered.",),
            confidence=0.0,
        )
        return ctx.record(result) if ctx else result

    if annual_cash_flow_gbp < 0:
        # A loss-making year is a normal screening outcome, not an input error.
        # Report the position rather than raising, so one bad case cannot abort a
        # whole national run.
        result = CalcResult(
            function_name="payback",
            result=None,
            result_unit=Unit.YEARS,
            inputs={
                "initial_capex_gbp": initial_capex_gbp,
                "annual_cash_flow_gbp": annual_cash_flow_gbp,
                "discount_rate": discount_rate,
            },
            input_units={
                "initial_capex_gbp": Unit.GBP,
                "annual_cash_flow_gbp": Unit.GBP,
                "discount_rate": Unit.DIMENSIONLESS,
            },
            formula="simple_payback = CAPEX / annual_net_cash_flow",
            status=EpistemicStatus.UNKNOWN,
            intermediate_values={"annual_cash_flow_gbp": annual_cash_flow_gbp},
            warnings=(
                f"Annual net cash flow is negative (GBP {annual_cash_flow_gbp:,.0f}), so "
                "the scheme does not recover its capital at any point and payback is "
                "undefined.",
            ),
            confidence=0.0,
        )
        return ctx.record(result) if ctx else result

    years = initial_capex_gbp / annual_cash_flow_gbp

    intermediate = {"annual_cash_flow_gbp": annual_cash_flow_gbp}
    warnings: list[str] = []

    if discount_rate is not None and discount_rate > -1.0:
        # Invert the annuity factor to find the year in which the discounted
        # stream first covers the capex.
        intermediate["discounted_payback_years"] = _solve_annuity_years(
            initial_capex_gbp, annual_cash_flow_gbp, discount_rate
        )

    if years > 25:
        warnings.append(
            f"Simple payback of {years:.1f} years exceeds the typical asset life; "
            "the scheme would not recover its capital within its own design life."
        )

    result = CalcResult(
        function_name="payback",
        result=years,
        result_unit=Unit.YEARS,
        inputs={
            "initial_capex_gbp": initial_capex_gbp,
            "annual_cash_flow_gbp": annual_cash_flow_gbp,
            "discount_rate": discount_rate,
        },
        input_units={
            "initial_capex_gbp": Unit.GBP,
            "annual_cash_flow_gbp": Unit.GBP,
            "discount_rate": Unit.DIMENSIONLESS,
        },
        formula="simple_payback = CAPEX / annual_net_cash_flow",
        status=EpistemicStatus.DERIVED,
        sources=(SOURCE_FIN,),
        intermediate_values=intermediate,
        warnings=tuple(warnings),
        confidence=0.5,
    )
    return ctx.record(result) if ctx else result


def _solve_annuity_years(
    capex: float, annual_cash_flow: float, discount_rate: float, max_years: int = 100
) -> float | None:
    """Smallest n where ``CF * [1 - (1+r)^-n] / r >= capex``."""
    if discount_rate <= 0:
        return capex / annual_cash_flow if annual_cash_flow > 0 else None
    for n in range(1, max_years + 1):
        pv = annual_cash_flow * (1 - (1 + discount_rate) ** (-n)) / discount_rate
        if pv >= capex:
            return float(n)
    return None


def discounted_payback(
    *,
    initial_capex_gbp: float,
    cash_flows: list[float],
    discount_rate: float = DISCOUNT_RATE_DEFAULT,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """First year in which cumulative discounted cash flow becomes non-negative.

    Supports an intra-year fraction by interpolating within the crossing year,
    which matters when comparing a 6.2-year payback against a 7-year one.
    """
    if not cash_flows:
        raise CalculationError("cash_flows must contain at least one year")
    if discount_rate <= -1.0:
        raise CalculationError(f"discount_rate must be > -1, got {discount_rate}")

    cumulative = -(initial_capex_gbp or 0.0)
    discounted: list[float] = []
    payback_year: float | None = None

    for t, cf in enumerate(cash_flows, start=1):
        dcf = cf / (1 + discount_rate) ** t
        discounted.append(dcf)
        previous = cumulative
        cumulative += dcf
        if cumulative >= 0 and payback_year is None:
            # Interpolate inside the crossing year.
            payback_year = (t - 1) + (0.0 if dcf == 0 else -previous / dcf)

    warnings: list[str] = []
    if payback_year is None:
        warnings.append(
            f"Cumulative discounted cash flow does not turn positive within "
            f"{len(cash_flows)} years; discounted payback exceeds the modelled life."
        )

    result = CalcResult(
        function_name="discounted_payback",
        result=payback_year,
        result_unit=Unit.YEARS,
        inputs={
            "initial_capex_gbp": initial_capex_gbp,
            "cash_flows": cash_flows,
            "discount_rate": discount_rate,
        },
        input_units={
            "initial_capex_gbp": Unit.GBP,
            "cash_flows": "GBP per year",
            "discount_rate": Unit.DIMENSIONLESS,
        },
        formula="payback = min{t : sum_{s=1..t} CF_s/(1+r)^s - CAPEX_0 >= 0}",
        status=EpistemicStatus.DERIVED,
        sources=(SOURCE_FIN,),
        intermediate_values={
            "cumulative_discounted": cumulative,
            "discounted_cash_flows": discounted,
        },
        warnings=tuple(warnings),
        confidence=0.5,
    )
    return ctx.record(result) if ctx else result


def break_even(
    *,
    capex_gbp: float,
    annual_opex_gbp: float,
    annual_heat_kwh: float,
    discount_rate: float = DISCOUNT_RATE_DEFAULT,
    project_lifetime_years: int = 20,
    electricity_price_p_per_kwh: float | None = None,
    heat_pump_cop: float | None = None,
    fixed_electricity_kw: float = 0.0,
    operating_hours_per_year: float = 3500.0,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """The heat and electricity prices at which the scheme breaks even.

    Break-even heat price is the price at which NPV = 0:

    ``p_break_even = [CAPEX * CRF + OPEX + electricity_cost] / annual_heat_kwh * 100``

    where ``CRF`` is the capital recovery factor. This single number is more
    useful to a screening analyst than LCOH, because it can be compared
    directly against the heat price the customer would actually pay.

    Also returns the electricity price at which the scheme breaks even when the
    heat price is held at zero, which bounds how exposed it is to power prices.

    Args:
        electricity_price_p_per_kwh: Price of imported electricity.
        heat_pump_cop: Required to size the electricity consumption.
        fixed_electricity_kw: Auxiliary electricity beyond the heat pump, e.g.
            circulation and control loads.

    Returns:
        CalcResult in p/kWh, with the electricity break-even in intermediate values.
    """
    require_positive(capex_gbp, "capex_gbp")
    require_positive(annual_opex_gbp, "annual_opex_gbp", allow_zero=True)
    require_positive(annual_heat_kwh, "annual_heat_kwh")
    require_positive(project_lifetime_years, "project_lifetime_years")

    r = discount_rate
    n = project_lifetime_years
    crf = (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    capital_recovery = capex_gbp * crf

    # Annual electricity to deliver a kWh of heat is 1/COP; auxiliary load is
    # sized on hours rather than on heat because it runs whenever the plant does.
    annual_electricity_kwh = 0.0
    if heat_pump_cop and electricity_price_p_per_kwh:
        annual_electricity_kwh = annual_heat_kwh / heat_pump_cop
        annual_electricity_kwh += fixed_electricity_kw * operating_hours_per_year

    electricity_cost_gbp = (annual_electricity_kwh * electricity_price_p_per_kwh / 100.0) if (
        electricity_price_p_per_kwh
    ) else 0.0

    break_even_pence = (
        (capital_recovery + annual_opex_gbp + electricity_cost_gbp) / annual_heat_kwh * 100.0
    )

    # Electricity price at which the scheme breaks even with zero heat revenue.
    energy_per_heat = 0.0
    if heat_pump_cop:
        energy_per_heat = 1.0 / heat_pump_cop
    aux_per_heat = (
        fixed_electricity_kw * operating_hours_per_year / annual_heat_kwh
        if annual_heat_kwh
        else 0.0
    )
    energy_per_heat += aux_per_heat

    fixed_cost_pence = (capital_recovery + annual_opex_gbp) / annual_heat_kwh * 100.0
    break_even_electricity_pence = (
        fixed_cost_pence / energy_per_heat if energy_per_heat > 0 else None
    )

    result = CalcResult(
        function_name="break_even",
        result=break_even_pence,
        result_unit=Unit.PENCE_PER_KWH,
        inputs={
            "capex_gbp": capex_gbp,
            "annual_opex_gbp": annual_opex_gbp,
            "annual_heat_kwh": annual_heat_kwh,
            "discount_rate": discount_rate,
            "project_lifetime_years": n,
            "electricity_price_p_per_kwh": electricity_price_p_per_kwh,
            "heat_pump_cop": heat_pump_cop,
            "fixed_electricity_kw": fixed_electricity_kw,
        },
        input_units={
            "capex_gbp": Unit.GBP,
            "annual_opex_gbp": Unit.GBP,
            "annual_heat_kwh": Unit.KWH,
            "discount_rate": Unit.DIMENSIONLESS,
            "project_lifetime_years": Unit.YEARS,
            "electricity_price_p_per_kwh": Unit.PENCE_PER_KWH,
            "heat_pump_cop": Unit.DIMENSIONLESS,
            "fixed_electricity_kw": "kW",
        },
        formula=(
            "p_break_even = [CAPEX*CRF + OPEX + electricity_cost] / annual_heat_kWh * 100"
        ),
        status=EpistemicStatus.DERIVED,
        sources=(SOURCE_FIN,),
        intermediate_values={
            "capital_recovery_factor": crf,
            "capital_recovery_gbp": capital_recovery,
            "annual_electricity_kwh": annual_electricity_kwh,
            "electricity_cost_gbp": electricity_cost_gbp,
            "break_even_electricity_price_p_per_kwh": break_even_electricity_pence,
            "energy_per_kwh_heat": energy_per_heat,
        },
        warnings=(
            "Break-even price is the price required to cover modelled costs at the "
            "stated discount rate. It excludes financing structure, tax, and any "
            "option value, and it assumes the heat is contracted at a flat price.",
        ),
        confidence=0.3,
    )
    return ctx.record(result) if ctx else result
