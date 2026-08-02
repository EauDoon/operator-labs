"""Bounded two-parameter stress-grid calculations."""

from __future__ import annotations

from decimal import Decimal

from .canonical import InputError, MAX_SENSITIVITY_ROWS, MAX_SENSITIVITY_VALUES, decimal_text
from .model import evaluate_route
from .scenario import Scenario


def run_stress_grid(
    scenario: Scenario,
    parameter_a: str,
    values_a: list[Decimal],
    parameter_b: str,
    values_b: list[Decimal],
) -> dict[str, object]:
    if not values_a or not values_b:
        raise InputError("stress grid requires values for both parameters")
    if parameter_a == parameter_b:
        raise InputError("stress grid parameters must be distinct")
    if not scenario.routes:
        raise InputError("stress grid requires routes embedded in the scenario")
    if len(values_a) > MAX_SENSITIVITY_VALUES or len(values_b) > MAX_SENSITIVITY_VALUES:
        raise InputError(f"stress grid values exceed the {MAX_SENSITIVITY_VALUES}-value budget")
    row_count = len(scenario.routes) * len(values_a) * len(values_b)
    if row_count > MAX_SENSITIVITY_ROWS:
        raise InputError(f"stress grid exceeds the {MAX_SENSITIVITY_ROWS}-row budget")
    rows: list[dict[str, object]] = []
    for route in sorted(scenario.routes, key=lambda item: item.route_id):
        for value_a in values_a:
            for value_b in values_b:
                changed = route.changed_parameter(parameter_a, value_a).changed_parameter(parameter_b, value_b)
                metrics = evaluate_route(changed, scenario.transaction).as_dict()
                rows.append(
                    {
                        "route_id": route.route_id,
                        "parameter_a": parameter_a,
                        "value_a": decimal_text(value_a),
                        "parameter_b": parameter_b,
                        "value_b": decimal_text(value_b),
                        "expected_recipient_amount": metrics["expected_recipient_amount"],
                        "expected_sender_cost": metrics["expected_sender_cost"],
                        "probability_by_deadline": metrics["probability_by_deadline"],
                    }
                )
    return {
        "report_version": "corridor-lab.stress-grid/v1",
        "scenario_id": scenario.scenario_id,
        "fictional": True,
        "parameter_a": parameter_a,
        "parameter_b": parameter_b,
        "rows": rows,
    }
