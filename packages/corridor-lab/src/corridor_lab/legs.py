"""Bounded multi-leg route composition.

A composed route declares an explicit chain of legs, each with its own currency
transition, fees, spread, and delay. Corridor Lab validates the chain against
the transaction's declared send and receive currencies and rejects cycles.

Dependency model
----------------
Failures across legs are **not** assumed independent and success probabilities
are **never** multiplied. A composed route declares joint outcomes: each outcome
names the leg at which the payment terminates (`terminal_leg`) together with its
own probability, additional delay, recovery amount, and recovery delay. The
probability of the declared outcomes is taken exactly as declared and must sum
to one, exactly as it must for a single-leg route.

Two explicit rules follow from that model:

- A success outcome must terminate at the final leg, because a composed route
  only completes when every leg completes.
- A failure outcome may terminate at any leg. Funds are assumed to return along
  the declared route, so its recovery amount is still declared in the send
  currency.

Timing
------
Time to a final state is the sum of the declared leg delays up to and including
the terminal leg, plus the outcome's own declared additional delay, plus the
recovery delay for a failure:

```text
leg_time(k) = sum(delay_hours of legs 1..k)
resolution  = leg_time(terminal_leg) + outcome.delay_hours
              + (recovery_delay_hours if the outcome is a failure)
```

Aggregation convention
----------------------
Leg fees are charged in each leg's `from_currency` and are deducted before that
leg converts. To express a single send-currency sender cost, each leg fee is
converted back using the declared effective rates of the preceding legs:

```text
e_i        = fx_rate_i * (1 - fx_spread_bps_i / 10000)
fee_send_i = fee_i / product(e_j for j < i)
recipient  = (S - sum(fee_send_i)) * product(e_j for all j)
```

That identity is exact for the declared chain, so `recipient_amount` computed
leg by leg equals the aggregated form. The conversion is a declared valuation
convention, not a market quote. Every leg fee is also reported partitioned in
its own currency, alongside the aggregate, so nothing is hidden by the
conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Any

from .canonical import (
    MAX_BPS,
    MAX_LEGS,
    InputError,
    decimal_text,
    local_decimal_context,
    require_decimal,
    require_identifier,
    require_keys,
    require_object,
    require_string,
)

LEG_CONTRACT_FIELDS = ("leg_id", "from_currency", "to_currency", "fx_rate", "fx_spread_bps", "fixed_fee_send", "percent_fee_bps", "delay_hours")


@dataclass(frozen=True)
class Leg:
    leg_id: str
    from_currency: str
    to_currency: str
    fx_rate: Decimal
    fx_spread_bps: Decimal
    fixed_fee_send: Decimal
    percent_fee_bps: Decimal
    delay_hours: Decimal

    @property
    def effective_rate(self) -> Decimal:
        """The declared rate after the declared spread."""
        with local_decimal_context():
            return self.fx_rate * (Decimal("1") - self.fx_spread_bps / MAX_BPS)


@dataclass(frozen=True)
class LegFee:
    leg_id: str
    currency: str
    fixed_fee: Decimal
    percentage_fee: Decimal
    total_fee: Decimal


@dataclass(frozen=True)
class CompositionPlan:
    """The result of walking a declared leg chain."""

    explicit_fee_send: Decimal
    amount_converted_send: Decimal
    effective_fx_rate: Decimal
    fx_spread_cost_receive: Decimal
    recipient_amount: Decimal
    leg_fees: tuple[LegFee, ...]
    terminal_delay_hours: dict[str, Decimal]


def parse_legs(value: Any, path: str) -> tuple[Leg, ...]:
    """Parse a declared leg chain and validate its internal continuity.

    The chain endpoints are checked against the transaction's declared send and
    receive currencies at evaluation time, because a route document is also
    valid on its own.
    """
    if not isinstance(value, list) or len(value) < 2:
        raise InputError(f"{path} must be an array of at least two legs")
    if len(value) > MAX_LEGS:
        raise InputError(f"{path} exceeds the {MAX_LEGS}-leg budget")
    legs: list[Leg] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(value):
        location = f"{path}[{index}]"
        item = require_object(raw, location)
        require_keys(item, set(LEG_CONTRACT_FIELDS), set(), location)
        leg_id = require_identifier(item["leg_id"], f"{location}.leg_id")
        if leg_id in identifiers:
            raise InputError(f"{path} has duplicate leg_id: {leg_id}")
        identifiers.add(leg_id)
        from_currency = require_identifier(item["from_currency"], f"{location}.from_currency", maximum=16)
        to_currency = require_identifier(item["to_currency"], f"{location}.to_currency", maximum=16)
        if from_currency == to_currency:
            raise InputError(f"{location} must convert between two different currencies")
        legs.append(
            Leg(
                leg_id=leg_id,
                from_currency=from_currency,
                to_currency=to_currency,
                fx_rate=require_decimal(item["fx_rate"], f"{location}.fx_rate", positive=True),
                fx_spread_bps=require_decimal(
                    item["fx_spread_bps"], f"{location}.fx_spread_bps", minimum=Decimal("0"), maximum=MAX_BPS
                ),
                fixed_fee_send=require_decimal(
                    item["fixed_fee_send"], f"{location}.fixed_fee_send", minimum=Decimal("0")
                ),
                percent_fee_bps=require_decimal(
                    item["percent_fee_bps"], f"{location}.percent_fee_bps", minimum=Decimal("0"), maximum=MAX_BPS
                ),
                delay_hours=require_decimal(item["delay_hours"], f"{location}.delay_hours", minimum=Decimal("0")),
            )
        )
    _validate_chain(legs, path)
    return tuple(legs)


def require_chain_endpoints(
    legs: tuple[Leg, ...], path: str, send_currency: str, receive_currency: str
) -> None:
    """Check a declared chain against the transaction's declared currencies."""
    if not legs:
        return
    if legs[0].from_currency != send_currency:
        raise InputError(f"{path}[0].from_currency must equal the declared send currency {send_currency}")
    if legs[-1].to_currency != receive_currency:
        raise InputError(f"{path}[-1].to_currency must equal the declared receive currency {receive_currency}")


def _validate_chain(legs: list[Leg], path: str) -> None:
    for index in range(1, len(legs)):
        if legs[index - 1].to_currency != legs[index].from_currency:
            raise InputError(
                f"{path}[{index}].from_currency must equal {path}[{index - 1}].to_currency to form a contiguous chain"
            )
    seen: list[str] = [legs[0].from_currency, *(leg.to_currency for leg in legs)]
    duplicates = sorted({item for item in seen if seen.count(item) > 1})
    if duplicates:
        raise InputError(
            f"{path} revisits {', '.join(duplicates)}; a declared chain must not contain a cycle"
        )


def terminal_leg_delays(legs: tuple[Leg, ...]) -> dict[str, Decimal]:
    """Cumulative declared delay up to and including each leg."""
    cumulative = Decimal("0")
    result: dict[str, Decimal] = {}
    with local_decimal_context():
        for leg in legs:
            cumulative += leg.delay_hours
            result[leg.leg_id] = cumulative
    return result


def compose(legs: tuple[Leg, ...], send_amount: Decimal) -> CompositionPlan:
    """Walk a declared leg chain and return the aggregated and partitioned results."""
    try:
        with local_decimal_context():
            amount = send_amount
            leg_fees: list[LegFee] = []
            explicit_fee_send = Decimal("0")
            effective_product = Decimal("1")
            reference_product = Decimal("1")
            for leg in legs:
                reference_product *= leg.fx_rate
                percentage_fee = amount * leg.percent_fee_bps / MAX_BPS
                total_fee = leg.fixed_fee_send + percentage_fee
                if total_fee > amount:
                    raise InputError(f"leg {leg.leg_id} fees exceed the amount reaching that leg")
                leg_fees.append(
                    LegFee(
                        leg_id=leg.leg_id,
                        currency=leg.from_currency,
                        fixed_fee=leg.fixed_fee_send,
                        percentage_fee=percentage_fee,
                        total_fee=total_fee,
                    )
                )
                explicit_fee_send += total_fee / effective_product
                amount = (amount - total_fee) * leg.fx_rate
                spread_cost = amount * leg.fx_spread_bps / MAX_BPS
                amount -= spread_cost
                effective_product *= leg.effective_rate
            amount_converted = send_amount - explicit_fee_send
            return CompositionPlan(
                explicit_fee_send=explicit_fee_send,
                amount_converted_send=amount_converted,
                effective_fx_rate=effective_product,
                fx_spread_cost_receive=amount_converted * reference_product - amount,
                recipient_amount=amount,
                leg_fees=tuple(leg_fees),
                terminal_delay_hours=terminal_leg_delays(legs),
            )
    except DecimalException as exc:
        raise InputError("route composition calculation failed") from exc


def declared_legs(legs: tuple[Leg, ...]) -> list[dict[str, object]]:
    return [
        {
            "leg_id": leg.leg_id,
            "from_currency": leg.from_currency,
            "to_currency": leg.to_currency,
            "fx_rate": decimal_text(leg.fx_rate),
            "fx_spread_bps": decimal_text(leg.fx_spread_bps),
            "fixed_fee_send": decimal_text(leg.fixed_fee_send),
            "percent_fee_bps": decimal_text(leg.percent_fee_bps),
            "delay_hours": decimal_text(leg.delay_hours),
        }
        for leg in legs
    ]


def require_terminal_leg(value: Any, path: str, known: set[str]) -> str:
    leg_id = require_string(value, path)
    if leg_id not in known:
        raise InputError(f"{path} must name a declared leg_id ({', '.join(sorted(known))})")
    return leg_id
