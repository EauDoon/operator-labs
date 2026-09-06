"""Bounded declared-volume (workload) scenario analysis.

A workload is an author-declared number of transactions per period. Corridor Lab
never derives one from data: a workload exists only when the scenario declares
it under ``scenario.workload_scenarios``.

What the analysis shows
-----------------------
For every declared workload and every route it reports:

``explicit_fee_send``
    Per-transaction explicit fee under that volume. Only period charges
    declared with ``amortization_over: scenario_volume`` move with the volume;
    transaction-level fees do not.

``liquidity_carry_cost_send``
    The route's declared prefunding carrying cost divided by the workload's
    declared transactions per period.

``period_explicit_fee_send`` and ``period_expected_sender_cost_send``
    The same per-transaction figures multiplied by the declared transactions per
    period. These are deterministic arithmetic on declared inputs, not a budget
    forecast.

Amounts are aggregated only within the scenario's declared send currency for
sender-cost columns and its declared receive currency for recipient columns.
No currency conversion is applied to sender cost.
"""

from __future__ import annotations

from decimal import Decimal

from .canonical import MAX_WORKLOAD_ROWS, InputError, decimal_text, local_decimal_context
from .model import evaluate_route_at_volume, money_text
from .scenario import Scenario, Workload

REPORT_VERSION = "corridor-lab.workload/v1"


def select_workloads(scenario: Scenario, identifiers: list[str] | tuple[str, ...] | None) -> tuple[Workload, ...]:
    """Return the declared workloads in declaration order, optionally filtered."""
    if not scenario.workloads:
        raise InputError(
            "this scenario declares no workload_scenarios; add declared workload "
            "assumptions to a corridor-lab.scenario/v2 scenario first"
        )
    if identifiers is None:
        return scenario.workloads
    wanted = {text.strip() for text in identifiers if text.strip()}
    if not wanted:
        raise InputError("workload selection must not be empty")
    selected = tuple(workload for workload in scenario.workloads if workload.workload_id in wanted)
    missing = sorted(wanted - {workload.workload_id for workload in selected})
    if missing:
        raise InputError(f"unknown workload id(s): {', '.join(missing)}")
    return selected


def run_workload(scenario: Scenario, identifiers: list[str] | tuple[str, ...] | None = None) -> dict[str, object]:
    """Evaluate every route under each selected declared workload."""
    if not scenario.routes:
        raise InputError("workload analysis requires routes embedded in the scenario")
    workloads = select_workloads(scenario, identifiers)
    if len(scenario.routes) * len(workloads) > MAX_WORKLOAD_ROWS:
        raise InputError(f"workload analysis exceeds the {MAX_WORKLOAD_ROWS}-row budget")
    rows: list[dict[str, object]] = []
    for workload in workloads:
        for route in sorted(scenario.routes, key=lambda item: item.route_id):
            evaluation = evaluate_route_at_volume(route, scenario.transaction, workload.transactions_per_period)
            metrics = evaluation.as_dict()
            precision = scenario.transaction.send_precision
            rounding = scenario.transaction.rounding
            with local_decimal_context():
                period_fee = evaluation.explicit_fee_send * workload.transactions_per_period
                period_cost = evaluation.expected_sender_cost * workload.transactions_per_period
            rows.append(
                {
                    "workload_id": workload.workload_id,
                    "workload_label": workload.label,
                    "route_id": route.route_id,
                    "transactions_per_period": decimal_text(workload.transactions_per_period),
                    "fee_basis": metrics["fee_basis"],
                    "explicit_fee_send": metrics["explicit_fee_send"],
                    "explicit_fee_transaction_send": metrics["explicit_fee_transaction_send"],
                    "explicit_fee_period_amortized_send": metrics["explicit_fee_period_amortized_send"],
                    "liquidity_carry_cost_send": metrics["liquidity_carry_cost_send"],
                    "expected_failure_recovery_cost_send": metrics["expected_failure_recovery_cost_send"],
                    "expected_sender_cost": metrics["expected_sender_cost"],
                    "period_explicit_fee_send": money_text(period_fee, precision, rounding),
                    "period_expected_sender_cost_send": money_text(period_cost, precision, rounding),
                    "recipient_amount": metrics["recipient_amount"],
                    "expected_recipient_amount": metrics["expected_recipient_amount"],
                    "probability_by_deadline": metrics["probability_by_deadline"],
                }
            )
    return {
        "report_version": REPORT_VERSION,
        "scenario_id": scenario.scenario_id,
        "fictional": True,
        "send_currency": scenario.transaction.send_currency,
        "receive_currency": scenario.transaction.receive_currency,
        "reference_volume_per_period": decimal_text(scenario.transaction.volume_per_period),
        "workloads": [
            {
                "workload_id": workload.workload_id,
                "label": workload.label,
                "transactions_per_period": decimal_text(workload.transactions_per_period),
            }
            for workload in workloads
        ],
        "rows": rows,
    }


def break_even_workloads(
    scenario: Scenario, left_route_id: str, right_route_id: str, identifiers: list[str] | tuple[str, ...] | None = None
) -> dict[str, object]:
    """Report where two routes' per-transaction sender costs cross, if at all.

    The scan is bounded to the declared workloads. Corridor Lab does not
    interpolate between them: a crossing is reported only between two adjacent
    declared workloads whose ordering actually reverses.
    """
    workloads = select_workloads(scenario, identifiers)
    if len(workloads) < 2:
        raise InputError("break-even workload exploration requires at least two declared workloads")
    ordered = sorted(workloads, key=lambda item: item.transactions_per_period)
    routes = {route.route_id: route for route in scenario.routes}
    for identifier in (left_route_id, right_route_id):
        if identifier not in routes:
            raise InputError(f"unknown route id: {identifier}")
    if left_route_id == right_route_id:
        raise InputError("break-even workload exploration requires two different routes")
    points: list[dict[str, str]] = []
    crossings: list[dict[str, str]] = []
    previous: tuple[Workload, Decimal] | None = None
    for workload in ordered:
        left = evaluate_route_at_volume(routes[left_route_id], scenario.transaction, workload.transactions_per_period)
        right = evaluate_route_at_volume(routes[right_route_id], scenario.transaction, workload.transactions_per_period)
        with local_decimal_context():
            difference = left.expected_sender_cost - right.expected_sender_cost
        precision = scenario.transaction.send_precision
        rounding = scenario.transaction.rounding
        points.append(
            {
                "workload_id": workload.workload_id,
                "transactions_per_period": decimal_text(workload.transactions_per_period),
                "left_expected_sender_cost": money_text(left.expected_sender_cost, precision, rounding),
                "right_expected_sender_cost": money_text(right.expected_sender_cost, precision, rounding),
                "difference_send": money_text(difference, precision, rounding),
            }
        )
        if previous is not None and previous[1] != 0 and (previous[1] > 0) != (difference > 0):
            crossings.append(
                {
                    "status": "crossing_between_declared_workloads",
                    "lower_workload_id": previous[0].workload_id,
                    "upper_workload_id": workload.workload_id,
                }
            )
        previous = (workload, difference)
    if crossings:
        status: dict[str, str] = crossings[0]
    else:
        status = {
            "status": "no_crossing_between_declared_workloads",
            "note": "the ordering of these two routes does not reverse across the declared workloads",
        }
    return {
        "report_version": "corridor-lab.break-even-workload/v1",
        "scenario_id": scenario.scenario_id,
        "fictional": True,
        "send_currency": scenario.transaction.send_currency,
        "left_route_id": left_route_id,
        "right_route_id": right_route_id,
        "points": points,
        **status,
    }
