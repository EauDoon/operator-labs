"""Explicit scenario-revision comparison.

Two scenario files are compared only when the user selects both. Corridor Lab
never autosaves a revision and never compares against a hidden previous state.

What a diff reports
-------------------
1. **Changed assumptions.** The declared documents are flattened to
   ``path -> value`` maps and compared, so every declared field is covered
   without a hand-maintained list. Array entries are addressed by their
   declared identifier (`route_id`, `outcome_id`, `leg_id`, `workload_id`,
   period index) so a path stays meaningful when entries are reordered.

2. **Changed modeled outputs.** Both scenarios are evaluated and every reported
   metric is compared per route.

3. **Attribution, honestly.** When exactly one declared assumption changed, the
   diff says so: every output movement is attributable to that single change
   under the declared model. When several changed, the diff does **not** claim
   per-factor attribution. It reports the number of changed assumptions and
   states that the outputs moved under their combination. Corridor Lab does not
   apportion an output delta across simultaneous input changes, because the
   declared model does not licence that arithmetic.

Value normalisation matters: `1`, `"1"`, and `"1.0"` are the same declared
number, so scalars are normalised through `Decimal` before comparison. A change
of contract version, currency label, or rounding mode is an assumption change
like any other.
"""

from __future__ import annotations

from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Any

from .canonical import InputError, decimal_text, load_json
from .comparison import compare_routes
from .scenario import Scenario, parse_scenario

REPORT_VERSION = "corridor-lab.scenario-diff/v1"

_IDENTIFIER_KEYS = ("route_id", "outcome_id", "leg_id", "workload_id", "period_index", "label", "key")
_SKIP_KEYS = ("description", "scenario_id")
_METRICS = (
    "recipient_amount",
    "expected_recipient_amount",
    "explicit_fee_send",
    "explicit_fee_transaction_send",
    "explicit_fee_period_amortized_send",
    "liquidity_carry_cost_send",
    "expected_failure_recovery_cost_send",
    "expected_sender_cost",
    "probability_by_deadline",
    "expected_completion_time_hours",
    "median_completion_time_hours",
    "tail_completion_time_hours",
)


def flatten_declared(document: dict[str, Any]) -> dict[str, str]:
    """Flatten a declared scenario document into ``path -> normalised value``."""
    if not isinstance(document, dict):
        raise InputError("scenario document must be a JSON object")
    result: dict[str, str] = {}
    _flatten(document, (), result)
    return result


def _flatten(value: Any, path: tuple[str, ...], result: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            if not path and key in _SKIP_KEYS:
                continue
            _flatten(value[key], path + (str(key),), result)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _flatten(item, path + (_entry_name(item, index),), result)
        return
    result[".".join(path) if path else ""] = _normalise(value)


def _entry_name(item: Any, index: int) -> str:
    """Address an array entry by its declared identifier where one exists."""
    if isinstance(item, dict):
        for key in _IDENTIFIER_KEYS:
            if key in item and isinstance(item[key], (str, int)) and not isinstance(item[key], bool):
                return f"{key}={item[key]}"
    return str(index)


def _normalise(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float, Decimal)):
        try:
            return decimal_text(Decimal(str(value)))
        except (DecimalException, ValueError):
            return str(value)
    text = str(value)
    # Declared decimals are usually JSON strings, so "1", "1.0" and 1 must all
    # compare equal. A value that is not a number keeps its exact text.
    try:
        return decimal_text(Decimal(text))
    except (DecimalException, ValueError):
        return text


def diff_declarations(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, str]]:
    """Return the added, removed, and changed declared assumptions."""
    left = flatten_declared(before)
    right = flatten_declared(after)
    changes: list[dict[str, str]] = []
    for path in sorted(set(left) | set(right)):
        if path not in left:
            changes.append({"path": path, "change": "added", "before": "", "after": right[path]})
        elif path not in right:
            changes.append({"path": path, "change": "removed", "before": left[path], "after": ""})
        elif left[path] != right[path]:
            changes.append({"path": path, "change": "changed", "before": left[path], "after": right[path]})
    return changes


def _route_metrics(scenario: Scenario) -> dict[str, dict[str, str]]:
    report = compare_routes(scenario.transaction, scenario.routes, scenario.objective, scenario.scenario_id)
    return {route["route_id"]: route for route in report["routes"]}


def _output_changes(before: Scenario, after: Scenario) -> list[dict[str, str]]:
    left = _route_metrics(before)
    right = _route_metrics(after)
    rows: list[dict[str, str]] = []
    for route_id in sorted(set(left) | set(right)):
        if route_id not in left:
            rows.append(
                {
                    "route_id": route_id,
                    "metric": "route",
                    "change": "added",
                    "before": "",
                    "after": "present",
                    "delta": "",
                }
            )
            continue
        if route_id not in right:
            rows.append(
                {
                    "route_id": route_id,
                    "metric": "route",
                    "change": "removed",
                    "before": "present",
                    "after": "",
                    "delta": "",
                }
            )
            continue
        for metric in _METRICS:
            old = left[route_id].get(metric)
            new = right[route_id].get(metric)
            if old is None or new is None:
                continue
            if old == new:
                continue
            rows.append(
                {
                    "route_id": route_id,
                    "metric": metric,
                    "change": "changed",
                    "before": str(old),
                    "after": str(new),
                    "delta": _delta(old, new),
                }
            )
    return rows


def _delta(before: str, after: str) -> str:
    try:
        difference = Decimal(after) - Decimal(before)
    except (DecimalException, ValueError):
        return ""
    return decimal_text(difference)


def diff_scenarios(
    before: dict[str, Any], after: dict[str, Any], *, before_label: str = "before", after_label: str = "after"
) -> dict[str, Any]:
    """Compare two declared scenario documents and their modeled outputs."""
    before_scenario = parse_scenario(before)
    after_scenario = parse_scenario(after)
    assumption_changes = diff_declarations(before, after)
    output_changes = _output_changes(before_scenario, after_scenario)
    changed_count = len(assumption_changes)
    if changed_count == 0:
        attribution = {
            "status": "no_declared_change",
            "note": "the two documents declare identical assumptions, so no output movement is explained by them",
        }
    elif changed_count == 1:
        attribution = {
            "status": "single_declared_change",
            "changed_assumption": assumption_changes[0]["path"],
            "note": (
                "exactly one declared assumption changed, so every reported output movement is attributable "
                "to that single change under the declared model"
            ),
        }
    else:
        attribution = {
            "status": "multiple_declared_changes",
            "changed_assumption_count": changed_count,
            "note": (
                f"{changed_count} declared assumptions changed together. Corridor Lab does not apportion an "
                "output delta across simultaneous input changes, because the declared model does not licence "
                "that arithmetic. The outputs below moved under their combination."
            ),
        }
    return {
        "report_version": REPORT_VERSION,
        "fictional": True,
        "before": {
            "label": before_label,
            "scenario_id": before_scenario.scenario_id,
            "contract_version": before_scenario.contract_version,
        },
        "after": {
            "label": after_label,
            "scenario_id": after_scenario.scenario_id,
            "contract_version": after_scenario.contract_version,
        },
        "assumption_changes": assumption_changes,
        "output_changes": output_changes,
        "attribution": attribution,
    }


def diff_scenario_files(before_path: str | Path, after_path: str | Path) -> dict[str, Any]:
    """Load two user-selected scenario files and compare them."""
    before = load_json(before_path)
    after = load_json(after_path)
    return diff_scenarios(before, after, before_label=str(before_path), after_label=str(after_path))
