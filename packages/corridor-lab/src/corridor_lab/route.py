"""Versioned, fictional route contracts and parsing."""

from __future__ import annotations

import os
import stat as stat_module
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from .canonical import (
    MAX_BPS,
    MAX_INPUT_BYTES,
    MAX_OUTCOMES_PER_ROUTE,
    MAX_ROUTES,
    InputError,
    decimal_text,
    load_json,
    parse_json_bytes,
    require_bool,
    require_decimal,
    require_keys,
    local_decimal_context,
    require_object,
    require_identifier,
    require_string,
)
from .fees import FeeSchedule, parse_fee_schedule
from .legs import Leg, compose, parse_legs, require_terminal_leg, terminal_leg_delays
from .outcomes import Outcome


ROUTE_CONTRACT_VERSION = "corridor-lab.route/v1"
ROUTE_CONTRACT_VERSION_V2 = "corridor-lab.route/v2"
SUPPORTED_ROUTE_CONTRACT_VERSIONS = (ROUTE_CONTRACT_VERSION, ROUTE_CONTRACT_VERSION_V2)
MAX_BPS = MAX_BPS
SENSITIVITY_PARAMETERS = ("fx_rate", "fixed_fee_send", "percent_fee_bps", "fx_spread_bps")


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
    contract_version: str = ROUTE_CONTRACT_VERSION
    fee_schedule: FeeSchedule | None = None
    legs: tuple[Leg, ...] = ()

    @property
    def uses_fee_schedule(self) -> bool:
        return self.fee_schedule is not None

    @property
    def is_composed(self) -> bool:
        return bool(self.legs)

    def outcome_resolution_hours(self, outcome: Outcome) -> Decimal:
        """Time to a final state for a declared outcome.

        Composed routes add the declared leg delays up to the outcome's terminal
        leg. Single-leg routes use the outcome's own declared delay.
        """
        with local_decimal_context():
            if not self.legs:
                return outcome.resolution_hours
            assert outcome.terminal_leg is not None
            leg_time = terminal_leg_delays(self.legs)[outcome.terminal_leg]
            additional = outcome.delay_hours
            if outcome.completion == "failure":
                additional += outcome.recovery_delay_hours
            return leg_time + additional

    def changed_parameter(self, parameter: str, value: Decimal) -> Route:
        """Return a copy changing exactly one documented top-level parameter."""
        name = parameter.strip()
        if not name:
            raise InputError("parameter must not be empty")
        if name not in SENSITIVITY_PARAMETERS:
            raise InputError(
                f"unsupported sensitivity parameter: {name} (choose from {', '.join(SENSITIVITY_PARAMETERS)})"
            )
        if self.uses_fee_schedule and name in ("fixed_fee_send", "percent_fee_bps"):
            raise InputError(
                f"route {self.route_id} declares a tiered fee schedule, so {name} is not an active assumption"
            )
        parsed = require_decimal(value, f"{name} sensitivity value")
        if name == "fx_rate" and parsed <= 0:
            raise InputError("fx_rate sensitivity values must be greater than zero")
        if name != "fx_rate" and parsed < 0:
            raise InputError(f"{name} sensitivity values must be non-negative")
        if name.endswith("bps") and parsed > MAX_BPS:
            raise InputError(f"{name} sensitivity values must not exceed 10000")
        return replace(self, **{name: parsed})


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


def _parse_outcomes(value: Any, path: str, legs: tuple[Leg, ...] = ()) -> tuple[Outcome, ...]:
    """Parse declared outcomes, requiring `terminal_leg` only for composed routes."""
    if not isinstance(value, list) or not value:
        raise InputError(f"{path} must be a non-empty array")
    if len(value) > MAX_OUTCOMES_PER_ROUTE:
        raise InputError(f"{path} exceeds the {MAX_OUTCOMES_PER_ROUTE}-outcome budget")
    known_legs = {leg.leg_id for leg in legs}
    final_leg = legs[-1].leg_id if legs else None
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
            {"terminal_leg"} if legs else set(),
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
        terminal_leg: str | None = None
        if legs:
            if "terminal_leg" not in item:
                raise InputError(f"{location} missing required field(s): terminal_leg")
            terminal_leg = require_terminal_leg(item["terminal_leg"], f"{location}.terminal_leg", known_legs)
            if completion == "success" and terminal_leg != final_leg:
                raise InputError(
                    f"{location} is a success outcome, so terminal_leg must be the final leg ({final_leg})"
                )
        parsed.append(
            Outcome(
                outcome_id=outcome_id,
                probability=require_decimal(item["probability"], f"{location}.probability", positive=True),
                completion=completion,
                delay_hours=require_decimal(item["delay_hours"], f"{location}.delay_hours", minimum=Decimal("0")),
                recovery_amount_send=recovery_amount,
                recovery_delay_hours=recovery_delay,
                terminal_leg=terminal_leg,
            )
        )
    with local_decimal_context():
        total = sum((outcome.probability for outcome in parsed), Decimal("0"))
    if total != Decimal("1"):
        raise InputError(f"{path} probabilities must sum exactly to 1, got {decimal_text(total)}")
    return tuple(parsed)


def parse_route(value: Any, path: str = "route") -> Route:
    """Dispatch on the declared route contract version.

    ``corridor-lab.route/v1`` keeps its original strict field set. The v2
    contract adds optional declared fee structures and never reinterprets a v1
    document.
    """
    item = require_object(value, path)
    if "contract_version" not in item:
        raise InputError(f"{path} missing required field(s): contract_version")
    version = require_string(item["contract_version"], f"{path}.contract_version")
    if version == ROUTE_CONTRACT_VERSION:
        return _parse_route_v1(item, path)
    if version == ROUTE_CONTRACT_VERSION_V2:
        return _parse_route_v2(item, path)
    raise InputError(
        f"{path}.contract_version must be one of {', '.join(SUPPORTED_ROUTE_CONTRACT_VERSIONS)}"
    )


def _parse_route_v1(item: dict[str, Any], path: str) -> Route:
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
        contract_version=ROUTE_CONTRACT_VERSION,
    )
    return route


def _parse_route_v2(item: dict[str, Any], path: str) -> Route:
    """Parse a v2 route, which is either a scalar route or a declared leg chain."""
    if "legs" in item:
        return _parse_composed_route_v2(item, path)
    require_keys(
        item,
        {
            "contract_version",
            "route_id",
            "label",
            "fictional",
            "fx_rate",
            "fx_spread_bps",
            "liquidity",
            "outcomes",
        },
        {"fixed_fee_send", "percent_fee_bps", "fee_schedule"},
        path,
    )
    fictional = require_bool(item["fictional"], f"{path}.fictional")
    if not fictional:
        raise InputError(f"{path}.fictional must be true; Corridor Lab accepts synthetic routes only")
    has_schedule = "fee_schedule" in item
    if has_schedule:
        for field in ("fixed_fee_send", "percent_fee_bps"):
            if field in item:
                raise InputError(
                    f"{path}.{field} must be omitted when fee_schedule is declared; "
                    "mixing a flat fee with a tiered schedule would double count fees"
                )
        fixed_fee = Decimal("0")
        percent_fee_bps = Decimal("0")
    else:
        for field in ("fixed_fee_send", "percent_fee_bps"):
            if field not in item:
                raise InputError(f"{path} missing required field(s): {field}")
        fixed_fee = require_decimal(item["fixed_fee_send"], f"{path}.fixed_fee_send", minimum=Decimal("0"))
        percent_fee_bps = require_decimal(
            item["percent_fee_bps"], f"{path}.percent_fee_bps", minimum=Decimal("0"), maximum=MAX_BPS
        )
    return Route(
        route_id=require_identifier(item["route_id"], f"{path}.route_id"),
        label=require_string(item["label"], f"{path}.label"),
        fictional=fictional,
        fx_rate=require_decimal(item["fx_rate"], f"{path}.fx_rate", positive=True),
        fixed_fee_send=fixed_fee,
        percent_fee_bps=percent_fee_bps,
        fx_spread_bps=require_decimal(item["fx_spread_bps"], f"{path}.fx_spread_bps", minimum=Decimal("0"), maximum=MAX_BPS),
        liquidity=_parse_liquidity(item["liquidity"], f"{path}.liquidity"),
        outcomes=_parse_outcomes(item["outcomes"], f"{path}.outcomes"),
        contract_version=ROUTE_CONTRACT_VERSION_V2,
        fee_schedule=parse_fee_schedule(item["fee_schedule"], f"{path}.fee_schedule") if has_schedule else None,
    )


def _parse_composed_route_v2(item: dict[str, Any], path: str) -> Route:
    """A composed route: an explicit leg chain with declared joint outcomes."""
    require_keys(
        item,
        {
            "contract_version",
            "route_id",
            "label",
            "fictional",
            "liquidity",
            "outcomes",
            "legs",
        },
        # Accepted by the key check so that the explicit message below, which
        # explains why they must be omitted, is the one a reader sees.
        {"fx_rate", "fx_spread_bps", "fixed_fee_send", "percent_fee_bps", "fee_schedule"},
        path,
    )
    for field in ("fx_rate", "fx_spread_bps", "fixed_fee_send", "percent_fee_bps", "fee_schedule"):
        if field in item:
            raise InputError(
                f"{path}.{field} must be omitted when legs are declared; each leg carries its own {field}"
            )
    fictional = require_bool(item["fictional"], f"{path}.fictional")
    if not fictional:
        raise InputError(f"{path}.fictional must be true; Corridor Lab accepts synthetic routes only")
    # The chain's own structure is validated here. Its endpoints are checked
    # against the declared send and receive currencies when the route is
    # evaluated against a transaction, because a route document is also valid
    # on its own.
    legs = parse_legs(item["legs"], f"{path}.legs")
    return Route(
        route_id=require_identifier(item["route_id"], f"{path}.route_id"),
        label=require_string(item["label"], f"{path}.label"),
        fictional=fictional,
        fx_rate=Decimal("0"),
        fixed_fee_send=Decimal("0"),
        percent_fee_bps=Decimal("0"),
        fx_spread_bps=Decimal("0"),
        liquidity=_parse_liquidity(item["liquidity"], f"{path}.liquidity"),
        outcomes=_parse_outcomes(item["outcomes"], f"{path}.outcomes", legs),
        contract_version=ROUTE_CONTRACT_VERSION_V2,
        legs=legs,
    )


def load_route(path: str | Path) -> Route:
    return parse_route(load_json(path), str(path))


def _read_scanned_route(
    directory: Path,
    name: str,
    expected: os.stat_result,
    directory_fd: int | None,
) -> Route:
    """Read the same regular file observed during the directory scan."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = (
            os.open(name, flags, dir_fd=directory_fd)
            if directory_fd is not None
            else os.open(directory / name, flags)
        )
        opened = os.fstat(descriptor)
        if not stat_module.S_ISREG(opened.st_mode) or not os.path.samestat(expected, opened):
            raise InputError("route folder changed while being read")
        with os.fdopen(descriptor, "rb") as route_file:
            descriptor = None
            raw = route_file.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise InputError("route folder changed while being read") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > MAX_INPUT_BYTES:
        raise InputError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    return parse_route(parse_json_bytes(raw), str(directory / name))


def load_route_folder(path: str | Path) -> list[Route]:
    """Load a bounded snapshot of regular JSON files without following links."""

    directory = Path(path)
    directory_fd: int | None = None
    try:
        expected_directory = os.lstat(directory)
        if not stat_module.S_ISDIR(expected_directory.st_mode):
            raise InputError(f"route selection is not a folder: {directory}")

        use_directory_fd = (
            os.scandir in os.supports_fd
            and os.open in os.supports_dir_fd
            and os.stat in os.supports_dir_fd
        )
        if use_directory_fd:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            directory_fd = os.open(directory, flags)
            if not os.path.samestat(expected_directory, os.fstat(directory_fd)):
                raise InputError("route folder changed while being read")
            scan_target: str | Path | int = directory_fd
        else:
            scan_target = directory

        with os.scandir(scan_target) as iterator:
            files = sorted(
                (
                    (
                        entry.name,
                        os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
                        if directory_fd is not None
                        else os.stat(entry.path, follow_symlinks=False),
                    )
                    for entry in iterator
                    if entry.name.lower().endswith(".json")
                    and entry.is_file(follow_symlinks=False)
                ),
                key=lambda item: item[0],
            )
        if directory_fd is None and not os.path.samestat(expected_directory, os.lstat(directory)):
            raise InputError("route folder changed while being read")
        if not files:
            raise InputError(f"route folder contains no JSON files: {directory}")
        if len(files) > MAX_ROUTES:
            raise InputError(f"route folder exceeds the {MAX_ROUTES}-route budget")
        routes = [
            _read_scanned_route(directory, name, metadata, directory_fd)
            for name, metadata in files
        ]
        if directory_fd is None and not os.path.samestat(expected_directory, os.lstat(directory)):
            raise InputError("route folder changed while being read")
        return routes
    except OSError as exc:
        raise InputError(f"cannot read route folder: {directory}") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
