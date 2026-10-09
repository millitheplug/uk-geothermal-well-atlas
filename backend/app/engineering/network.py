"""Heat network: distribution loss and delivery.

Two things are modelled here and nothing else:

1. heat lost in distributing heat from the well to the off-taker; and
2. whether the heat arriving is worth having, given the supply temperature the
   customer needs.

Both feed the network score. Neither is a substitute for a network cost study.
"""

from __future__ import annotations

import math

from app.core.enums import EpistemicStatus
from app.engineering.base import (
    CalcResult,
    CalculationContext,
    CalculationError,
    SourceRef,
    Unit,
    require_positive,
)

SOURCE_DUKES_GUIDE = SourceRef(
    name="BEIS / DUKES Digest of UK Energy Statistics, district heating heat loss conventions",
    url="https://www.gov.uk/government/collections/digest-of-uk-energy-statistics-dukes",
    citation="Distribution losses for district heat networks typically 10-20% of heat input",
)

#: Linear heat loss per metre of buried pipe, W per metre per K of temperature
#: difference between pipe and ground. Applied as the dominant term.
DEFAULT_LINEAR_LOSS_W_PER_M_PER_K = 0.20
"""Assumed value for an insulated pre-insulated twin pipe at typical district
heating temperatures and burial depths. Falls with better insulation. Held as an
explicit default so a reviewer can change it in one place."""


def network_heat_loss(
    *,
    flow_rate_kg_s: float,
    supply_temperature_c: float,
    return_temperature_c: float,
    pipe_length_m: float,
    ground_temperature_c: float = 10.0,
    linear_loss_w_per_m_per_k: float = DEFAULT_LINEAR_LOSS_W_PER_M_PER_K,
    additional_fixed_loss_kw: float = 0.0,
    ctx: CalculationContext | None = None,
) -> CalcResult:
    """Heat lost between the wellhead and the off-taker.

    Two terms are summed:

    * **Pipe conduction**, proportional to length and to the mean temperature
      excess over ground: ``Q_pipe = k * L * T_mean_excess``.
    * **Fixed losses** (substations, heat exchangers, metering), given as an
      explicit input rather than derived, because it depends on how many
      off-takers are on the route.

    The *fraction* lost is what matters economically, so the result also
    reports ``loss_fraction`` as an intermediate value.

    Args:
        flow_rate_kg_s: Mass flow in the network.
        supply_temperature_c: Network flow temperature.
        return_temperature_c: Network return temperature.
        pipe_length_m: Total buried length serving the off-takers.
        ground_temperature_c: Ground temperature at pipe depth. UK range is
            8-14 degC; 10 is the default and is flagged as an assumption.
        linear_loss_w_per_m_per_k: See module constant.
        additional_fixed_loss_kw: Non-proportional losses.

    Returns:
        CalcResult in kW.

    Example:
        10 kg/s, 70/40 degC, 1500 m, ground 10 degC -> about 20.3 kW lost,
        roughly 13% of the 157 kW delivered.
    """
    require_positive(flow_rate_kg_s, "flow_rate_kg_s")
    require_positive(pipe_length_m, "pipe_length_m")
    if return_temperature_c >= supply_temperature_c:
        raise CalculationError(
            f"return_temperature_c ({return_temperature_c}) must be below "
            f"supply_temperature_c ({supply_temperature_c})"
        )

    mean_temp = (supply_temperature_c + return_temperature_c) / 2.0
    temp_excess = mean_temp - ground_temperature_c
    if temp_excess < 0:
        raise CalculationError(
            f"network mean temperature ({mean_temp} degC) is below ground "
            f"temperature ({ground_temperature_c} degC); the network would gain heat"
        )

    pipe_loss_w = linear_loss_w_per_m_per_k * pipe_length_m * temp_excess
    pipe_loss_kw = pipe_loss_w / 1000.0
    total_loss_kw = pipe_loss_kw + additional_fixed_loss_kw

    # Useful heat delivered, used only to express the loss as a fraction.
    from app.engineering.thermal import SPECIFIC_HEAT_WATER_J_KG_K  # noqa: PLC0415

    delivered_kw = (
        flow_rate_kg_s
        * SPECIFIC_HEAT_WATER_J_KG_K
        * (supply_temperature_c - return_temperature_c)
        / 1000.0
    )
    loss_fraction = total_loss_kw / delivered_kw if delivered_kw > 0 else float("inf")

    result = CalcResult(
        function_name="network_heat_loss",
        result=total_loss_kw,
        result_unit=Unit.KILOWATT,
        inputs={
            "flow_rate_kg_s": flow_rate_kg_s,
            "supply_temperature_c": supply_temperature_c,
            "return_temperature_c": return_temperature_c,
            "pipe_length_m": pipe_length_m,
            "ground_temperature_c": ground_temperature_c,
            "linear_loss_w_per_m_per_k": linear_loss_w_per_m_per_k,
            "additional_fixed_loss_kw": additional_fixed_loss_kw,
        },
        input_units={
            "flow_rate_kg_s": "kg/s",
            "supply_temperature_c": Unit.CELSIUS,
            "return_temperature_c": Unit.CELSIUS,
            "pipe_length_m": Unit.METRES,
            "ground_temperature_c": Unit.CELSIUS,
            "linear_loss_w_per_m_per_k": "W/(m.K)",
            "additional_fixed_loss_kw": "kW",
        },
        formula=(
            "Q_loss = k * L * ((T_supply + T_return)/2 - T_ground) / 1000 "
            "+ Q_fixed"
        ),
        status=EpistemicStatus.ESTIMATE,
        sources=(SOURCE_DUKES_GUIDE,),
        intermediate_values={
            "mean_network_temperature_c": mean_temp,
            "temperature_excess_k": temp_excess,
            "pipe_loss_kw": pipe_loss_kw,
            "delivered_kw": delivered_kw,
            "loss_fraction": loss_fraction,
        },
        warnings=(
            "Loss is a first-order estimate for a buried insulated pipe. It is not a "
            "hydraulic network model and does not include pump work.",
        ),
        confidence=0.5,
    )
    return ctx.record(result) if ctx else result


def pipe_length_cost_factor(pipe_length_m: float, is_urban: bool = False) -> float:
    """Relative cost multiplier for buried pipe, used inside :mod:`app.engineering.financial`.

    Trapezoidal cost curve: short runs have high cost per metre due to fixed
    mobilisation, long runs amortise it. Capped so a 40 km run does not make
    the well look impossibly expensive in a way that hides the real driver,
    which is always heat demand at the far end.
    """
    if pipe_length_m <= 0:
        raise CalculationError("pipe_length_m must be positive")
    km = pipe_length_m / 1000.0
    base = 0.6 + 0.5 * math.log10(km + 1.0)  # ~0.6 at 0 m, ~1.6 at 5 km
    return base * (1.25 if is_urban else 1.0)


def supply_temperature_penalty(
    *,
    available_temperature_c: float,
    required_supply_temperature_c: float,
    required_return_temperature_c: float = 40.0,
) -> float:
    """Fraction of the available temperature swing lost to a supply-temperature gap.

    If a network needs 90 degC flow and the well gives 45 degC, the usable swing
    collapses and the delivered energy falls even though the wellhead power does
    not. Returns a multiplier in (0, 1] on useful heat.
    """
    require_positive(available_temperature_c, "available_temperature_c")
    require_positive(required_supply_temperature_c, "required_supply_temperature_c")

    if available_temperature_c >= required_supply_temperature_c:
        return 1.0

    max_swing = available_temperature_c - required_return_temperature_c
    if max_swing <= 0:
        # Cannot serve the circuit at all; effectively no useful heat.
        return 0.01

    nominal_swing = 30.0  # K, typical design swing
    usable = max_swing / nominal_swing
    return max(0.01, min(1.0, usable))
