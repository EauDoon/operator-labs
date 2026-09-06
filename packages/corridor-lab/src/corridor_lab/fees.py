"""Declared tiered fee schedules and amortized period charges.

Every value in this module is author-declared. Nothing here estimates,
forecasts, or fetches a price.

Band convention
---------------
Tiers are ordered and contiguous. Tier ``i`` covers the half-open interval
``(lower_i, upper_i]`` where ``lower_0`` is zero and ``lower_i`` is the previous
tier's ``upper_bound_send``. An amount exactly equal to a tier's upper bound
therefore belongs to that tier, not the next one. The final tier carries a null
upper bound and covers everything above the previous bound.

Basis convention
----------------
``whole_band`` selects the single band containing the send amount and applies
that band's fixed fee and its percentage fee to the whole amount.

``marginal`` applies each band's percentage fee only to the portion of the send
amount that falls inside that band. The fixed fee is charged exactly once, using
the band that contains the full send amount. Fixed fees are never summed across
bands, so a marginal schedule can never charge more than one fixed fee per
transaction.

Period charges
--------------
A period charge is a cost that is not incurred per transaction. Corridor Lab
never reports it as a whole-period figure without also reporting the
per-transaction amortized figure, and the amortization denominator is always
explicitly declared:

``declared_transactions``
    Divide by the charge's own ``period_transactions``. The resulting
    per-transaction figure does not vary with the scenario volume.

``scenario_volume``
    Divide by the transaction volume in force (the scenario's
    ``volume_per_period``, or the active workload's ``transactions_per_period``).
    The resulting per-transaction figure does vary with volume.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Any

from .canonical import (
    MAX_BPS,
    MAX_FEE_TIERS,
    MAX_PERIOD_CHARGES,
    InputError,
    decimal_text,
    local_decimal_context,
    require_decimal,
    require_identifier,
    require_keys,
    require_object,
    require_string,
)

FEE_SCHEDULE_CONTRACT_VERSION = "corridor-lab.fee-schedule/v1"
FEE_BASES = ("marginal", "whole_band")
AMORTIZATION_MODES = ("declared_transactions", "scenario_volume")


@dataclass(frozen=True)
class FeeTier:
    upper_bound_send: Decimal | None
    fixed_fee_send: Decimal
    percent_fee_bps: Decimal


@dataclass(frozen=True)
class PeriodCharge:
    label: str
    amount_send: Decimal
    amortization_over: str
    period_transactions: Decimal | None

    def amortized(self, scenario_volume: Decimal) -> Decimal:
        """Return the per-transaction share of this period charge."""
        with local_decimal_context():
            if self.amortization_over == "declared_transactions":
                assert self.period_transactions is not None
                return self.amount_send / self.period_transactions
            return self.amount_send / scenario_volume


@dataclass(frozen=True)
class FeeSchedule:
    basis: str
    tiers: tuple[FeeTier, ...]
    period_charges: tuple[PeriodCharge, ...]

    def band_index(self, send_amount: Decimal) -> int:
        with local_decimal_context():
            for index, tier in enumerate(self.tiers):
                if tier.upper_bound_send is None or send_amount <= tier.upper_bound_send:
                    return index
        raise AssertionError("the final fee tier must have no upper bound")

    def transaction_fee(self, send_amount: Decimal) -> "FeeBreakdown":
        """Return the transaction-level fee for a declared send amount."""
        try:
            with local_decimal_context():
                index = self.band_index(send_amount)
                fixed = self.tiers[index].fixed_fee_send
                if self.basis == "whole_band":
                    percentage = send_amount * self.tiers[index].percent_fee_bps / MAX_BPS
                    return FeeBreakdown(fixed, percentage, fixed + percentage, index)
                percentage = Decimal("0")
                lower = Decimal("0")
                for tier in self.tiers:
                    if tier.upper_bound_send is None:
                        portion = send_amount - lower
                    else:
                        portion = min(send_amount, tier.upper_bound_send) - lower
                    if portion > 0:
                        percentage += portion * tier.percent_fee_bps / MAX_BPS
                    if tier.upper_bound_send is not None:
                        lower = tier.upper_bound_send
                return FeeBreakdown(fixed, percentage, fixed + percentage, index)
        except DecimalException as exc:
            raise InputError("fee schedule calculation failed") from exc

    def amortized_period_charges(self, scenario_volume: Decimal) -> Decimal:
        with local_decimal_context():
            return sum(
                (charge.amortized(scenario_volume) for charge in self.period_charges),
                Decimal("0"),
            )


@dataclass(frozen=True)
class FeeBreakdown:
    fixed_fee_send: Decimal
    percentage_fee_send: Decimal
    total_send: Decimal
    band_index: int


def parse_fee_schedule(value: Any, path: str) -> FeeSchedule:
    item = require_object(value, path)
    require_keys(item, {"basis", "tiers"}, {"period_charges"}, path)
    basis = require_string(item["basis"], f"{path}.basis")
    if basis not in FEE_BASES:
        raise InputError(f"{path}.basis must be one of {', '.join(FEE_BASES)}")
    return FeeSchedule(
        basis=basis,
        tiers=_parse_tiers(item["tiers"], f"{path}.tiers"),
        period_charges=_parse_period_charges(item.get("period_charges", []), f"{path}.period_charges"),
    )


def _parse_tiers(value: Any, path: str) -> tuple[FeeTier, ...]:
    if not isinstance(value, list) or not value:
        raise InputError(f"{path} must be a non-empty array")
    if len(value) > MAX_FEE_TIERS:
        raise InputError(f"{path} exceeds the {MAX_FEE_TIERS}-tier budget")
    parsed: list[FeeTier] = []
    previous: Decimal | None = None
    for index, raw in enumerate(value):
        location = f"{path}[{index}]"
        item = require_object(raw, location)
        require_keys(item, {"upper_bound_send", "fixed_fee_send", "percent_fee_bps"}, set(), location)
        is_last = index == len(value) - 1
        upper: Decimal | None = None
        if item["upper_bound_send"] is None:
            if not is_last:
                raise InputError(f"{location}.upper_bound_send may be null only on the final tier")
        else:
            upper = require_decimal(
                item["upper_bound_send"], f"{location}.upper_bound_send", positive=True
            )
            if previous is not None and upper <= previous:
                raise InputError(f"{location}.upper_bound_send must be greater than the previous tier bound")
        previous = upper
        parsed.append(
            FeeTier(
                upper_bound_send=upper,
                fixed_fee_send=require_decimal(
                    item["fixed_fee_send"], f"{location}.fixed_fee_send", minimum=Decimal("0")
                ),
                percent_fee_bps=require_decimal(
                    item["percent_fee_bps"],
                    f"{location}.percent_fee_bps",
                    minimum=Decimal("0"),
                    maximum=MAX_BPS,
                ),
            )
        )
    if len(parsed) == 1 and parsed[0].upper_bound_send is None:
        return tuple(parsed)
    return tuple(parsed)


def _parse_period_charges(value: Any, path: str) -> tuple[PeriodCharge, ...]:
    if not isinstance(value, list):
        raise InputError(f"{path} must be an array")
    if len(value) > MAX_PERIOD_CHARGES:
        raise InputError(f"{path} exceeds the {MAX_PERIOD_CHARGES}-charge budget")
    parsed: list[PeriodCharge] = []
    labels: set[str] = set()
    for index, raw in enumerate(value):
        location = f"{path}[{index}]"
        item = require_object(raw, location)
        require_keys(item, {"label", "amount_send", "amortization_over"}, {"period_transactions"}, location)
        label = require_identifier(item["label"], f"{location}.label")
        if label in labels:
            raise InputError(f"{path} has duplicate label: {label}")
        labels.add(label)
        mode = require_string(item["amortization_over"], f"{location}.amortization_over")
        if mode not in AMORTIZATION_MODES:
            raise InputError(f"{location}.amortization_over must be one of {', '.join(AMORTIZATION_MODES)}")
        period_transactions: Decimal | None = None
        if mode == "declared_transactions":
            if "period_transactions" not in item:
                raise InputError(f"{location}.period_transactions is required when amortization_over is declared_transactions")
            period_transactions = require_decimal(
                item["period_transactions"], f"{location}.period_transactions", positive=True
            )
        elif "period_transactions" in item:
            raise InputError(f"{location}.period_transactions is not used when amortization_over is scenario_volume")
        parsed.append(
            PeriodCharge(
                label=label,
                amount_send=require_decimal(item["amount_send"], f"{location}.amount_send", minimum=Decimal("0")),
                amortization_over=mode,
                period_transactions=period_transactions,
            )
        )
    return tuple(parsed)


def declared_fee_schedule(schedule: FeeSchedule) -> dict[str, object]:
    return {
        "basis": schedule.basis,
        "tiers": [
            {
                "upper_bound_send": None if tier.upper_bound_send is None else decimal_text(tier.upper_bound_send),
                "fixed_fee_send": decimal_text(tier.fixed_fee_send),
                "percent_fee_bps": decimal_text(tier.percent_fee_bps),
            }
            for tier in schedule.tiers
        ],
        "period_charges": [
            {
                "label": charge.label,
                "amount_send": decimal_text(charge.amount_send),
                "amortization_over": charge.amortization_over,
                **(
                    {"period_transactions": decimal_text(charge.period_transactions)}
                    if charge.period_transactions is not None
                    else {}
                ),
            }
            for charge in schedule.period_charges
        ],
    }
