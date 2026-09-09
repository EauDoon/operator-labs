"""Transparent inspection of declared fictional scenarios, with no recommendations."""
from decimal import Decimal
from .canonical import MAX_SENSITIVITY_ROWS, InputError, decimal_text, local_decimal_context
from .model import evaluate_route
from .scenario import Scenario


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
