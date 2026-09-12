"""Named scenario variants derived from an explicit baseline.

A derived variant copies its base scenario and applies a controlled, strictly
validated set of changes while keeping every other declared field intact.
The unchanged fields are part of the variant by construction, and the
assumption diff lists exactly what changed before any result is shown.
Variants are declared cases, never a statistically representative
distribution, and nothing here invents a composite score.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Any

from .canonical import (
    InputError,
    decimal_text,
    require_decimal,
    require_identifier,
)
from .scenario import parse_scenario

TRANSACTION_CHANGE_FIELDS = ("send_amount", "deadline_hours", "volume_per_period")
ROUTE_CHANGE_FIELDS = (
    "fx_rate",
    "fixed_fee_send",
    "percent_fee_bps",
    "fx_spread_bps",
    "liquidity.prefunding_amount_send",
    "liquidity.annual_cost_of_capital_bps",
    "liquidity.holding_days",
)
MAX_CHANGES = 32


@dataclass(frozen=True)
class DerivedVariant:
    """A named, controlled change set applied to the project scenario."""

    name: str
    transaction: dict[str, str]
    routes: dict[str, dict[str, str]]


def _split_route_field(field: str) -> tuple[str, str]:
    if field in ROUTE_CHANGE_FIELDS and "." in field:
        group, name = field.split(".", 1)
        return group, name
    return "", field


def _validate_change_value(field: str, value: str, path: str) -> str:
    text = str(value).strip()
    if not text:
        raise InputError(f"{path} must be a non-empty decimal string")
    require_decimal(text, f"{path}")
    return text


def validate_changes(changes: Any) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Validate one variant's change set with exact decimal preservation."""
    if not isinstance(changes, dict):
        raise InputError("variant changes must be an object")
    unknown = changes.keys() - {"transaction", "routes"}
    if unknown:
        raise InputError(f"variant changes have unsupported fields: {', '.join(sorted(unknown))}")
    transaction: dict[str, str] = {}
    if "transaction" in changes:
        raw = changes["transaction"]
        if not isinstance(raw, dict):
            raise InputError("variant changes.transaction must be an object")
        for field, value in raw.items():
            if field not in TRANSACTION_CHANGE_FIELDS:
                raise InputError(
                    f"variant transaction change must be one of {', '.join(TRANSACTION_CHANGE_FIELDS)}: {field}"
                )
            transaction[field] = _validate_change_value(field, value, f"changes.transaction.{field}")
    routes: dict[str, dict[str, str]] = {}
    if "routes" in changes:
        raw = changes["routes"]
        if not isinstance(raw, dict):
            raise InputError("variant changes.routes must be an object keyed by route_id")
        for route_id, fields in raw.items():
            require_identifier(route_id, f"changes.routes route_id")
            if not isinstance(fields, dict) or not fields:
                raise InputError(f"changes.routes[{route_id}] must be a non-empty object")
            route_fields: dict[str, str] = {}
            for field, value in fields.items():
                if field not in ROUTE_CHANGE_FIELDS:
                    raise InputError(
                        f"variant route change must be one of {', '.join(ROUTE_CHANGE_FIELDS)}: {field}"
                    )
                route_fields[field] = _validate_change_value(field, value, f"changes.routes[{route_id}].{field}")
            routes[route_id] = route_fields
    total = len(transaction) + sum(len(fields) for fields in routes.values())
    if total == 0 or total > MAX_CHANGES:
        raise InputError(f"a variant declares between 1 and {MAX_CHANGES} changes")
    return transaction, routes
def parse_derived_variant(name: str, value: Any) -> DerivedVariant:
    if not isinstance(value, dict):
        raise InputError("variant must be an object")
    unknown = value.keys() - {"base", "changes"}
    missing = {"base", "changes"} - value.keys()
    if unknown or missing:
        raise InputError(f"derived variant has unsupported or missing fields: {', '.join(sorted(unknown | missing))}")
    if value["base"] != "scenario":
        raise InputError("variant base must be the project scenario; chained variants are not supported")
    transaction, routes = validate_changes(value["changes"])
    return DerivedVariant(name=require_identifier(name, "variant name"), transaction=transaction, routes=routes)


def apply_variant(variant: DerivedVariant, base_raw: dict[str, Any]) -> dict[str, Any]:
    """Return the materialized scenario with only the declared changes applied."""
    raw: dict[str, Any] = {
        "transaction": dict(base_raw.get("transaction", {})),
        **{key: value for key, value in base_raw.items() if key != "transaction"},
    }
    if not isinstance(raw["transaction"], dict):
        raise InputError("variant base scenario transaction must be an object")
    transaction = dict(raw["transaction"])
    for field, value in variant.transaction.items():
        if field not in transaction:
            raise InputError(f"variant base scenario has no transaction field {field}")
        transaction[field] = value
    raw["transaction"] = transaction
    routes_raw = raw.get("routes")
    if variant.routes:
        if not isinstance(routes_raw, list):
            raise InputError("variant base scenario has no routes to change")
        by_id: dict[str, dict[str, Any]] = {}
        for route in routes_raw:
            if isinstance(route, dict) and isinstance(route.get("route_id"), str):
                by_id[route["route_id"]] = route
        for route_id, fields in variant.routes.items():
            if route_id not in by_id:
                raise InputError(f"variant base scenario has no route {route_id}")
            for field, value in fields.items():
                group, name = _split_route_field(field)
                if group:
                    section = by_id[route_id].get(group)
                    if not isinstance(section, dict) or name not in section:
                        raise InputError(f"variant base route {route_id} has no {field}")
                    section[name] = value
                else:
                    if field not in by_id[route_id]:
                        raise InputError(f"variant base route {route_id} has no {field}")
                    by_id[route_id][field] = value
    return raw


def parse_variant_changes_argument(text: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Parse ``transaction.FIELD=VALUE;route.ROUTE_ID.FIELD=VALUE`` arguments."""
    if not text.strip():
        raise InputError("--changes must declare at least one change")
    transaction: dict[str, str] = {}
    routes: dict[str, dict[str, str]] = {}
    for chunk in text.split(";"):
        key, separator, value = chunk.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise InputError(f"variant change must be KEY=VALUE: {chunk}")
        key = key.strip()
        if key.startswith("transaction."):
            field = key.removeprefix("transaction.")
            if field in transaction:
                raise InputError(f"variant change repeated: {key}")
            transaction[field] = value.strip()
        elif key.startswith("route."):
            remainder = key.removeprefix("route.")
            route_id, dot, field = remainder.partition(".")
            if not dot or not route_id.strip() or not field.strip():
                raise InputError(f"route change must be route.ROUTE_ID.FIELD=VALUE: {chunk}")
            fields = routes.setdefault(route_id.strip(), {})
            if field.strip() in fields:
                raise InputError(f"variant change repeated: {key}")
            fields[field.strip()] = value.strip()
        else:
            raise InputError(f"variant change must start with transaction. or route.: {key}")
    return validate_changes({"transaction": transaction, "routes": routes})


def variant_diff_report(variant: DerivedVariant, base_raw: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    """The assumption diff as a standard analysis table, shown before results."""
    rows = variant_changes(variant, base_raw)
    return {"report_version": "corridor-lab.analysis/v1", "analysis": "variant-assumption-diff",
            "scenario_id": scenario_id, "fictional": True,
            "columns": ["section", "field", "base", "variant"], "rows": rows,
            "scope": "Exactly these declared assumptions differ from the base scenario; every other declared field is unchanged."}


METRIC_LABELS = (
    ("expected_recipient_amount", "conditional recipient amount", "amount"),
    ("expected_sender_cost", "expected sender cost", "cost"),
    ("probability_by_deadline", "successful by deadline probability", "probability"),
    ("tail_completion_time_hours", "tail completion time", "hours"),
)


def _variant_rows(name: str, scenario_obj, rows: list) -> None:
    from .comparison import evaluate_scenario

    evaluation = evaluate_scenario(scenario_obj)
    transaction = evaluation["transaction"]
    send_currency = transaction["send_currency"]
    receive_currency = transaction["receive_currency"]
    ranking = evaluation.get("ranking") if isinstance(evaluation.get("ranking"), dict) else {}
    rejected = {entry["route_id"] for entry in ranking.get("guardrail_rejections", [])}
    objective_declared = ranking.get("objective_metric") is not None
    for route in evaluation["routes"]:
        route_id = route["route_id"]
        for metric, label, unit in METRIC_LABELS:
            currency = ""
            if unit == "amount":
                currency = f" {receive_currency}"
            elif unit == "cost":
                currency = f" {send_currency}"
            rows.append({
                "variant": name,
                "route_id": route_id,
                "metric": metric,
                "metric_definition": label,
                "value": route[metric],
                "unit": f"{unit}{currency}",
            })
        if objective_declared:
            rows.append({
                "variant": name,
                "route_id": route_id,
                "metric": "objective_guardrail_pass",
                "metric_definition": "meets every declared guardrail",
                "value": "false" if route_id in rejected else "true",
                "unit": "boolean",
            })


def variant_comparison(
    base_raw: dict[str, Any],
    variants: dict[str, DerivedVariant],
    project_id: str,
) -> dict[str, Any]:
    """Route performance across the declared variant set, with currencies and units explicit.

    Variants are declared cases, not forecasts, and no composite score is
    computed across metrics.
    """
    from .scenario import parse_scenario

    if len(variants) > MAX_CHANGES:
        raise InputError("variant comparison exceeds the declared variant budget")
    rows: list[dict[str, Any]] = []
    for name in ("scenario", *sorted(variants)):
        variant = variants.get(name)
        if variant is None:
            raw = base_raw
        else:
            raw = apply_variant(variant, base_raw)
        scenario = parse_scenario(raw)
        _variant_rows(name, scenario, rows)
    return {"report_version": "corridor-lab.analysis/v1", "analysis": "variant-comparison",
            "scenario_id": str(base_raw.get("scenario_id", "fictional-scenario")), "fictional": True,
            "project_id": project_id,
            "columns": ["variant", "route_id", "metric", "metric_definition", "value", "unit"],
            "rows": rows,
            "scope": "One declared case per row set; sampled scenarios are not a statistically representative distribution and no composite score is computed."}


def variant_changes(variant: DerivedVariant, base_raw: dict[str, Any]) -> list[dict[str, str]]:
    """The assumption diff: exactly what changes, with declared base values."""
    rows: list[dict[str, str]] = []
    transaction = base_raw.get("transaction", {})
    for field, value in variant.transaction.items():
        base_value = transaction.get(field)
        rows.append({"section": "transaction", "field": field, "base": decimal_text(Decimal(str(base_value))) if base_value is not None else "", "variant": value})
    routes_raw = base_raw.get("routes", [])
    by_id: dict[str, dict[str, Any]] = {}
    for route in routes_raw or []:
        if isinstance(route, dict) and isinstance(route.get("route_id"), str):
            by_id[route["route_id"]] = route
    for route_id, fields in variant.routes.items():
        route = by_id.get(route_id, {})
        for field, value in fields.items():
            group, name = _split_route_field(field)
            source = route.get(group, {}) if group else route
            base_value = source.get(name) if isinstance(source, dict) else None
            rows.append({
                "section": f"route {route_id}",
                "field": field,
                "base": decimal_text(Decimal(str(base_value))) if base_value is not None else "",
                "variant": value,
            })
    return rows
