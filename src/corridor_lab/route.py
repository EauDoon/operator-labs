"""Versioned, fictional route contracts and parsing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from .canonical import (
    InputError,
    decimal_text,
    load_json,
    require_bool,
    require_decimal,
    require_keys,
    local_decimal_context,
    require_object,
    require_identifier,
    require_string,
)
from .canonical import MAX_OUTCOMES_PER_ROUTE
from .outcomes import Outcome


ROUTE_CONTRACT_VERSION = "corridor-lab.route/v1"
MAX_BPS = Decimal("10000")


@dataclass(frozen=True)
class Liquidity:
    prefunding_amount_send: Decimal
    annual_cost_of_capital_bps: Decimal
    holding_days: Decimal


@dataclass(frozen=True)
class Route:
    route_id: str
    label: str
    fictional: bool
    fx_rate: Decimal
    fixed_fee_send: Decimal
    percent_fee_bps: Decimal
    fx_spread_bps: Decimal
    liquidity: Liquidity
    outcomes: tuple[Outcome, ...]

    def changed_parameter(self, parameter: str, value: Decimal) -> "Route":
        """Return a copy changing exactly one documented top-level parameter."""
        if parameter not in {"fx_rate", "fixed_fee_send", "percent_fee_bps", "fx_spread_bps"}:
            raise InputError(f"unsupported sensitivity parameter: {parameter}")
        if parameter == "fx_rate" and value <= 0:
            raise InputError("fx_rate sensitivity values must be greater than zero")
        if parameter != "fx_rate" and value < 0:
            raise InputError(f"{parameter} sensitivity values must be non-negative")
        if parameter.endswith("bps") and value > MAX_BPS:
            raise InputError(f"{parameter} sensitivity values must not exceed 10000")
        return replace(self, **{parameter: value})


def _parse_liquidity(value: Any, path: str) -> Liquidity:
    item = require_object(value, path)
    require_keys(
        item,
        {"prefunding_amount_send", "annual_cost_of_capital_bps", "holding_days"},
        set(),
        path,
    )
    return Liquidity(
        prefunding_amount_send=require_decimal(item["prefunding_amount_send"], f"{path}.prefunding_amount_send", minimum=Decimal("0")),
        annual_cost_of_capital_bps=require_decimal(item["annual_cost_of_capital_bps"], f"{path}.annual_cost_of_capital_bps", minimum=Decimal("0"), maximum=MAX_BPS),
        holding_days=require_decimal(item["holding_days"], f"{path}.holding_days", minimum=Decimal("0")),
    )


def _parse_outcomes(value: Any, path: str) -> tuple[Outcome, ...]:
    if not isinstance(value, list) or not value:
        raise InputError(f"{path} must be a non-empty array")
    if len(value) > MAX_OUTCOMES_PER_ROUTE:
        raise InputError(f"{path} exceeds the {MAX_OUTCOMES_PER_ROUTE}-outcome budget")
    parsed: list[Outcome] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(value):
        location = f"{path}[{index}]"
        item = require_object(raw, location)
        require_keys(
            item,
            {
                "outcome_id",
                "probability",
                "completion",
                "delay_hours",
                "recovery_amount_send",
                "recovery_delay_hours",
            },
            set(),
            location,
        )
        outcome_id = require_identifier(item["outcome_id"], f"{location}.outcome_id")
        if outcome_id in seen_ids:
            raise InputError(f"{path} has duplicate outcome_id: {outcome_id}")
        seen_ids.add(outcome_id)
        completion = require_string(item["completion"], f"{location}.completion")
        if completion not in {"success", "failure"}:
            raise InputError(f"{location}.completion must be success or failure")
        recovery_amount = require_decimal(
            item["recovery_amount_send"], f"{location}.recovery_amount_send", minimum=Decimal("0")
        )
        recovery_delay = require_decimal(
            item["recovery_delay_hours"], f"{location}.recovery_delay_hours", minimum=Decimal("0")
        )
        if completion == "success" and (recovery_amount != 0 or recovery_delay != 0):
            raise InputError(f"{location} success outcome cannot include recovery fields")
        parsed.append(
            Outcome(
                outcome_id=outcome_id,
                probability=require_decimal(item["probability"], f"{location}.probability", positive=True),
                completion=completion,
                delay_hours=require_decimal(item["delay_hours"], f"{location}.delay_hours", minimum=Decimal("0")),
                recovery_amount_send=recovery_amount,
                recovery_delay_hours=recovery_delay,
            )
        )
    with local_decimal_context():
        total = sum((outcome.probability for outcome in parsed), Decimal("0"))
    if total != Decimal("1"):
        raise InputError(f"{path} probabilities must sum exactly to 1, got {decimal_text(total)}")
    return tuple(parsed)


def parse_route(value: Any, path: str = "route") -> Route:
    item = require_object(value, path)
    require_keys(
        item,
        {
            "contract_version",
            "route_id",
            "label",
            "fictional",
            "fx_rate",
            "fixed_fee_send",
            "percent_fee_bps",
            "fx_spread_bps",
            "liquidity",
            "outcomes",
        },
        set(),
        path,
    )
    if require_string(item["contract_version"], f"{path}.contract_version") != ROUTE_CONTRACT_VERSION:
        raise InputError(f"{path}.contract_version must equal {ROUTE_CONTRACT_VERSION}")
    fictional = require_bool(item["fictional"], f"{path}.fictional")
    if not fictional:
        raise InputError(f"{path}.fictional must be true; Corridor Lab accepts synthetic routes only")
    route = Route(
        route_id=require_identifier(item["route_id"], f"{path}.route_id"),
        label=require_string(item["label"], f"{path}.label"),
        fictional=fictional,
        fx_rate=require_decimal(item["fx_rate"], f"{path}.fx_rate", positive=True),
        fixed_fee_send=require_decimal(item["fixed_fee_send"], f"{path}.fixed_fee_send", minimum=Decimal("0")),
        percent_fee_bps=require_decimal(item["percent_fee_bps"], f"{path}.percent_fee_bps", minimum=Decimal("0"), maximum=MAX_BPS),
        fx_spread_bps=require_decimal(item["fx_spread_bps"], f"{path}.fx_spread_bps", minimum=Decimal("0"), maximum=MAX_BPS),
        liquidity=_parse_liquidity(item["liquidity"], f"{path}.liquidity"),
        outcomes=_parse_outcomes(item["outcomes"], f"{path}.outcomes"),
    )
    return route


def load_route(path: str | Path) -> Route:
    return parse_route(load_json(path), str(path))
