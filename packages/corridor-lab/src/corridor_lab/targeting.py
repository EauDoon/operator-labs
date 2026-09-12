"""Bounded target-seeking and constraint review over declared candidate sets.

Everything here evaluates an explicit, bounded candidate set that the user
declared. Results identify the smallest tested feasible value — never a
mathematical optimum — and keep currencies, probabilities, and hours in
their own units with no composite score. Scenario sets are declared cases,
not forecasts.
"""

from __future__ import annotations

import re
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Any

from .canonical import (
    MAX_SENSITIVITY_ROWS,
    InputError,
    decimal_text,
    require_decimal,
)
from .comparison import evaluate_route
from .scenario import Scenario, _parse_transaction
from .transaction_sweep import TRANSACTION_PARAMETERS

CONSTRAINTS: dict[str, dict[str, str]] = {
    "expected_sender_cost_at_most": {"metric": "expected_sender_cost", "op": "at_most", "unit": "cost"},
    "expected_recipient_amount_at_least": {"metric": "expected_recipient_amount", "op": "at_least", "unit": "amount"},
    "probability_by_deadline_at_least": {"metric": "probability_by_deadline", "op": "at_least", "unit": "probability"},
    "tail_completion_time_hours_at_most": {"metric": "tail_completion_time_hours", "op": "at_most", "unit": "hours"},
}
MAX_CONSTRAINTS = 8
MAX_SCENARIOS = 64
_CONSTRAINT_PATTERN = re.compile(r"([a-z_]+)=(.+)")


def parse_constraint(text: str, send_currency: str | None = None, receive_currency: str | None = None) -> dict[str, Any]:
    """Parse one ``NAME=THRESHOLD`` constraint with strict kind and op matching."""
    match = _CONSTRAINT_PATTERN.fullmatch(text.strip())
    if match is None:
        raise InputError(f"constraint must be NAME=THRESHOLD from {', '.join(CONSTRAINTS)}")
    name, threshold_text = match.group(1), match.group(2)
    if name not in CONSTRAINTS:
        base = name.rsplit("_at_", 1)[0]
        if any(candidate.startswith(base + "_") for candidate in CONSTRAINTS):
            raise InputError(f"constraint {name} does not support the declared direction; use {', '.join(CONSTRAINTS)}")
        raise InputError(f"constraint must be NAME=THRESHOLD from {', '.join(CONSTRAINTS)}: {name}")
    declaration = CONSTRAINTS[name]
    if name.endswith("_at_most") and declaration["op"] != "at_most":
        raise InputError(f"constraint {name} does not support an upper bound here; use the listed forms")
    if name.endswith("_at_least") and declaration["op"] != "at_least":
        raise InputError(f"constraint {name} does not support a lower bound")
    threshold = require_decimal(threshold_text, f"constraint {name}")
    unit = declaration["unit"]
    if unit == "cost" and send_currency:
        unit = f"cost {send_currency}"
    elif unit == "amount" and receive_currency:
        unit = f"amount {receive_currency}"
    return {"name": name, "metric": declaration["metric"], "op": declaration["op"],
            "threshold": threshold, "unit": unit, "threshold_text": decimal_text(threshold)}


def _observed_value(evaluation: dict[str, Any], metric: str) -> Decimal:
    value = evaluation.get(metric)
    if value is None:
        raise InputError(f"evaluation did not report {metric}")
    try:
        return Decimal(str(value))
    except DecimalException as exc:
        raise InputError(f"evaluation reported an invalid value for {metric}") from exc


def _satisfied(constraint: dict[str, Any], observed: Decimal) -> bool:
    if constraint["op"] == "at_most":
        return observed <= constraint["threshold"]
    return observed >= constraint["threshold"]


def _scenario_units(scenario: Scenario, constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    send_currency = scenario.transaction.send_currency
    receive_currency = scenario.transaction.receive_currency
    parsed: list[dict[str, Any]] = []
    for raw in constraints:
        text = raw if isinstance(raw, str) else str(raw)
        parsed.append(parse_constraint(text, send_currency, receive_currency))
    if not parsed:
        raise InputError("declare at least one constraint")
    if len(parsed) > MAX_CONSTRAINTS:
        raise InputError(f"declare at most {MAX_CONSTRAINTS} constraints")
    return parsed


def target_search(scenario: Scenario, parameter: str, values: list[Decimal], constraints: list[str]) -> dict[str, Any]:
    """Evaluate every declared candidate against every declared constraint.

    One row per (candidate, route, constraint). The summary marks the smallest
    tested feasible candidate per route; nothing here searches beyond the
    declared values.
    """
    from .transaction_sweep import TRANSACTION_PARAMETERS

    if parameter not in TRANSACTION_PARAMETERS:
        raise InputError(f"target search parameter must be one of {', '.join(TRANSACTION_PARAMETERS)}")
    candidate_values = [require_decimal(value, "target search value") for value in values]
    if not candidate_values or len(candidate_values) > 64:
        raise InputError("target search requires 1 to 64 candidate values")
    if len(candidate_values) != len(set(candidate_values)):
        raise InputError("target search candidate values must be distinct")
    parsed_constraints = _scenario_units(scenario, constraints)
    routes = sorted(scenario.routes, key=lambda item: item.route_id)
    if not routes:
        raise InputError("target search requires embedded routes")
    if len(candidate_values) * len(routes) * len(parsed_constraints) > MAX_SENSITIVITY_ROWS:
        raise InputError("target search exceeds the row budget; reduce candidates, routes, or constraints")

    rows: list[dict[str, Any]] = []
    feasible_by_route: dict[str, list[Decimal]] = {route.route_id: [] for route in routes}
    invalid_by_route: dict[str, int] = {route.route_id: 0 for route in routes}
    for value in candidate_values:
        raw_transaction = _parse_transaction({
            "send_amount": decimal_text(scenario.transaction.send_amount),
            "send_currency": scenario.transaction.send_currency,
            "send_precision": scenario.transaction.send_precision,
            "receive_currency": scenario.transaction.receive_currency,
            "receive_precision": scenario.transaction.receive_precision,
            "rounding": scenario.transaction.rounding,
            "deadline_hours": decimal_text(scenario.transaction.deadline_hours),
            "volume_per_period": decimal_text(scenario.transaction.volume_per_period),
        } | {parameter: decimal_text(value)})
        for route in routes:
            try:
                evaluation = evaluate_route(route, raw_transaction).as_dict()
            except (InputError, ValueError, DecimalException) as exc:
                invalid_by_route[route.route_id] += 1
                for constraint in parsed_constraints:
                    rows.append({
                        "parameter": parameter, "value": decimal_text(value), "route_id": route.route_id,
                        "constraint": constraint["name"], "observed": None, "threshold": None,
                        "satisfied": None, "status": "invalid", "status_detail": str(exc),
                        "unit": constraint["unit"],
                    })
                continue
            all_pass = True
            for constraint in parsed_constraints:
                observed = _observed_value(evaluation, constraint["metric"])
                passed = _satisfied(constraint, observed)
                all_pass = all_pass and passed
                rows.append({
                    "parameter": parameter, "value": decimal_text(value), "route_id": route.route_id,
                    "constraint": constraint["name"], "observed": decimal_text(observed),
                    "threshold": constraint["threshold_text"], "satisfied": passed,
                    "status": "evaluated", "status_detail": None, "unit": constraint["unit"],
                })
            if all_pass:
                feasible_by_route[route.route_id].append(value)
    for route in routes:
        candidates = feasible_by_route[route.route_id]
        if candidates:
            smallest = min(candidates)
            rows.append({
                "parameter": parameter, "value": decimal_text(smallest), "route_id": route.route_id,
                "constraint": "smallest_tested_feasible_value", "observed": None, "threshold": None,
                "satisfied": True, "status": "summary", "status_detail": None,
                "unit": "declared candidate",
            })
        else:
            rows.append({
                "parameter": parameter, "value": None, "route_id": route.route_id,
                "constraint": "unreachable_within_tested_set", "observed": None, "threshold": None,
                "satisfied": False, "status": "summary",
                "status_detail": "no tested candidate satisfied every declared constraint"
                + (f"; {invalid_by_route[route.route_id]} candidate(s) could not be evaluated" if invalid_by_route[route.route_id] else ""),
                "unit": "declared candidate",
            })
    return {"report_version": "corridor-lab.analysis/v1", "analysis": "target-search",
            "scenario_id": scenario.scenario_id, "fictional": True,
            "columns": ["parameter", "value", "route_id", "constraint", "observed", "threshold", "satisfied", "status", "status_detail", "unit"],
            "rows": rows,
            "scope": "Exhaustive evaluation of the explicitly declared candidate set only. The smallest tested feasible value is not a mathematical optimum; invalid candidates are reported, not hidden."}


def robustness_review(scenarios: list[Scenario], scenario_labels: list[str], constraints: list[str]) -> dict[str, Any]:
    """Which declared routes satisfy the constraints across every supplied scenario.

    Scenarios are declared cases. For each route the first failing scenario is
    named; no forecast or completeness claim is implied.
    """
    if not scenarios:
        raise InputError("robustness review requires at least one scenario")
    if len(scenarios) > MAX_SCENARIOS:
        raise InputError(f"robustness review accepts at most {MAX_SCENARIOS} scenarios")
    first = scenarios[0]
    for scenario in scenarios[1:]:
        for field in ("send_currency", "receive_currency", "send_precision", "receive_precision", "rounding"):
            if getattr(scenario.transaction, field) != getattr(first.transaction, field):
                raise InputError("robustness review requires matching currencies, precisions, and rounding across scenarios")
    parsed_constraints = _scenario_units(first, constraints)
    rows: list[dict[str, Any]] = []
    first_failure: dict[str, str] = {}
    seen_routes: set[str] = set()
    for label, scenario in zip(scenario_labels, scenarios, strict=True):
        routes = sorted(scenario.routes, key=lambda item: item.route_id)
        for route in routes:
            seen_routes.add(route.route_id)
            evaluation = evaluate_route(route, scenario.transaction).as_dict()
            all_pass = True
            for constraint in parsed_constraints:
                observed = _observed_value(evaluation, constraint["metric"])
                passed = _satisfied(constraint, observed)
                all_pass = all_pass and passed
                rows.append({
                    "scenario": scenario.scenario_id,
                    "route_id": route.route_id,
                    "constraint": constraint["name"],
                    "observed": decimal_text(observed),
                    "threshold": constraint["threshold_text"],
                    "satisfied": passed,
                    "unit": constraint["unit"],
                })
            if not all_pass and route.route_id not in first_failure:
                first_failure[route.route_id] = scenario.scenario_id
    for route_id in sorted(seen_routes):
        rows.append({
            "scenario": first_failure.get(route_id, "none in the supplied order"),
            "route_id": route_id,
            "constraint": "first_failing_scenario",
            "observed": None, "threshold": None,
            "satisfied": route_id not in first_failure,
            "unit": "scenario order",
        })
    return {"report_version": "corridor-lab.analysis/v1", "analysis": "robustness-review",
            "scenario_id": first.scenario_id, "fictional": True,
            "columns": ["scenario", "route_id", "constraint", "observed", "threshold", "satisfied", "unit"],
            "rows": rows,
            "scope": "Constraints are evaluated against each declared scenario separately. Scenarios are declared cases, not forecasts; routes absent from a scenario are simply not evaluated there."}
