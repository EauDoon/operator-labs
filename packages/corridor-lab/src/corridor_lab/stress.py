"""Bounded two-parameter stress-grid calculations."""

from __future__ import annotations

from decimal import Decimal

from .canonical import (
    MAX_SENSITIVITY_ROWS,
    MAX_SENSITIVITY_VALUES,
    InputError,
    decimal_text,
    require_decimal_values,
)
from .model import evaluate_route
from .comparison import _guardrail_status, _declared_objective
from .scenario import Scenario


def run_stress_grid(
    scenario: Scenario,
    parameter_a: str,
    values_a: list[Decimal],
    parameter_b: str,
    values_b: list[Decimal],
) -> dict[str, object]:
    parsed_a = require_decimal_values(values_a, "stress grid parameter-a")
    parsed_b = require_decimal_values(values_b, "stress grid parameter-b")
    if not parsed_a or not parsed_b:
        raise InputError("stress grid requires values for both parameters")
    if parameter_a == parameter_b:
        raise InputError("stress grid parameters must be distinct")
    if not scenario.routes:
        raise InputError("stress grid requires routes embedded in the scenario")
    if len(parsed_a) > MAX_SENSITIVITY_VALUES or len(parsed_b) > MAX_SENSITIVITY_VALUES:
        raise InputError(f"stress grid values exceed the {MAX_SENSITIVITY_VALUES}-value budget")
    row_count = len(scenario.routes) * len(parsed_a) * len(parsed_b)
    if row_count > MAX_SENSITIVITY_ROWS:
        raise InputError(f"stress grid exceeds the {MAX_SENSITIVITY_ROWS}-row budget")
    rows: list[dict[str, object]] = []
    for route in sorted(scenario.routes, key=lambda item: item.route_id):
        for value_a in parsed_a:
            for value_b in parsed_b:
                changed = route.changed_parameter(parameter_a, value_a).changed_parameter(parameter_b, value_b)
                evaluation = evaluate_route(changed, scenario.transaction)
                metrics = evaluation.as_dict()
                guardrails = {}
                if scenario.objective is not None:
                    passes, failures = _guardrail_status(evaluation, scenario.objective)
                    guardrails = {"guardrails_pass": passes, "failed_guardrails": failures}
                rows.append(
                    {
                        **guardrails,
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
    report = {
        "report_version": "corridor-lab.stress-grid/v1",
        "scenario_id": scenario.scenario_id,
        "fictional": True,
        "parameter_a": parameter_a,
        "parameter_b": parameter_b,
        "rows": rows,
    }

    if scenario.objective is not None:
        report["objective"] = _declared_objective(scenario.objective)
        report["guardrail_summary"] = [
            {"route_id": route.route_id,
             "passing_cells": sum(row["guardrails_pass"] for row in rows if row["route_id"] == route.route_id),
             "total_cells": len(parsed_a) * len(parsed_b)}
            for route in sorted(scenario.routes, key=lambda item: item.route_id)
        ]
    return report
