"""Bounded what-if analysis of declared transaction assumptions."""

from dataclasses import replace
from decimal import Decimal

from .canonical import InputError, MAX_SENSITIVITY_ROWS, MAX_SENSITIVITY_VALUES, decimal_text, require_decimal_values
from .comparison import _declared_transaction
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
