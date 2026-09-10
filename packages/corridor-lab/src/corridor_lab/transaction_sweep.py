"""Bounded what-if analysis of declared transaction assumptions."""

from decimal import Decimal
from itertools import product

from .analysis import _table
from .canonical import (
    MAX_SENSITIVITY_ROWS,
    MAX_SENSITIVITY_VALUES,
    InputError,
    decimal_text,
    require_decimal_values,
)
from .comparison import _declared_transaction, _guardrail_status
from .model import evaluate_route
from .scenario import Scenario, _parse_transaction

TRANSACTION_PARAMETERS = ("send_amount", "deadline_hours", "volume_per_period")


def run_transaction_sweep(scenario: Scenario, parameter: str, values: list[Decimal]) -> dict[str, object]:
    """Vary one transaction field, retaining all declared route assumptions."""
    if parameter not in TRANSACTION_PARAMETERS:
        raise InputError("unsupported transaction parameter")
    parsed = require_decimal_values(values, "transaction sweep")
    if not parsed or len(parsed) > MAX_SENSITIVITY_VALUES:
        raise InputError(f"transaction sweep requires 1 to {MAX_SENSITIVITY_VALUES} values")
    if not scenario.routes:
        raise InputError("transaction sweep requires embedded routes")
    if len(parsed) * len(scenario.routes) > MAX_SENSITIVITY_ROWS:
        raise InputError("transaction sweep exceeds the row budget")
    transactions = []
    for value in parsed:
        raw = _declared_transaction(scenario.transaction)
        raw[parameter] = decimal_text(value)
        transactions.append((value, _parse_transaction(raw)))
    rows = []
    for route in sorted(scenario.routes, key=lambda item: item.route_id):
        for value, transaction in transactions:
            metrics = evaluate_route(route, transaction).as_dict()
            rows.append({"route_id": route.route_id, "parameter": parameter, "value": decimal_text(value),
                         **{key: metrics[key] for key in ("expected_recipient_amount", "expected_sender_cost", "probability_by_deadline", "tail_completion_time_hours")},
                         "probability_by_deadline_definition": "successful completion by declared deadline"})
    return {"report_version": "corridor-lab.transaction-sweep/v1", "scenario_id": scenario.scenario_id,
            "fictional": True, "parameter": parameter, "transaction": _declared_transaction(scenario.transaction), "rows": rows}


def run_transaction_grid(scenario: Scenario, parameter_a: str, values_a: list[Decimal],
                         parameter_b: str, values_b: list[Decimal]) -> dict[str, object]:
    """Evaluate each explicitly requested transaction combination, without changing routes."""
    if parameter_a not in TRANSACTION_PARAMETERS or parameter_b not in TRANSACTION_PARAMETERS or parameter_a == parameter_b:
        raise InputError("transaction grid requires two distinct supported parameters")
    a, b = require_decimal_values(values_a, "axis a"), require_decimal_values(values_b, "axis b")
    if not a or not b or max(len(a), len(b)) > MAX_SENSITIVITY_VALUES or not scenario.routes:
        raise InputError("transaction grid requires embedded routes and 1 to 64 values per axis")
    if len(a) * len(b) * len(scenario.routes) > MAX_SENSITIVITY_ROWS:
        raise InputError("transaction grid exceeds the row budget")
    transactions = []
    for value_a, value_b in product(a, b):
        raw = _declared_transaction(scenario.transaction)
        raw.update({parameter_a: decimal_text(value_a), parameter_b: decimal_text(value_b)})
        transactions.append((value_a, value_b, _parse_transaction(raw)))
    rows = []
    for route in sorted(scenario.routes, key=lambda item: item.route_id):
        for value_a, value_b, transaction in transactions:
            evaluation = evaluate_route(route, transaction)
            metrics = evaluation.as_dict()
            passes = _guardrail_status(evaluation, scenario.objective)[0] if scenario.objective else None
            rows.append({"route_id": route.route_id, "parameter_a": parameter_a, "value_a": decimal_text(value_a),
                "parameter_b": parameter_b, "value_b": decimal_text(value_b), "guardrails_pass": passes,
                "send_currency": transaction.send_currency, "receive_currency": transaction.receive_currency,
                **{key: metrics[key] for key in ("expected_recipient_amount", "expected_sender_cost", "probability_by_deadline", "tail_completion_time_hours")}})
    return _table(scenario, "transaction-grid", ["route_id", "parameter_a", "value_a", "parameter_b", "value_b",
        "send_currency", "receive_currency", "expected_recipient_amount", "expected_sender_cost",
        "probability_by_deadline", "tail_completion_time_hours", "guardrails_pass"], rows,
        "Declared transaction combinations only. Routes and recovery amounts remain fixed. Null guardrail state means no objective was declared.")
