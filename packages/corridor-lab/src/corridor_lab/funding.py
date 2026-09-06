"""Bounded multi-period funding and liquidity analysis.

Everything in this module is driven by a declared synthetic schedule. Corridor
Lab does not manufacture arrival distributions, financing availability, or
forecasts: a period exists only because the scenario declares it.

Declared inputs
---------------
A ``corridor-lab.scenario/v2`` scenario may declare a ``funding`` object:

``opening_balance_send``
    The balance available at the start of period 1.

``days_per_period``
    The declared length of one period, used only to scale the annual capital
    cost to a period.

``settlement_delay_periods``
    Whole periods a disbursement remains unsettled after it is disbursed.
    Unsettled disbursements are still exposed, so they keep counting towards
    the settlement exposure metric.

``recovery_delay_periods``
    Whole periods before a declared recovery becomes available. A recovery
    declared for period ``i`` becomes available in period
    ``i + recovery_delay_periods``.

``periods``
    An ordered array of ``{period_index, disbursements_send,
    recoveries_send}`` entries.

Model
-----
With ``R_i`` the recoveries that have become available strictly before period
``i``, and ``D_i`` the disbursements of periods before ``i``:

```text
balance_start_i = opening_balance + sum(R_j for j < i) - sum(D_j for j < i)
trough_i        = balance_start_i - D_i
required_prefunding = max(0, max_i (D_i - (balance_start_i - opening_balance)))
shortfall           = max(0, required_prefunding - opening_balance)
average_tied_up_capital = mean_i max(0, balance_start_i)
carrying_cost = sum_i max(0, balance_start_i) * c / 10000 * days_per_period / 365
settlement_exposure_i = sum(D_j for j where i < j + settlement_delay_periods)
```

Three distinct quantities are deliberately kept apart:

``required_prefunding_send``
    Peak funding that must be available. It is independent of the declared
    opening balance.

``average_tied_up_capital_send``
    A holding statistic given the declared opening balance. It is not a loss.

``expected_loss_send``
    The route's declared per-transaction loss rate applied to the declared total
    disbursements. Loss is not capital tied up, and capital tied up is not loss.

Recoveries whose declared arrival period falls beyond the last declared period
are reported as ``recoveries_after_horizon_send`` rather than being silently
dropped, so the end of a schedule is never mistaken for full recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import TYPE_CHECKING, Any

from .canonical import (
    BPS_DENOMINATOR,
    DAYS_PER_YEAR,
    MAX_FUNDING_DELAY_VALUES,
    MAX_FUNDING_PERIODS,
    MAX_FUNDING_ROWS,
    InputError,
    decimal_text,
    local_decimal_context,
    money_text,
    require_decimal,
    require_integer,
    require_keys,
    require_object,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; avoids a scenario import cycle
    from .scenario import Scenario

REPORT_VERSION = "corridor-lab.funding/v1"


@dataclass(frozen=True)
class FundingPeriod:
    period_index: int
    disbursements_send: Decimal
    recoveries_send: Decimal


@dataclass(frozen=True)
class FundingSchedule:
    opening_balance_send: Decimal
    days_per_period: Decimal
    settlement_delay_periods: int
    recovery_delay_periods: int
    periods: tuple[FundingPeriod, ...]


@dataclass(frozen=True)
class PeriodRow:
    """One declared period.

    ``recoveries_declared_send`` is what the schedule says this period recovers.
    ``recoveries_arriving_send`` is what actually arrives in this period after
    the declared recovery delay, so it is available for disbursement from the
    next period onward. The two differ whenever the recovery delay is non-zero.
    """

    period_index: int
    balance_start_send: Decimal
    disbursements_send: Decimal
    recoveries_declared_send: Decimal
    recoveries_arriving_send: Decimal
    trough_send: Decimal
    unsettled_exposure_send: Decimal


@dataclass(frozen=True)
class FundingAnalysis:
    recovery_delay_periods: int
    total_disbursements_send: Decimal
    total_recoveries_send: Decimal
    recoveries_after_horizon_send: Decimal
    required_prefunding_send: Decimal
    declared_opening_balance_send: Decimal
    shortfall_send: Decimal
    shortfall_periods: tuple[int, ...]
    average_tied_up_capital_send: Decimal
    peak_settlement_exposure_send: Decimal
    carrying_cost_send: Decimal
    expected_loss_send: Decimal
    periods: tuple[PeriodRow, ...]


def parse_funding(value: Any) -> FundingSchedule:
    path = "scenario.funding"
    item = require_object(value, path)
    require_keys(
        item,
        {"opening_balance_send", "days_per_period", "periods"},
        {"settlement_delay_periods", "recovery_delay_periods"},
        path,
    )
    periods = _parse_periods(item["periods"], f"{path}.periods")
    return FundingSchedule(
        opening_balance_send=require_decimal(
            item["opening_balance_send"], f"{path}.opening_balance_send", minimum=Decimal("0")
        ),
        days_per_period=require_decimal(item["days_per_period"], f"{path}.days_per_period", positive=True),
        settlement_delay_periods=require_integer(
            item.get("settlement_delay_periods", 0),
            f"{path}.settlement_delay_periods",
            minimum=0,
            maximum=MAX_FUNDING_PERIODS,
        ),
        recovery_delay_periods=require_integer(
            item.get("recovery_delay_periods", 0),
            f"{path}.recovery_delay_periods",
            minimum=0,
            maximum=MAX_FUNDING_PERIODS,
        ),
        periods=periods,
    )


def _parse_periods(value: Any, path: str) -> tuple[FundingPeriod, ...]:
    if not isinstance(value, list) or not value:
        raise InputError(f"{path} must be a non-empty array")
    if len(value) > MAX_FUNDING_PERIODS:
        raise InputError(f"{path} exceeds the {MAX_FUNDING_PERIODS}-period budget")
    parsed: list[FundingPeriod] = []
    previous_index = 0
    for position, raw in enumerate(value):
        location = f"{path}[{position}]"
        item = require_object(raw, location)
        require_keys(item, {"period_index", "disbursements_send", "recoveries_send"}, set(), location)
        period_index = require_integer(
            item["period_index"], f"{location}.period_index", minimum=1, maximum=MAX_FUNDING_PERIODS
        )
        if period_index <= previous_index:
            raise InputError(f"{location}.period_index must increase across the declared schedule")
        previous_index = period_index
        parsed.append(
            FundingPeriod(
                period_index=period_index,
                disbursements_send=require_decimal(
                    item["disbursements_send"], f"{location}.disbursements_send", minimum=Decimal("0")
                ),
                recoveries_send=require_decimal(
                    item["recoveries_send"], f"{location}.recoveries_send", minimum=Decimal("0")
                ),
            )
        )
    return tuple(parsed)


def _available_recoveries(
    schedule: FundingSchedule, recovery_delay_periods: int, horizon: int
) -> dict[int, Decimal]:
    """Map a 1-based period number to the recoveries arriving in it."""
    arriving: dict[int, Decimal] = {}
    for period in schedule.periods:
        arrival = period.period_index + recovery_delay_periods
        arriving[arrival] = arriving.get(arrival, Decimal("0")) + period.recoveries_send
    return {index: value for index, value in arriving.items() if index <= horizon}


def analyse_funding(
    schedule: FundingSchedule,
    *,
    annual_cost_of_capital_bps: Decimal,
    loss_rate: Decimal,
    recovery_delay_periods: int | None = None,
) -> FundingAnalysis:
    """Evaluate a declared funding schedule for one route's declared parameters.

    ``loss_rate`` is a dimensionless declared fraction of principal that is not
    recovered; it is applied to the declared total disbursements.
    """
    delay = schedule.recovery_delay_periods if recovery_delay_periods is None else recovery_delay_periods
    delay = require_integer(delay, "recovery_delay_periods", minimum=0, maximum=MAX_FUNDING_PERIODS)
    try:
        with local_decimal_context():
            horizon = schedule.periods[-1].period_index
            arriving = _available_recoveries(schedule, delay, horizon)
            rows: list[PeriodRow] = []
            balance = schedule.opening_balance_send
            available_before = Decimal("0")
            disbursed_before = Decimal("0")
            required = Decimal("0")
            tied_up_total = Decimal("0")
            peak_exposure = Decimal("0")
            shortfall_periods: list[int] = []
            for period in schedule.periods:
                recoveries_available = arriving.get(period.period_index, Decimal("0"))
                balance_start = schedule.opening_balance_send + available_before - disbursed_before
                trough = balance_start - period.disbursements_send
                if trough < 0:
                    shortfall_periods.append(period.period_index)
                needed = period.disbursements_send - (available_before - disbursed_before)
                if needed > required:
                    required = needed
                if balance_start > 0:
                    tied_up_total += balance_start
                exposure = _settlement_exposure(schedule, period.period_index, schedule.settlement_delay_periods)
                if exposure > peak_exposure:
                    peak_exposure = exposure
                rows.append(
                    PeriodRow(
                        period_index=period.period_index,
                        balance_start_send=balance_start,
                        disbursements_send=period.disbursements_send,
                        recoveries_declared_send=period.recoveries_send,
                        recoveries_arriving_send=recoveries_available,
                        trough_send=trough,
                        unsettled_exposure_send=exposure,
                    )
                )
                available_before += recoveries_available
                disbursed_before += period.disbursements_send
            count = Decimal(len(schedule.periods))
            average_tied_up = tied_up_total / count
            carrying_cost = (
                tied_up_total * annual_cost_of_capital_bps / BPS_DENOMINATOR * schedule.days_per_period / DAYS_PER_YEAR
            )
            total_disbursed = sum((period.disbursements_send for period in schedule.periods), Decimal("0"))
            total_recoveries = sum((period.recoveries_send for period in schedule.periods), Decimal("0"))
            after_horizon = total_recoveries - sum(arriving.values(), Decimal("0"))
            return FundingAnalysis(
                recovery_delay_periods=delay,
                total_disbursements_send=total_disbursed,
                total_recoveries_send=total_recoveries,
                recoveries_after_horizon_send=after_horizon,
                required_prefunding_send=max(Decimal("0"), required),
                declared_opening_balance_send=schedule.opening_balance_send,
                shortfall_send=max(Decimal("0"), required - schedule.opening_balance_send),
                shortfall_periods=tuple(shortfall_periods),
                average_tied_up_capital_send=average_tied_up,
                peak_settlement_exposure_send=peak_exposure,
                carrying_cost_send=carrying_cost,
                expected_loss_send=total_disbursed * loss_rate,
                periods=tuple(rows),
            )
    except DecimalException as exc:
        raise InputError("funding calculation failed") from exc


def _settlement_exposure(schedule: FundingSchedule, period_index: int, settlement_delay: int) -> Decimal:
    """Disbursements made by `period_index` that are still unsettled at its end."""
    with local_decimal_context():
        return sum(
            (
                period.disbursements_send
                for period in schedule.periods
                if period.period_index <= period_index < period.period_index + settlement_delay
            ),
            Decimal("0"),
        )


def run_funding(scenario: Scenario, delays: list[int] | tuple[int, ...] | None = None) -> dict[str, object]:
    """Evaluate every route against the scenario's declared funding schedule."""
    if scenario.funding is None:
        raise InputError("this scenario declares no funding schedule")
    if not scenario.routes:
        raise InputError("funding analysis requires routes embedded in the scenario")
    delay_values = _resolve_delays(scenario.funding, delays)
    if len(scenario.routes) * len(delay_values) > MAX_FUNDING_ROWS:
        raise InputError(f"funding analysis exceeds the {MAX_FUNDING_ROWS}-row budget")
    precision = scenario.transaction.send_precision
    rounding = scenario.transaction.rounding
    rows: list[dict[str, object]] = []
    details: list[dict[str, object]] = []
    for route in sorted(scenario.routes, key=lambda item: item.route_id):
        loss_rate = _loss_rate(route, scenario)
        for delay in delay_values:
            analysis = analyse_funding(
                scenario.funding,
                annual_cost_of_capital_bps=route.liquidity.annual_cost_of_capital_bps,
                loss_rate=loss_rate,
                recovery_delay_periods=delay,
            )
            rows.append(_funding_row(route.route_id, analysis, precision, rounding))
            details.append(
                {
                    "route_id": route.route_id,
                    "recovery_delay_periods": str(delay),
                    "periods": [
                        {
                            "period_index": str(period.period_index),
                            "balance_start_send": money_text(period.balance_start_send, precision, rounding),
                            "disbursements_send": money_text(period.disbursements_send, precision, rounding),
                            "recoveries_declared_send": money_text(
                                period.recoveries_declared_send, precision, rounding
                            ),
                            "recoveries_arriving_send": money_text(
                                period.recoveries_arriving_send, precision, rounding
                            ),
                            "trough_send": money_text(period.trough_send, precision, rounding),
                            "unsettled_exposure_send": money_text(
                                period.unsettled_exposure_send, precision, rounding
                            ),
                        }
                        for period in analysis.periods
                    ],
                }
            )
    return {
        "report_version": REPORT_VERSION,
        "scenario_id": scenario.scenario_id,
        "fictional": True,
        "send_currency": scenario.transaction.send_currency,
        "declared_schedule": _declared_schedule(scenario.funding),
        "delays": [str(delay) for delay in delay_values],
        "rows": rows,
        "period_detail": details,
    }


def _loss_rate(route: Any, scenario: "Scenario") -> Decimal:
    """Declared fraction of principal not recovered, per transaction."""
    from .model import evaluate_route

    evaluation = evaluate_route(route, scenario.transaction)
    with local_decimal_context():
        if scenario.transaction.send_amount == 0:
            return Decimal("0")
        return evaluation.expected_failure_recovery_cost_send / scenario.transaction.send_amount


def _resolve_delays(schedule: FundingSchedule, delays: list[int] | tuple[int, ...] | None) -> list[int]:
    if delays is None:
        return [schedule.recovery_delay_periods]
    parsed = [require_integer(delay, "funding delay", minimum=0, maximum=MAX_FUNDING_PERIODS) for delay in delays]
    if not parsed:
        raise InputError("funding delays must not be empty")
    if len(parsed) > MAX_FUNDING_DELAY_VALUES:
        raise InputError(f"funding delays exceed the {MAX_FUNDING_DELAY_VALUES}-value budget")
    seen = set()
    ordered = []
    for value in parsed:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _funding_row(route_id: str, analysis: FundingAnalysis, precision: int, rounding: str) -> dict[str, object]:
    text = lambda value: money_text(value, precision, rounding)  # noqa: E731
    return {
        "route_id": route_id,
        "recovery_delay_periods": str(analysis.recovery_delay_periods),
        "total_disbursements_send": text(analysis.total_disbursements_send),
        "total_recoveries_send": text(analysis.total_recoveries_send),
        "recoveries_after_horizon_send": text(analysis.recoveries_after_horizon_send),
        "required_prefunding_send": text(analysis.required_prefunding_send),
        "declared_opening_balance_send": text(analysis.declared_opening_balance_send),
        "shortfall_send": text(analysis.shortfall_send),
        "shortfall_periods": ",".join(str(index) for index in analysis.shortfall_periods),
        "average_tied_up_capital_send": text(analysis.average_tied_up_capital_send),
        "peak_settlement_exposure_send": text(analysis.peak_settlement_exposure_send),
        "carrying_cost_send": text(analysis.carrying_cost_send),
        "expected_loss_send": text(analysis.expected_loss_send),
    }


def _declared_schedule(schedule: FundingSchedule) -> dict[str, object]:
    return {
        "opening_balance_send": decimal_text(schedule.opening_balance_send),
        "days_per_period": decimal_text(schedule.days_per_period),
        "settlement_delay_periods": schedule.settlement_delay_periods,
        "recovery_delay_periods": schedule.recovery_delay_periods,
        "periods": [
            {
                "period_index": period.period_index,
                "disbursements_send": decimal_text(period.disbursements_send),
                "recoveries_send": decimal_text(period.recoveries_send),
            }
            for period in schedule.periods
        ],
    }
