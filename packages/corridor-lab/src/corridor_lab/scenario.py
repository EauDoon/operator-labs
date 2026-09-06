"""Versioned scenario contract and safe input loading."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; funding parses without importing scenario
    from .funding import FundingSchedule

from .canonical import (
    InputError,
    MAX_WORKLOADS,
    load_json,
    parse_json_text,
    require_bool,
    require_decimal,
    require_integer,
    require_identifier,
    require_keys,
    require_object,
    require_string,
    MAX_ROUTES,
)
from .route import ROUTE_CONTRACT_VERSION, ROUTE_CONTRACT_VERSION_V2, Route, parse_route


SCENARIO_CONTRACT_VERSION = "corridor-lab.scenario/v1"
SCENARIO_CONTRACT_VERSION_V2 = "corridor-lab.scenario/v2"
SUPPORTED_SCENARIO_CONTRACT_VERSIONS = (SCENARIO_CONTRACT_VERSION, SCENARIO_CONTRACT_VERSION_V2)
ROUNDING_NAMES = {"ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_DOWN", "ROUND_UP"}
ScenarioError = InputError


@dataclass(frozen=True)
class Workload:
    """A declared transaction-volume assumption for one period."""

    workload_id: str
    label: str
    transactions_per_period: Decimal


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
    contract_version: str = SCENARIO_CONTRACT_VERSION
    workloads: tuple[Workload, ...] = ()
    funding: "FundingSchedule | None" = None

    @property
    def workload_ids(self) -> tuple[str, ...]:
        return tuple(workload.workload_id for workload in self.workloads)


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
        send_currency=require_identifier(item["send_currency"], f"{path}.send_currency", maximum=16),
        send_precision=require_integer(item["send_precision"], f"{path}.send_precision", minimum=0, maximum=6),
        receive_currency=require_identifier(item["receive_currency"], f"{path}.receive_currency", maximum=16),
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
    minimum: Decimal | None = None
    maximum: Decimal | None = None
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
    """Dispatch on the declared scenario contract version.

    ``corridor-lab.scenario/v1`` keeps its original strict field set and accepts
    only v1 routes. The v2 contract adds declared workload assumptions and
    accepts routes of either supported route contract version.
    """
    item = require_object(value, "scenario")
    if "contract_version" not in item:
        raise InputError("scenario missing required field(s): contract_version")
    version = require_string(item["contract_version"], "scenario.contract_version")
    if version == SCENARIO_CONTRACT_VERSION:
        return _parse_scenario_v1(item)
    if version == SCENARIO_CONTRACT_VERSION_V2:
        return _parse_scenario_v2(item)
    raise InputError(
        f"scenario.contract_version must be one of {', '.join(SUPPORTED_SCENARIO_CONTRACT_VERSIONS)}"
    )


def _scenario_common(
    item: dict[str, Any],
    version: str,
    optional: set[str],
    allowed_route_versions: tuple[str, ...] | None,
) -> tuple[str, str, bool, Transaction, tuple[Route, ...], Objective | None]:
    require_keys(
        item,
        {"contract_version", "scenario_id", "description", "fictional", "transaction"},
        optional | {"routes", "objective"},
        "scenario",
    )
    fictional = require_bool(item["fictional"], "scenario.fictional")
    if not fictional:
        raise InputError("scenario.fictional must be true; Corridor Lab accepts synthetic scenarios only")
    routes_raw = item.get("routes", [])
    if not isinstance(routes_raw, list):
        raise InputError("scenario.routes must be an array")
    if len(routes_raw) > MAX_ROUTES:
        raise InputError(f"scenario.routes exceeds the {MAX_ROUTES}-route budget")
    routes = tuple(parse_route(route, f"scenario.routes[{index}]") for index, route in enumerate(routes_raw))
    if allowed_route_versions is not None:
        for index, route in enumerate(routes):
            if route.contract_version not in allowed_route_versions:
                raise InputError(
                    f"scenario.routes[{index}].contract_version must be one of "
                    f"{', '.join(allowed_route_versions)} in a {version} scenario"
                )
    identifiers = [route.route_id for route in routes]
    if len(identifiers) != len(set(identifiers)):
        raise InputError("scenario.routes has duplicate route_id values")
    return (
        require_identifier(item["scenario_id"], "scenario.scenario_id"),
        require_string(item["description"], "scenario.description"),
        fictional,
        _parse_transaction(item["transaction"]),
        routes,
        _parse_objective(item["objective"]) if "objective" in item else None,
    )


def _parse_scenario_v1(item: dict[str, Any]) -> Scenario:
    scenario_id, description, fictional, transaction, routes, objective = _scenario_common(
        item, SCENARIO_CONTRACT_VERSION, set(), (ROUTE_CONTRACT_VERSION,)
    )
    return Scenario(
        scenario_id=scenario_id,
        description=description,
        fictional=fictional,
        transaction=transaction,
        routes=routes,
        objective=objective,
        contract_version=SCENARIO_CONTRACT_VERSION,
    )


def _parse_scenario_v2(item: dict[str, Any]) -> Scenario:
    scenario_id, description, fictional, transaction, routes, objective = _scenario_common(
        item,
        SCENARIO_CONTRACT_VERSION_V2,
        {"workload_scenarios", "funding"},
        (ROUTE_CONTRACT_VERSION, ROUTE_CONTRACT_VERSION_V2),
    )
    from .funding import parse_funding

    return Scenario(
        scenario_id=scenario_id,
        description=description,
        fictional=fictional,
        transaction=transaction,
        routes=routes,
        objective=objective,
        contract_version=SCENARIO_CONTRACT_VERSION_V2,
        workloads=_parse_workloads(item.get("workload_scenarios", [])),
        funding=parse_funding(item["funding"]) if "funding" in item else None,
    )


def _parse_workloads(value: Any) -> tuple[Workload, ...]:
    path = "scenario.workload_scenarios"
    if not isinstance(value, list):
        raise InputError(f"{path} must be an array")
    if len(value) > MAX_WORKLOADS:
        raise InputError(f"{path} exceeds the {MAX_WORKLOADS}-workload budget")
    parsed: list[Workload] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(value):
        location = f"{path}[{index}]"
        item = require_object(raw, location)
        require_keys(item, {"workload_id", "label", "transactions_per_period"}, set(), location)
        workload_id = require_identifier(item["workload_id"], f"{location}.workload_id")
        if workload_id in identifiers:
            raise InputError(f"{path} has duplicate workload_id: {workload_id}")
        identifiers.add(workload_id)
        parsed.append(
            Workload(
                workload_id=workload_id,
                label=require_string(item["label"], f"{location}.label"),
                transactions_per_period=require_decimal(
                    item["transactions_per_period"], f"{location}.transactions_per_period", positive=True
                ),
            )
        )
    return tuple(parsed)


def load_scenario(path: str | Path) -> Scenario:
    return parse_scenario(load_json(path))


def parse_scenario_text(text: str) -> Scenario:
    """Validate an in-memory fictional scenario with the file-input rules."""
    return parse_scenario(parse_json_text(text))
