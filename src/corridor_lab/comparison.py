"""Route comparison, explicit guardrails, and volume break-even calculations."""

from __future__ import annotations

from decimal import Decimal, DecimalException
from itertools import combinations
from typing import Iterable

from .canonical import InputError, MAX_ROUTE_PAIRS, decimal_text, local_decimal_context
from .model import RouteEvaluation, evaluate_route
from .route import Route
from .scenario import Objective, Scenario, Transaction


def _break_even(left: RouteEvaluation, right: RouteEvaluation) -> dict[str, str]:
    """Solve fixed_left + liquid_left/V = fixed_right + liquid_right/V."""
    row = {"left_route_id": left.route.route_id, "right_route_id": right.route.route_id}
    try:
        with local_decimal_context():
            numerator = left.liquidity_carry_numerator_send - right.liquidity_carry_numerator_send
            denominator = right.fixed_expected_cost_send - left.fixed_expected_cost_send
            if denominator == 0:
                return {**row, "status": "no_finite_break_even"}
            volume = numerator / denominator
            if volume <= 0:
                return {**row, "status": "no_positive_break_even"}
            return {
                **row,
                "status": "computed",
                "volume_transactions_per_period": decimal_text(volume),
            }
    except DecimalException as exc:
        raise InputError("break-even calculation failed") from exc


def _declared_transaction(transaction: Transaction) -> dict[str, object]:
    return {
        "send_amount": decimal_text(transaction.send_amount),
        "send_currency": transaction.send_currency,
        "send_precision": transaction.send_precision,
        "receive_currency": transaction.receive_currency,
        "receive_precision": transaction.receive_precision,
        "rounding": transaction.rounding,
        "deadline_hours": decimal_text(transaction.deadline_hours),
        "volume_per_period": decimal_text(transaction.volume_per_period),
    }


def _declared_route(route: Route) -> dict[str, object]:
    return {
        "contract_version": "corridor-lab.route/v1",
        "route_id": route.route_id,
        "label": route.label,
        "fictional": route.fictional,
        "fx_rate": decimal_text(route.fx_rate),
        "fixed_fee_send": decimal_text(route.fixed_fee_send),
        "percent_fee_bps": decimal_text(route.percent_fee_bps),
        "fx_spread_bps": decimal_text(route.fx_spread_bps),
        "liquidity": {
            "prefunding_amount_send": decimal_text(route.liquidity.prefunding_amount_send),
            "annual_cost_of_capital_bps": decimal_text(route.liquidity.annual_cost_of_capital_bps),
            "holding_days": decimal_text(route.liquidity.holding_days),
        },
        "outcomes": [
            {
                "outcome_id": outcome.outcome_id,
                "probability": decimal_text(outcome.probability),
                "completion": outcome.completion,
                "delay_hours": decimal_text(outcome.delay_hours),
                "recovery_amount_send": decimal_text(outcome.recovery_amount_send),
                "recovery_delay_hours": decimal_text(outcome.recovery_delay_hours),
            }
            for outcome in route.outcomes
        ],
    }


def _declared_objective(objective: Objective) -> dict[str, object]:
    guardrails: dict[str, str] = {}
    if objective.minimum_probability_by_deadline is not None:
        guardrails["minimum_probability_by_deadline"] = decimal_text(objective.minimum_probability_by_deadline)
    if objective.maximum_tail_hours is not None:
        guardrails["maximum_tail_hours"] = decimal_text(objective.maximum_tail_hours)
    return {"metric": objective.metric, "guardrails": guardrails}


def _route_report(evaluation: RouteEvaluation, objective: Objective | None) -> dict[str, object]:
    report = evaluation.as_dict()
    declared_inputs: dict[str, object] = {
        "model_contract_version": "corridor-lab.model/v1",
        "transaction": _declared_transaction(evaluation.transaction),
        "route": _declared_route(evaluation.route),
    }
    if objective is not None:
        declared_inputs["objective"] = _declared_objective(objective)
    report["declared_inputs"] = declared_inputs
    return report


def _guardrail_status(evaluation: RouteEvaluation, objective: Objective) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if (
        objective.minimum_probability_by_deadline is not None
        and evaluation.probability_by_deadline < objective.minimum_probability_by_deadline
    ):
        failures.append("minimum_probability_by_deadline")
    if objective.maximum_tail_hours is not None and evaluation.tail_completion_time_hours > objective.maximum_tail_hours:
        failures.append("maximum_tail_hours")
    return not failures, failures


def _ranking(evaluations: list[RouteEvaluation], objective: Objective) -> dict[str, object]:
    eligible: list[RouteEvaluation] = []
    rejected: list[dict[str, object]] = []
    for evaluation in evaluations:
        passes, failures = _guardrail_status(evaluation, objective)
        if passes:
            eligible.append(evaluation)
        else:
            rejected.append({"route_id": evaluation.route.route_id, "failed_guardrails": failures})
    reverse = objective.metric == "maximize_expected_recipient_amount"
    if reverse:
        eligible.sort(key=lambda item: (-item.expected_recipient_amount, item.route.route_id))
    else:
        eligible.sort(key=lambda item: (item.expected_sender_cost, item.route.route_id))
    metric_value = (
        lambda item: item.expected_recipient_amount
        if objective.metric == "maximize_expected_recipient_amount"
        else item.expected_sender_cost
    )
    return {
        "objective_metric": objective.metric,
        "eligible_routes": [
            {"rank": index + 1, "route_id": item.route.route_id, "objective_value": decimal_text(metric_value(item))}
            for index, item in enumerate(eligible)
        ],
        "guardrail_rejections": rejected,
    }


def compare_routes(
    transaction: Transaction, routes: Iterable[Route], objective: Objective | None = None, scenario_id: str = "ad-hoc"
) -> dict[str, object]:
    ordered_routes = sorted(routes, key=lambda route: route.route_id)
    if not ordered_routes:
        raise InputError("at least one route is required for evaluation")
    identifiers = [route.route_id for route in ordered_routes]
    if len(identifiers) != len(set(identifiers)):
        raise InputError("route identifiers must be unique")
    if len(ordered_routes) * (len(ordered_routes) - 1) // 2 > MAX_ROUTE_PAIRS:
        raise InputError(f"route pair comparison exceeds the {MAX_ROUTE_PAIRS}-pair budget")
    evaluations = [evaluate_route(route, transaction) for route in ordered_routes]
    report: dict[str, object] = {
        "report_version": "corridor-lab.report/v1",
        "scenario_id": scenario_id,
        "fictional": True,
        "metric_definitions": {
            "probability_by_deadline": "successful completion by declared deadline",
        },
        "transaction": _declared_transaction(transaction),
        "routes": [_route_report(evaluation, objective) for evaluation in evaluations],
        "break_even_volumes": [
            _break_even(left, right) for left, right in combinations(evaluations, 2)
        ],
    }
    if objective is not None:
        report["objective"] = _declared_objective(objective)
        report["ranking"] = _ranking(evaluations, objective)
    return report


def pareto_frontier(evaluations: Iterable[RouteEvaluation]) -> list[dict[str, str]]:
    """Return non-dominated routes for explicit recipient and sender-cost metrics."""
    ordered = sorted(evaluations, key=lambda item: item.route.route_id)
    frontier: list[RouteEvaluation] = []
    for candidate in ordered:
        dominated = any(
            other.expected_recipient_amount >= candidate.expected_recipient_amount
            and other.expected_sender_cost <= candidate.expected_sender_cost
            and (
                other.expected_recipient_amount > candidate.expected_recipient_amount
                or other.expected_sender_cost < candidate.expected_sender_cost
            )
            for other in ordered
            if other is not candidate
        )
        if not dominated:
            frontier.append(candidate)
    return [
        {
            "route_id": item.route.route_id,
            "expected_recipient_amount": item.as_dict()["expected_recipient_amount"],
            "expected_sender_cost": item.as_dict()["expected_sender_cost"],
        }
        for item in frontier
    ]


def evaluate_scenario(scenario: Scenario) -> dict[str, object]:
    return compare_routes(scenario.transaction, scenario.routes, scenario.objective, scenario.scenario_id)
