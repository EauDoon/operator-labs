"""A library of synthetic, fictional scenario and route templates.

Every template is a valid Corridor Lab document and parses through
:func:`corridor_lab.scenario.parse_scenario` or
:func:`corridor_lab.route.parse_route`. They exist so a new user can start from
a declared structure that already demonstrates a distinct cost shape, funding
requirement, outcome mix, deadline, and volume, instead of editing a blank file.

The templates are deliberately different from one another. They are not renames
of a single example: each varies the fee structure, the liquidity assumptions,
the outcome distribution, the deadline, or the volume, and `notes` states which
axis a given template exists to demonstrate.

All values are invented. No template represents a real corridor, provider,
network, price, or institution.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import InputError, canonical_dumps

TEMPLATE_KINDS = ("scenario", "route")


def _transaction(
    send_amount: str,
    deadline_hours: str,
    volume_per_period: str,
    send_currency: str = "AMR",
    receive_currency: str = "BRC",
    rounding: str = "ROUND_HALF_UP",
    send_precision: int = 2,
    receive_precision: int = 2,
) -> dict[str, Any]:
    return {
        "send_amount": send_amount,
        "send_currency": send_currency,
        "send_precision": send_precision,
        "receive_currency": receive_currency,
        "receive_precision": receive_precision,
        "rounding": rounding,
        "deadline_hours": deadline_hours,
        "volume_per_period": volume_per_period,
    }


def _liquidity(prefunding: str, annual_bps: str, holding_days: str) -> dict[str, str]:
    return {
        "prefunding_amount_send": prefunding,
        "annual_cost_of_capital_bps": annual_bps,
        "holding_days": holding_days,
    }


def _outcome(
    outcome_id: str,
    probability: str,
    completion: str,
    delay_hours: str,
    recovery_amount: str = "0",
    recovery_delay: str = "0",
    terminal_leg: str | None = None,
) -> dict[str, Any]:
    result = {
        "outcome_id": outcome_id,
        "probability": probability,
        "completion": completion,
        "delay_hours": delay_hours,
        "recovery_amount_send": recovery_amount,
        "recovery_delay_hours": recovery_delay,
    }
    if terminal_leg is not None:
        result["terminal_leg"] = terminal_leg
    return result


def _v2_route(
    route_id: str,
    label: str,
    liquidity: dict[str, str],
    outcomes: list[dict[str, Any]],
    fx_rate: str = "1.7500",
    fx_spread_bps: str = "50",
    fixed_fee_send: str | None = None,
    percent_fee_bps: str | None = None,
    fee_schedule: dict[str, Any] | None = None,
    legs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    route: dict[str, Any] = {
        "contract_version": "corridor-lab.route/v2",
        "route_id": route_id,
        "label": label,
        "fictional": True,
        "liquidity": liquidity,
        "outcomes": outcomes,
    }
    if legs is not None:
        route["legs"] = legs
        return route
    route["fx_rate"] = fx_rate
    route["fx_spread_bps"] = fx_spread_bps
    if fee_schedule is not None:
        route["fee_schedule"] = fee_schedule
    else:
        route["fixed_fee_send"] = fixed_fee_send
        route["percent_fee_bps"] = percent_fee_bps
    return route


def _v1_route(
    route_id: str,
    label: str,
    liquidity: dict[str, str],
    outcomes: list[dict[str, Any]],
    fx_rate: str = "1.7500",
    fx_spread_bps: str = "50",
    fixed_fee_send: str = "6.00",
    percent_fee_bps: str = "20",
) -> dict[str, Any]:
    return {
        "contract_version": "corridor-lab.route/v1",
        "route_id": route_id,
        "label": label,
        "fictional": True,
        "fx_rate": fx_rate,
        "fixed_fee_send": fixed_fee_send,
        "percent_fee_bps": percent_fee_bps,
        "fx_spread_bps": fx_spread_bps,
        "liquidity": liquidity,
        "outcomes": outcomes,
    }


_TEMPLATES: dict[str, dict[str, Any]] = {
    "flat-fee-low-volume": {
        "kind": "scenario",
        "title": "Flat fee, low volume, tight deadline",
        "notes": (
            "The simplest declared structure: one flat fee and one percentage fee per route, a small declared "
            "volume that leaves liquidity carrying cost visible, and a 4-hour deadline that only the fastest "
            "outcome can meet. Use it to see deadline probability reject a cheaper but slower route."
        ),
        "document": {
            "contract_version": "corridor-lab.scenario/v1",
            "scenario_id": "fictional-flat-fee-low-volume",
            "description": "A fictional low-volume corridor with flat fees and a tight deadline.",
            "fictional": True,
            "transaction": _transaction("500.00", "4", "20"),
            "objective": {
                "metric": "minimize_expected_sender_cost",
                "guardrails": {"minimum_probability_by_deadline": "0.90", "maximum_tail_hours": "24"},
            },
            "routes": [
                _v1_route(
                    "fast-expensive",
                    "Fast but expensive flat-fee route (fictional)",
                    _liquidity("4000", "600", "0.5"),
                    [
                        _outcome("on-time", "0.94", "success", "1"),
                        _outcome("late", "0.04", "success", "9"),
                        _outcome("failed", "0.02", "failure", "2", "470", "10"),
                    ],
                    fixed_fee_send="9.00",
                    percent_fee_bps="35",
                ),
                _v1_route(
                    "slow-cheap",
                    "Slow but cheap flat-fee route (fictional)",
                    _liquidity("20000", "1000", "2"),
                    [
                        _outcome("on-time", "0.20", "success", "3"),
                        _outcome("late", "0.77", "success", "30"),
                        _outcome("failed", "0.03", "failure", "4", "480", "36"),
                    ],
                    fixed_fee_send="1.00",
                    percent_fee_bps="5",
                ),
            ],
        },
    },
    "tiered-marginal-platform-fee": {
        "kind": "scenario",
        "title": "Tiered marginal fees with a volume-amortized platform charge",
        "notes": (
            "Demonstrates a declared tiered schedule: marginal bands, a fixed fee charged once, and a period "
            "charge amortized over the declared volume. Raising the volume lowers the amortized charge, so the "
            "route ordering can reverse. Use it with `workload` and `break-even`."
        ),
        "document": {
            "contract_version": "corridor-lab.scenario/v2",
            "scenario_id": "fictional-tiered-marginal",
            "description": "A fictional corridor with declared marginal fee bands and a period charge.",
            "fictional": True,
            "transaction": _transaction("1000.00", "12", "100"),
            "workload_scenarios": [
                {"workload_id": "low", "label": "Low declared volume", "transactions_per_period": "50"},
                {"workload_id": "base", "label": "Base declared volume", "transactions_per_period": "100"},
                {"workload_id": "peak", "label": "Peak declared volume", "transactions_per_period": "400"},
            ],
            "objective": {
                "metric": "minimize_expected_sender_cost",
                "guardrails": {"minimum_probability_by_deadline": "0.90"},
            },
            "routes": [
                _v2_route(
                    "tiered-marginal",
                    "Declared marginal bands plus a platform charge (fictional)",
                    _liquidity("36500", "1000", "1"),
                    [
                        _outcome("on-time", "0.95", "success", "2"),
                        _outcome("late-success", "0.03", "success", "14"),
                        _outcome("failed-recovered", "0.02", "failure", "3", "980", "24"),
                    ],
                    fee_schedule={
                        "basis": "marginal",
                        "tiers": [
                            {"upper_bound_send": "500", "fixed_fee_send": "5.00", "percent_fee_bps": "40"},
                            {"upper_bound_send": "1500", "fixed_fee_send": "3.00", "percent_fee_bps": "25"},
                            {"upper_bound_send": None, "fixed_fee_send": "0", "percent_fee_bps": "15"},
                        ],
                        "period_charges": [
                            {
                                "label": "monthly-platform-fee",
                                "amount_send": "400.00",
                                "amortization_over": "scenario_volume",
                            }
                        ],
                    },
                ),
                _v2_route(
                    "flat-fee",
                    "Declared flat fee with no period charges (fictional)",
                    _liquidity("20000", "1000", "0.5"),
                    [
                        _outcome("on-time", "0.95", "success", "2"),
                        _outcome("late-success", "0.03", "success", "14"),
                        _outcome("failed-recovered", "0.02", "failure", "3", "980", "24"),
                    ],
                    fixed_fee_send="6.00",
                    percent_fee_bps="20",
                ),
            ],
        },
    },
    "whole-band-prefunding-heavy": {
        "kind": "scenario",
        "title": "Whole-band tiers with heavy prefunding",
        "notes": (
            "Demonstrates whole-band tier semantics, where one band's fixed and percentage fee applies to the "
            "whole amount, and a prefunding-heavy liquidity profile where carrying cost dominates the sender "
            "cost at low volumes. Compare it with the marginal template to see the two bases diverge."
        ),
        "document": {
            "contract_version": "corridor-lab.scenario/v2",
            "scenario_id": "fictional-whole-band-prefunding",
            "description": "A fictional corridor with whole-band tiers and heavy declared prefunding.",
            "fictional": True,
            "transaction": _transaction("2000.00", "24", "10"),
            "workload_scenarios": [
                {"workload_id": "sparse", "label": "Very sparse declared volume", "transactions_per_period": "5"},
                {"workload_id": "dense", "label": "Dense declared volume", "transactions_per_period": "200"},
            ],
            "routes": [
                _v2_route(
                    "whole-band",
                    "Declared whole-band tiers (fictional)",
                    _liquidity("250000", "1200", "3"),
                    [
                        _outcome("on-time", "0.90", "success", "6"),
                        _outcome("failed", "0.10", "failure", "6", "1900", "48"),
                    ],
                    fee_schedule={
                        "basis": "whole_band",
                        "tiers": [
                            {"upper_bound_send": "1000", "fixed_fee_send": "12.00", "percent_fee_bps": "60"},
                            {"upper_bound_send": "5000", "fixed_fee_send": "4.00", "percent_fee_bps": "18"},
                            {"upper_bound_send": None, "fixed_fee_send": "0", "percent_fee_bps": "8"},
                        ],
                        "period_charges": [
                            {
                                "label": "quarterly-onboarding",
                                "amount_send": "900.00",
                                "amortization_over": "declared_transactions",
                                "period_transactions": "600",
                            }
                        ],
                    },
                ),
                _v2_route(
                    "marginal-alternative",
                    "Declared marginal tiers on the same bands (fictional)",
                    _liquidity("250000", "1200", "3"),
                    [
                        _outcome("on-time", "0.90", "success", "6"),
                        _outcome("failed", "0.10", "failure", "6", "1900", "48"),
                    ],
                    fee_schedule={
                        "basis": "marginal",
                        "tiers": [
                            {"upper_bound_send": "1000", "fixed_fee_send": "12.00", "percent_fee_bps": "60"},
                            {"upper_bound_send": "5000", "fixed_fee_send": "4.00", "percent_fee_bps": "18"},
                            {"upper_bound_send": None, "fixed_fee_send": "0", "percent_fee_bps": "8"},
                        ],
                    },
                ),
            ],
        },
    },
    "high-failure-long-recovery": {
        "kind": "scenario",
        "title": "High failure probability with long recovery",
        "notes": (
            "Demonstrates how expected recipient amount and expected sender cost respond to a high declared "
            "failure probability with a long recovery delay and only partial recovery of principal. The "
            "conditional recipient amount stays high while the expected value collapses; those two numbers are "
            "reported separately on purpose."
        ),
        "document": {
            "contract_version": "corridor-lab.scenario/v1",
            "scenario_id": "fictional-high-failure-recovery",
            "description": "A fictional corridor with a high declared failure rate and slow partial recovery.",
            "fictional": True,
            "transaction": _transaction("1000.00", "72", "40"),
            "objective": {
                "metric": "maximize_expected_recipient_amount",
                "guardrails": {"maximum_tail_hours": "96"},
            },
            "routes": [
                _v1_route(
                    "optimistic",
                    "Optimistic declared outcomes (fictional)",
                    _liquidity("10000", "800", "1"),
                    [
                        _outcome("on-time", "0.98", "success", "2"),
                        _outcome("failed", "0.02", "failure", "2", "990", "12"),
                    ],
                ),
                _v1_route(
                    "pessimistic",
                    "Pessimistic declared outcomes with slow partial recovery (fictional)",
                    _liquidity("10000", "800", "1"),
                    [
                        _outcome("on-time", "0.55", "success", "3"),
                        _outcome("failed", "0.45", "failure", "3", "600", "72"),
                    ],
                    fixed_fee_send="0",
                    percent_fee_bps="0",
                ),
            ],
        },
    },
    "multi-leg-joint-outcomes": {
        "kind": "scenario",
        "title": "Two-leg chain with declared joint outcomes",
        "notes": (
            "Demonstrates bounded multi-leg composition: an explicit currency chain, per-leg fees and delays, "
            "and joint outcomes that name the terminating leg. Failure probabilities are declared, never "
            "multiplied across legs."
        ),
        "document": {
            "contract_version": "corridor-lab.scenario/v2",
            "scenario_id": "fictional-multi-leg-joint",
            "description": "A fictional two-leg corridor with declared joint outcomes.",
            "fictional": True,
            "transaction": _transaction("1000.00", "24", "100"),
            "objective": {
                "metric": "maximize_expected_recipient_amount",
                "guardrails": {"minimum_probability_by_deadline": "0.90"},
            },
            "routes": [
                _v2_route(
                    "two-leg-chain",
                    "Declared two-leg chain (fictional)",
                    _liquidity("20000", "1000", "0.5"),
                    [
                        _outcome("completed", "0.95", "success", "0", terminal_leg="offshore"),
                        _outcome("failed-on-leg-1", "0.03", "failure", "0", "995", "12", terminal_leg="onshore"),
                        _outcome("failed-on-leg-2", "0.02", "failure", "0", "990", "24", terminal_leg="offshore"),
                    ],
                    legs=[
                        {
                            "leg_id": "onshore",
                            "from_currency": "AMR",
                            "to_currency": "USD",
                            "fx_rate": "1.25",
                            "fx_spread_bps": "20",
                            "fixed_fee_send": "1.00",
                            "percent_fee_bps": "10",
                            "delay_hours": "1",
                        },
                        {
                            "leg_id": "offshore",
                            "from_currency": "USD",
                            "to_currency": "BRC",
                            "fx_rate": "1.40",
                            "fx_spread_bps": "30",
                            "fixed_fee_send": "2.00",
                            "percent_fee_bps": "15",
                            "delay_hours": "3",
                        },
                    ],
                ),
                _v2_route(
                    "single-leg-direct",
                    "Declared single-leg direct route (fictional)",
                    _liquidity("20000", "1000", "0.5"),
                    [
                        _outcome("completed", "0.95", "success", "4"),
                        _outcome("failed-recovered", "0.05", "failure", "4", "993", "16"),
                    ],
                    fx_rate="1.7412605",
                    fx_spread_bps="0",
                    fixed_fee_send="5.10",
                    percent_fee_bps="0",
                ),
            ],
        },
    },
    "funding-shortfall": {
        "kind": "scenario",
        "title": "Multi-period funding with a declared shortfall",
        "notes": (
            "Demonstrates the funding module: a declared disbursement and recovery schedule whose required "
            "prefunding exceeds the declared opening balance, so a shortfall and the periods that fall below "
            "zero are reported. Use `--delays` to see how a declared recovery delay moves the requirement."
        ),
        "document": {
            "contract_version": "corridor-lab.scenario/v2",
            "scenario_id": "fictional-funding-shortfall",
            "description": "A fictional funding schedule with a declared shortfall.",
            "fictional": True,
            "transaction": _transaction("1000.00", "12", "100"),
            "funding": {
                "opening_balance_send": "1000.00",
                "days_per_period": "30",
                "settlement_delay_periods": 1,
                "recovery_delay_periods": 0,
                "periods": [
                    {"period_index": 1, "disbursements_send": "1000.00", "recoveries_send": "0"},
                    {"period_index": 2, "disbursements_send": "1000.00", "recoveries_send": "1000.00"},
                    {"period_index": 3, "disbursements_send": "1000.00", "recoveries_send": "1000.00"},
                ],
            },
            "routes": [
                _v2_route(
                    "cheap-capital",
                    "Declared low capital cost and low failure rate (fictional)",
                    _liquidity("20000", "600", "0.5"),
                    [
                        _outcome("success", "0.99", "success", "2"),
                        _outcome("failed-recovered", "0.01", "failure", "3", "950", "24"),
                    ],
                    fixed_fee_send="6.00",
                    percent_fee_bps="20",
                ),
                _v2_route(
                    "expensive-capital",
                    "Declared high capital cost and higher failure rate (fictional)",
                    _liquidity("20000", "1000", "0.5"),
                    [
                        _outcome("success", "0.98", "success", "2"),
                        _outcome("failed-recovered", "0.02", "failure", "3", "950", "24"),
                    ],
                    fixed_fee_send="6.00",
                    percent_fee_bps="20",
                ),
            ],
        },
    },
}

_ROUTE_TEMPLATES: dict[str, dict[str, Any]] = {
    "flat-correspondent-style": {
        "kind": "route",
        "title": "Flat fee with prefunded correspondent-style liquidity",
        "notes": "A single flat and percentage fee with a moderate declared prefunding balance.",
        "document": _v1_route(
            "fictional-correspondent",
            "Flat-fee correspondent-style route (fictional)",
            _liquidity("6500", "650", "1.4"),
            [
                _outcome("on-time", "0.94", "success", "1.5"),
                _outcome("late-success", "0.04", "success", "8"),
                _outcome("failed-recovered", "0.02", "failure", "2", "980", "12"),
            ],
            fixed_fee_send="3.00",
            percent_fee_bps="30",
        ),
    },
    "tiered-marginal-route": {
        "kind": "route",
        "title": "Marginal tiered schedule with a platform charge",
        "notes": "Three declared bands with a period charge amortized over the declared volume.",
        "document": _v2_route(
            "fictional-tiered-marginal",
            "Marginal tiered schedule route (fictional)",
            _liquidity("36500", "1000", "1"),
            [
                _outcome("on-time", "0.95", "success", "2"),
                _outcome("failed-recovered", "0.05", "failure", "3", "970", "18"),
            ],
            fee_schedule={
                "basis": "marginal",
                "tiers": [
                    {"upper_bound_send": "500", "fixed_fee_send": "5.00", "percent_fee_bps": "40"},
                    {"upper_bound_send": "1500", "fixed_fee_send": "3.00", "percent_fee_bps": "25"},
                    {"upper_bound_send": None, "fixed_fee_send": "0", "percent_fee_bps": "15"},
                ],
                "period_charges": [
                    {
                        "label": "monthly-platform-fee",
                        "amount_send": "400.00",
                        "amortization_over": "scenario_volume",
                    }
                ],
            },
        ),
    },
    "two-leg-route": {
        "kind": "route",
        "title": "Two-leg chain with joint outcomes",
        "notes": "An explicit currency chain whose outcomes declare the terminating leg.",
        "document": _v2_route(
            "fictional-two-leg",
            "Two-leg chain route (fictional)",
            _liquidity("20000", "1000", "0.5"),
            [
                _outcome("completed", "0.95", "success", "0", terminal_leg="offshore"),
                _outcome("failed-on-leg-1", "0.03", "failure", "0", "995", "12", terminal_leg="onshore"),
                _outcome("failed-on-leg-2", "0.02", "failure", "0", "990", "24", terminal_leg="offshore"),
            ],
            legs=[
                {
                    "leg_id": "onshore",
                    "from_currency": "AMR",
                    "to_currency": "USD",
                    "fx_rate": "1.25",
                    "fx_spread_bps": "20",
                    "fixed_fee_send": "1.00",
                    "percent_fee_bps": "10",
                    "delay_hours": "1",
                },
                {
                    "leg_id": "offshore",
                    "from_currency": "USD",
                    "to_currency": "BRC",
                    "fx_rate": "1.40",
                    "fx_spread_bps": "30",
                    "fixed_fee_send": "2.00",
                    "percent_fee_bps": "15",
                    "delay_hours": "3",
                },
            ],
        ),
    },
    "high-failure-route": {
        "kind": "route",
        "title": "High failure probability with slow partial recovery",
        "notes": "Demonstrates expected-value collapse while the conditional recipient amount stays high.",
        "document": _v1_route(
            "fictional-high-failure",
            "High-failure route (fictional)",
            _liquidity("10000", "800", "1"),
            [
                _outcome("on-time", "0.55", "success", "3"),
                _outcome("failed", "0.45", "failure", "3", "600", "72"),
            ],
            fixed_fee_send="0",
            percent_fee_bps="0",
        ),
    },
}


def template_ids(kind: str | None = None) -> tuple[str, ...]:
    """Return the shipped template identifiers of one kind, sorted."""
    source = _TEMPLATES if kind is None or kind == "scenario" else {}
    if kind == "route":
        source = _ROUTE_TEMPLATES
    elif kind is None:
        source = {**_TEMPLATES, **_ROUTE_TEMPLATES}
    return tuple(sorted(source))


def template(template_id: str) -> dict[str, Any]:
    """Return a deep copy of one template's document."""
    entry = _lookup(template_id)
    return deepcopy(entry["document"])


def describe(template_id: str) -> dict[str, Any]:
    """Return stable metadata for one template."""
    entry = _lookup(template_id)
    document = entry["document"]
    metadata: dict[str, Any] = {
        "template_id": template_id,
        "kind": entry["kind"],
        "title": entry["title"],
        "notes": entry["notes"],
        "contract_version": document["contract_version"],
    }
    if entry["kind"] == "scenario":
        metadata["transaction"] = dict(document["transaction"])
        metadata["routes"] = [route["route_id"] for route in document.get("routes", [])]
        metadata["has_objective"] = "objective" in document
        metadata["declared_workloads"] = [
            workload["workload_id"] for workload in document.get("workload_scenarios", [])
        ]
        metadata["has_funding_schedule"] = "funding" in document
    else:
        metadata["route_id"] = document["route_id"]
        metadata["has_fee_schedule"] = "fee_schedule" in document
        metadata["has_legs"] = "legs" in document
    return metadata


def describe_all(kind: str | None = None) -> list[dict[str, Any]]:
    return [describe(template_id) for template_id in template_ids(kind)]


def write_template(template_id: str, path: str | Path) -> Path:
    """Write one template to an explicit user-chosen path.

    The path is never derived from template contents, and an existing file is
    never silently replaced: the caller must ask for an overwrite explicitly.
    """
    entry = _lookup(template_id)
    target = Path(path)
    if target.exists():
        raise InputError(f"template output already exists: {target}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            canonical_dumps(entry["document"]).replace("\n", "\n"),
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        raise InputError(f"template output could not be written: {exc}") from exc
    return target


def _lookup(template_id: str) -> dict[str, Any]:
    entry = _TEMPLATES.get(template_id) or _ROUTE_TEMPLATES.get(template_id)
    if entry is None:
        valid = ", ".join(template_ids())
        raise InputError(f"unknown template: {template_id} (valid templates: {valid})")
    return entry
