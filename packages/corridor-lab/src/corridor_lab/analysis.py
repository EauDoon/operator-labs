"""Transparent inspection of declared fictional scenarios, with no recommendations."""
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from itertools import combinations

from .canonical import (
    MAX_SENSITIVITY_ROWS,
    MAX_SENSITIVITY_VALUES,
    InputError,
    decimal_text,
    local_decimal_context,
    require_decimal,
    require_decimal_values,
)
from .comparison import _break_even, _declared_transaction
from .model import _quantile_time, evaluate_route
from .scenario import Scenario, _parse_transaction


def _evaluations(scenario: Scenario):
    if not scenario.routes:
        raise InputError("analysis requires embedded routes")
    return [evaluate_route(route, scenario.transaction)
            for route in sorted(scenario.routes, key=lambda item: item.route_id)]


def _table(scenario: Scenario, analysis: str, columns: list[str], rows: list[dict], note: str) -> dict:
    if len(rows) > MAX_SENSITIVITY_ROWS:
        raise InputError("analysis exceeds the row budget")
    return {"report_version": "corridor-lab.analysis/v1", "analysis": analysis,
            "scenario_id": scenario.scenario_id, "fictional": True,
            "columns": columns, "rows": rows, "scope": note}


def cost_ledger(scenario: Scenario) -> dict:
    """Reconcile unrounded sender costs without adding receive-currency FX spread."""
    rows = []
    with local_decimal_context():
        for evaluation in _evaluations(scenario):
            components = (("fixed_fee", evaluation.route.fixed_fee_send),
                          ("percentage_fee", evaluation.percentage_fee_send),
                          ("liquidity_carry", evaluation.liquidity_carry_cost_send),
                          ("failure_loss", evaluation.expected_failure_recovery_cost_send))
            for component, amount in components:
                rows.append({"route_id": evaluation.route.route_id, "component": component,
                    "send_currency": scenario.transaction.send_currency, "amount_send": decimal_text(amount),
                    "share_of_sender_cost": decimal_text(amount / evaluation.expected_sender_cost)
                    if evaluation.expected_sender_cost else None})
    return _table(scenario, "cost-ledger", ["route_id", "component", "send_currency", "amount_send",
        "share_of_sender_cost"], rows,
        "Unrounded per-transaction components sum to expected sender cost. FX spread is in receive currency and is excluded. Zero total cost has no share.")


def deadline_target(scenario: Scenario, probability: str) -> dict:
    """Find the first declared success time meeting an unconditional probability."""
    target = require_decimal(probability, "probability", minimum=Decimal(0), maximum=Decimal(1))
    rows = []
    with local_decimal_context():
        for evaluation in _evaluations(scenario):
            cumulative, hours = Decimal(0), Decimal(0) if target == 0 else None
            for outcome in sorted(evaluation.route.outcomes, key=lambda item: (item.delay_hours, item.outcome_id)):
                if outcome.completion == "success":
                    cumulative += outcome.probability
                    if hours is None and cumulative >= target:
                        hours = outcome.delay_hours
            rows.append({"route_id": evaluation.route.route_id, "target_probability": decimal_text(target),
                "maximum_success_probability": decimal_text(cumulative),
                "status": "reached" if hours is not None else "unreachable",
                "earliest_hours": decimal_text(hours) if hours is not None else None})
    return _table(scenario, "deadline-target", ["route_id", "target_probability",
        "maximum_success_probability", "status", "earliest_hours"], rows,
        "Earliest time meeting an explicitly requested unconditional delivery probability. Failure recovery never counts as delivery; no interpolation or forecast.")


def resolution_quantiles(scenario: Scenario, probabilities: list[Decimal]) -> dict:
    """Inspect caller-selected exact discrete quantiles of final-state time."""
    values = require_decimal_values(probabilities, "probabilities")
    if not values or len(values) > MAX_SENSITIVITY_VALUES or len(values) * len(scenario.routes) > MAX_SENSITIVITY_ROWS:
        raise InputError("resolution quantiles require 1 to 64 probabilities within the row budget")
    if any(value <= 0 or value > 1 for value in values):
        raise InputError("resolution probabilities must be greater than zero and at most one")
    rows = [{"route_id": evaluation.route.route_id, "probability": decimal_text(value),
             "resolution_hours": decimal_text(_quantile_time(evaluation.route, value))}
            for evaluation in _evaluations(scenario) for value in sorted(values)]
    return _table(scenario, "resolution-quantiles", ["route_id", "probability", "resolution_hours"], rows,
        "Earliest final-state time whose cumulative probability reaches the requested quantile. Includes failure recovery; not conditional delivery latency and never interpolated.")


def loss_profile(scenario: Scenario) -> dict:
    """Exact exceedance of unreturned principal at each declared loss breakpoint."""
    rows = []
    with local_decimal_context():
        for evaluation in _evaluations(scenario):
            losses = [(scenario.transaction.send_amount - outcome.recovery_amount_send, outcome.probability)
                      for outcome in evaluation.route.outcomes if outcome.completion == "failure"]
            thresholds = sorted({Decimal(0), *(loss for loss, _ in losses)})
            if len(rows) + len(thresholds) > MAX_SENSITIVITY_ROWS:
                raise InputError("loss profile exceeds the row budget")
            # ponytail: bounded outcome scan per breakpoint; suffix sums if outcome limits grow.
            for threshold in thresholds:
                probability = sum((weight for loss, weight in losses if loss > threshold), Decimal(0))
                excess = sum((weight * (loss - threshold) for loss, weight in losses if loss > threshold), Decimal(0))
                rows.append({"route_id": evaluation.route.route_id,
                    "send_currency": scenario.transaction.send_currency,
                    "loss_threshold_send": decimal_text(threshold),
                    "probability_above_threshold": decimal_text(probability),
                    "expected_excess_loss_send": decimal_text(excess)})
    return _table(scenario, "loss-profile", ["route_id", "send_currency", "loss_threshold_send",
        "probability_above_threshold", "expected_excess_loss_send"], rows,
        "Strictly greater than each unreturned-principal threshold; expected excess is unconditional. Fees, liquidity carry, and receive-currency FX spread are excluded. Declared synthetic outcomes only.")


def guardrail_headroom(scenario: Scenario) -> dict:
    """Positive or zero headroom passes only an explicitly declared guardrail."""
    objective = scenario.objective
    if objective is None:
        raise InputError("guardrail headroom requires an explicit objective and guardrails")
    rows = []
    with local_decimal_context():
        for evaluation in _evaluations(scenario):
            guards = [("minimum_probability_by_deadline", objective.minimum_probability_by_deadline,
                       evaluation.probability_by_deadline, "probability", True),
                      ("maximum_tail_hours", objective.maximum_tail_hours,
                       evaluation.tail_completion_time_hours, "hours", False)]
            for name, threshold, observed, unit, minimum in guards:
                if threshold is None:
                    continue
                margin = observed - threshold if minimum else threshold - observed
                rows.append({"route_id": evaluation.route.route_id, "guardrail": name,
                    "observed": decimal_text(observed), "threshold": decimal_text(threshold),
                    "headroom": decimal_text(margin), "unit": unit, "passes": margin >= 0})
    return _table(scenario, "guardrail-headroom",
                  ["route_id", "guardrail", "observed", "threshold", "headroom", "unit", "passes"], rows,
                  "Nonnegative headroom meets the declared guardrail; no route recommendation.")


def outcome_ledger(scenario: Scenario) -> dict:
    """Show each declared outcome's contribution to current model expectations."""
    if sum(len(route.outcomes) for route in scenario.routes) > MAX_SENSITIVITY_ROWS:
        raise InputError("outcome ledger exceeds the row budget")
    rows = []
    with local_decimal_context():
        for evaluation in _evaluations(scenario):
            for outcome in sorted(evaluation.route.outcomes, key=lambda item: item.outcome_id):
                success = outcome.completion == "success"
                probability = outcome.probability
                rows.append({"route_id": evaluation.route.route_id, "outcome_id": outcome.outcome_id,
                    "completion": outcome.completion, "probability": decimal_text(probability),
                    "resolution_hours": decimal_text(outcome.resolution_hours),
                    "send_currency": scenario.transaction.send_currency,
                    "receive_currency": scenario.transaction.receive_currency,
                    "expected_recipient_receive": decimal_text(probability * (evaluation.recipient_amount if success else Decimal(0))),
                    "expected_failure_loss_send": decimal_text(probability * (Decimal(0) if success else scenario.transaction.send_amount - outcome.recovery_amount_send)),
                    "expected_recovery_send": decimal_text(probability * (Decimal(0) if success else outcome.recovery_amount_send)),
                    "expected_resolution_hours": decimal_text(probability * outcome.resolution_hours)})
    return _table(scenario, "outcome-ledger", ["route_id", "outcome_id", "completion", "probability",
        "resolution_hours", "send_currency", "receive_currency", "expected_recipient_receive",
        "expected_failure_loss_send", "expected_recovery_send", "expected_resolution_hours"], rows,
        "Unrounded weighted contributions reconcile to model expectations. Fees and liquidity carry are separate sender costs.")


def deadline_profile(scenario: Scenario) -> dict:
    """Exact step probabilities at declared event times, including the deadline."""
    rows = []
    with local_decimal_context():
        for evaluation in _evaluations(scenario):
            outcomes = evaluation.route.outcomes
            times = sorted({Decimal(0), scenario.transaction.deadline_hours,
                            *(outcome.resolution_hours for outcome in outcomes)})
            if len(rows) + len(times) > MAX_SENSITIVITY_ROWS:
                raise InputError("deadline profile exceeds the row budget")
            for hours in times:
                successful = sum((outcome.probability for outcome in outcomes
                                  if outcome.completion == "success" and outcome.delay_hours <= hours), Decimal(0))
                resolved = sum((outcome.probability for outcome in outcomes
                                if outcome.resolution_hours <= hours), Decimal(0))
                rows.append({"route_id": evaluation.route.route_id, "hours": decimal_text(hours),
                    "successful_by_time": decimal_text(successful), "resolved_by_time": decimal_text(resolved),
                    "unresolved_probability": decimal_text(1 - resolved),
                    "declared_deadline": hours == scenario.transaction.deadline_hours})
    return _table(scenario, "deadline-profile", ["route_id", "hours", "successful_by_time",
        "resolved_by_time", "unresolved_probability", "declared_deadline"], rows,
        "Exact cumulative probabilities under declared outcomes. Failure recovery is resolution, not successful delivery.")


def break_even_check(scenario: Scenario) -> dict:
    """Re-evaluate whole transaction volumes next to each positive continuous crossover."""
    count = len(scenario.routes)
    if count < 2 or count * (count - 1) // 2 > MAX_SENSITIVITY_ROWS:
        raise InputError("break-even check requires 2 or more routes within the pair row budget")
    rows = []
    with local_decimal_context():
        for left, right in combinations(_evaluations(scenario), 2):
            row = _break_even(left, right)
            row["send_currency"] = scenario.transaction.send_currency
            if row["status"] == "computed":
                volume = Decimal(row["volume_transactions_per_period"])
                for name, rounding in (("lower", ROUND_FLOOR), ("upper", ROUND_CEILING)):
                    whole = max(Decimal(1), volume.to_integral_value(rounding=rounding))
                    raw = _declared_transaction(scenario.transaction)
                    raw["volume_per_period"] = decimal_text(whole)
                    transaction = _parse_transaction(raw)
                    delta = (evaluate_route(left.route, transaction).expected_sender_cost
                             - evaluate_route(right.route, transaction).expected_sender_cost)
                    row[f"{name}_volume"] = decimal_text(whole)
                    row[f"{name}_cost_delta_send"] = decimal_text(delta)
            rows.append(row)
    return _table(scenario, "break-even-check", ["left_route_id", "right_route_id", "status",
        "send_currency", "volume_transactions_per_period", "lower_volume", "lower_cost_delta_send",
        "upper_volume", "upper_cost_delta_send"], rows,
        "Costs are left minus right, unrounded sender currency. Floor/ceiling volumes are at least one and may coincide; no recommendation.")
