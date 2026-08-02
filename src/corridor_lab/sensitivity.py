"""One-declared-parameter sensitivity analysis."""

from __future__ import annotations

from decimal import Decimal

from .canonical import InputError, decimal_text
from .model import evaluate_route
from .scenario import Scenario


def run_sensitivity(scenario: Scenario, parameter: str, values: list[Decimal]) -> dict[str, object]:
    if not values:
        raise InputError("sensitivity requires at least one value")
    if not scenario.routes:
        raise InputError("sensitivity requires routes embedded in the scenario")
    rows: list[dict[str, object]] = []
    for route in sorted(scenario.routes, key=lambda item: item.route_id):
        for value in values:
            changed = route.changed_parameter(parameter, value)
            evaluation = evaluate_route(changed, scenario.transaction)
            rows.append(
                {
                    "route_id": route.route_id,
                    "parameter": parameter,
                    "value": decimal_text(value),
                    "expected_recipient_amount": evaluation.as_dict()["expected_recipient_amount"],
                    "expected_sender_cost": evaluation.as_dict()["expected_sender_cost"],
                    "probability_by_deadline": evaluation.as_dict()["probability_by_deadline"],
                    "probability_by_deadline_definition": "successful completion by declared deadline",
                    "tail_completion_time_hours": evaluation.as_dict()["tail_completion_time_hours"],
                }
            )
    return {
        "report_version": "corridor-lab.sensitivity/v1",
        "scenario_id": scenario.scenario_id,
        "fictional": True,
        "parameter": parameter,
        "rows": rows,
    }
