"""Versioned scenario contract and safe input loading."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .canonical import (
    InputError,
    load_json,
    parse_json_text,
    require_bool,
    require_decimal,
    require_integer,
    require_keys,
    require_object,
    require_string,
)
from .route import Route, parse_route


SCENARIO_CONTRACT_VERSION = "corridor-lab.scenario/v1"
ROUNDING_NAMES = {"ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_DOWN", "ROUND_UP"}
ScenarioError = InputError


@dataclass(frozen=True)
class Transaction:
    send_amount: Decimal
    send_currency: str
    send_precision: int
    receive_currency: str
    receive_precision: int
    rounding: str
    deadline_hours: Decimal
    volume_per_period: Decimal


@dataclass(frozen=True)
class Objective:
    metric: str
    minimum_probability_by_deadline: Decimal | None
    maximum_tail_hours: Decimal | None


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    fictional: bool
    transaction: Transaction
    routes: tuple[Route, ...]
    objective: Objective | None


def _parse_transaction(value: Any) -> Transaction:
    path = "scenario.transaction"
    item = require_object(value, path)
    require_keys(
        item,
        {
            "send_amount",
            "send_currency",
            "send_precision",
            "receive_currency",
            "receive_precision",
            "rounding",
            "deadline_hours",
            "volume_per_period",
        },
        set(),
        path,
    )
    rounding = require_string(item["rounding"], f"{path}.rounding")
    if rounding not in ROUNDING_NAMES:
        raise InputError(f"{path}.rounding must be one of {', '.join(sorted(ROUNDING_NAMES))}")
    return Transaction(
        send_amount=require_decimal(item["send_amount"], f"{path}.send_amount", positive=True),
        send_currency=require_string(item["send_currency"], f"{path}.send_currency"),
        send_precision=require_integer(item["send_precision"], f"{path}.send_precision", minimum=0, maximum=6),
        receive_currency=require_string(item["receive_currency"], f"{path}.receive_currency"),
        receive_precision=require_integer(item["receive_precision"], f"{path}.receive_precision", minimum=0, maximum=6),
        rounding=rounding,
        deadline_hours=require_decimal(item["deadline_hours"], f"{path}.deadline_hours", minimum=Decimal("0")),
        volume_per_period=require_decimal(item["volume_per_period"], f"{path}.volume_per_period", positive=True),
    )


def _parse_objective(value: Any) -> Objective:
    path = "scenario.objective"
    item = require_object(value, path)
    require_keys(item, {"metric", "guardrails"}, set(), path)
    metric = require_string(item["metric"], f"{path}.metric")
    if metric not in {"maximize_expected_recipient_amount", "minimize_expected_sender_cost"}:
        raise InputError(f"{path}.metric is not supported")
    guardrails = require_object(item["guardrails"], f"{path}.guardrails")
    require_keys(
        guardrails,
        set(),
        {"minimum_probability_by_deadline", "maximum_tail_hours"},
        f"{path}.guardrails",
    )
    if not guardrails:
        raise InputError(f"{path}.guardrails must contain at least one constraint")
    minimum = None
    maximum = None
    if "minimum_probability_by_deadline" in guardrails:
        minimum = require_decimal(
            guardrails["minimum_probability_by_deadline"],
            f"{path}.guardrails.minimum_probability_by_deadline",
            minimum=Decimal("0"),
            maximum=Decimal("1"),
        )
    if "maximum_tail_hours" in guardrails:
        maximum = require_decimal(
            guardrails["maximum_tail_hours"],
            f"{path}.guardrails.maximum_tail_hours",
            minimum=Decimal("0"),
        )
    return Objective(metric, minimum, maximum)


def parse_scenario(value: Any) -> Scenario:
    item = require_object(value, "scenario")
    require_keys(
        item,
        {"contract_version", "scenario_id", "description", "fictional", "transaction"},
        {"routes", "objective"},
        "scenario",
    )
    if require_string(item["contract_version"], "scenario.contract_version") != SCENARIO_CONTRACT_VERSION:
        raise InputError(f"scenario.contract_version must equal {SCENARIO_CONTRACT_VERSION}")
    fictional = require_bool(item["fictional"], "scenario.fictional")
    if not fictional:
        raise InputError("scenario.fictional must be true; Corridor Lab accepts synthetic scenarios only")
    routes_raw = item.get("routes", [])
    if not isinstance(routes_raw, list):
        raise InputError("scenario.routes must be an array")
    routes = tuple(parse_route(route, f"scenario.routes[{index}]") for index, route in enumerate(routes_raw))
    identifiers = [route.route_id for route in routes]
    if len(identifiers) != len(set(identifiers)):
        raise InputError("scenario.routes has duplicate route_id values")
    return Scenario(
        scenario_id=require_string(item["scenario_id"], "scenario.scenario_id"),
        description=require_string(item["description"], "scenario.description"),
        fictional=fictional,
        transaction=_parse_transaction(item["transaction"]),
        routes=routes,
        objective=_parse_objective(item["objective"]) if "objective" in item else None,
    )


def load_scenario(path: str | Path) -> Scenario:
    return parse_scenario(load_json(path))


def parse_scenario_text(text: str) -> Scenario:
    """Validate an in-memory fictional scenario with the file-input rules."""
    return parse_scenario(parse_json_text(text))
