"""Transparent Decimal-only calculation model for a single route."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException

from .canonical import (
    BPS_DENOMINATOR,
    DAYS_PER_YEAR,
    InputError,
    decimal_text,
    local_decimal_context,
    money_text,
    require_decimal,
)
from .legs import compose, require_chain_endpoints
from .route import Route
from .scenario import Transaction


@dataclass(frozen=True)
class RouteEvaluation:
    route: Route
    transaction: Transaction
    explicit_fee_send: Decimal
    explicit_fee_transaction_send: Decimal
    explicit_fee_period_amortized_send: Decimal
    percentage_fee_send: Decimal
    amount_converted_send: Decimal
    effective_fx_rate: Decimal
    fx_spread_cost_receive: Decimal
    recipient_amount: Decimal
    success_probability: Decimal
    probability_by_deadline: Decimal
    expected_recipient_amount: Decimal
    liquidity_carry_numerator_send: Decimal
    liquidity_carry_cost_send: Decimal
    expected_failure_recovery_cost_send: Decimal
    expected_recovery_amount_send: Decimal
    expected_sender_cost: Decimal
    expected_completion_time_hours: Decimal
    median_completion_time_hours: Decimal
    tail_completion_time_hours: Decimal

    @property
    def fixed_expected_cost_send(self) -> Decimal:
        """Costs independent of the stated transaction volume.

        A period charge amortized over ``scenario_volume`` is volume dependent by
        declaration and is therefore excluded here so that the documented
        break-even equation stays valid.
        """
        with local_decimal_context():
            volume_independent_fees = self.explicit_fee_send - self.volume_dependent_fee_send
            return volume_independent_fees + self.expected_failure_recovery_cost_send

    @property
    def volume_dependent_fee_send(self) -> Decimal:
        """The part of the explicit fee that moves with the transaction volume."""
        if self.route.fee_schedule is None:
            return Decimal("0")
        with local_decimal_context():
            return sum(
                (
                    charge.amortized(self.transaction.volume_per_period)
                    for charge in self.route.fee_schedule.period_charges
                    if charge.amortization_over == "scenario_volume"
                ),
                Decimal("0"),
            )

    @property
    def fee_basis(self) -> str:
        if self.route.is_composed:
            return "composed"
        schedule = self.route.fee_schedule
        if schedule is None:
            return "flat"
        return schedule.basis

    def as_dict(self) -> dict[str, object]:
        tx = self.transaction
        return {
            "route_id": self.route.route_id,
            "label": self.route.label,
            "currency": {"send": tx.send_currency, "receive": tx.receive_currency},
            "recipient_amount": money_text(self.recipient_amount, tx.receive_precision, tx.rounding),
            "expected_recipient_amount": money_text(self.expected_recipient_amount, tx.receive_precision, tx.rounding),
            "explicit_fee_send": money_text(self.explicit_fee_send, tx.send_precision, tx.rounding),
            "explicit_fee_transaction_send": money_text(
                self.explicit_fee_transaction_send, tx.send_precision, tx.rounding
            ),
            "explicit_fee_period_amortized_send": money_text(
                self.explicit_fee_period_amortized_send, tx.send_precision, tx.rounding
            ),
            "fee_basis": self.fee_basis,
            "percentage_fee_send": money_text(self.percentage_fee_send, tx.send_precision, tx.rounding),
            "amount_converted_send": money_text(self.amount_converted_send, tx.send_precision, tx.rounding),
            "effective_fx_rate": decimal_text(self.effective_fx_rate),
            "fx_spread_cost_receive": money_text(self.fx_spread_cost_receive, tx.receive_precision, tx.rounding),
            "liquidity_carry_cost_send": money_text(self.liquidity_carry_cost_send, tx.send_precision, tx.rounding),
            "expected_failure_recovery_cost_send": money_text(
                self.expected_failure_recovery_cost_send, tx.send_precision, tx.rounding
            ),
            "expected_recovery_amount_send": money_text(
                self.expected_recovery_amount_send, tx.send_precision, tx.rounding
            ),
            "expected_sender_cost": money_text(self.expected_sender_cost, tx.send_precision, tx.rounding),
            "success_probability": decimal_text(self.success_probability),
            "probability_by_deadline": decimal_text(self.probability_by_deadline),
            "probability_by_deadline_definition": "successful completion by declared deadline",
            "expected_completion_time_hours": decimal_text(self.expected_completion_time_hours),
            "median_completion_time_hours": decimal_text(self.median_completion_time_hours),
            "tail_completion_time_hours": decimal_text(self.tail_completion_time_hours),
        }


def _quantile_time(route: Route, threshold: Decimal) -> Decimal:
    with local_decimal_context():
        cumulative = Decimal("0")
        ordered = sorted(
            route.outcomes,
            key=lambda outcome: (route.outcome_resolution_hours(outcome), outcome.outcome_id),
        )
        for outcome in ordered:
            cumulative += outcome.probability
            if cumulative >= threshold:
                return route.outcome_resolution_hours(outcome)
    raise AssertionError("validated probabilities must cover every quantile")


def _fee_components(
    route: Route, send_amount: Decimal, volume: Decimal
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return (fixed, percentage, transaction fee, amortized period charge)."""
    with local_decimal_context():
        if route.fee_schedule is not None:
            breakdown = route.fee_schedule.transaction_fee(send_amount)
            period_amortized = route.fee_schedule.amortized_period_charges(volume)
            return (
                breakdown.fixed_fee_send,
                breakdown.percentage_fee_send,
                breakdown.total_send,
                period_amortized,
            )
        percentage_fee = send_amount * route.percent_fee_bps / BPS_DENOMINATOR
        return route.fixed_fee_send, percentage_fee, route.fixed_fee_send + percentage_fee, Decimal("0")


def evaluate_route(route: Route, transaction: Transaction) -> RouteEvaluation:
    """Evaluate a declared route using only declared assumptions.

    The reported recipient amount is conditional on successful completion.
    Expected recipient amount assigns zero recipient value to failure outcomes.
    Failure and recovery cost is the principal not returned in a failure state;
    it deliberately excludes already separately reported explicit fees.
    """
    return _evaluate(route, transaction, transaction.volume_per_period)


def evaluate_route_at_volume(
    route: Route, transaction: Transaction, volume_per_period: Decimal
) -> RouteEvaluation:
    """Evaluate a route under an explicitly supplied declared volume."""
    parsed = require_decimal(volume_per_period, "volume_per_period", positive=True)
    return _evaluate(route, transaction, parsed)


def _evaluate(route: Route, transaction: Transaction, volume: Decimal) -> RouteEvaluation:
    try:
        with local_decimal_context():
            if route.is_composed:
                require_chain_endpoints(
                    route.legs,
                    f"route {route.route_id}.legs",
                    transaction.send_currency,
                    transaction.receive_currency,
                )
                plan = compose(route.legs, transaction.send_amount)
                fixed_fee = Decimal("0")
                percentage_fee = Decimal("0")
                transaction_fee = plan.explicit_fee_send
                period_amortized = Decimal("0")
                explicit_fee = plan.explicit_fee_send
                amount_converted = plan.amount_converted_send
                fx_spread_cost = plan.fx_spread_cost_receive
                recipient_amount = plan.recipient_amount
                effective_fx_rate = plan.effective_fx_rate
                if explicit_fee > transaction.send_amount:
                    raise InputError(f"route {route.route_id} fees exceed the send amount")
            else:
                fixed_fee, percentage_fee, transaction_fee, period_amortized = _fee_components(
                    route, transaction.send_amount, volume
                )
                explicit_fee = transaction_fee + period_amortized
                if explicit_fee > transaction.send_amount:
                    raise InputError(f"route {route.route_id} fees exceed the send amount")
                amount_converted = transaction.send_amount - explicit_fee
                gross_recipient = amount_converted * route.fx_rate
                fx_spread_cost = gross_recipient * route.fx_spread_bps / BPS_DENOMINATOR
                recipient_amount = gross_recipient - fx_spread_cost
                effective_fx_rate = route.fx_rate * (Decimal("1") - route.fx_spread_bps / BPS_DENOMINATOR)

            success_probability = sum(
                (outcome.probability for outcome in route.outcomes if outcome.completion == "success"), Decimal("0")
            )
            probability_by_deadline = sum(
                (
                    outcome.probability
                    for outcome in route.outcomes
                    if outcome.completion == "success"
                    and route.outcome_resolution_hours(outcome) <= transaction.deadline_hours
                ),
                Decimal("0"),
            )
            for outcome in route.outcomes:
                if outcome.recovery_amount_send > transaction.send_amount:
                    raise InputError(f"route {route.route_id} outcome {outcome.outcome_id} recovers more than the send amount")
            expected_failure_cost = sum(
                (
                    outcome.probability * (transaction.send_amount - outcome.recovery_amount_send)
                    for outcome in route.outcomes
                    if outcome.completion == "failure"
                ),
                Decimal("0"),
            )
            expected_recovery = sum(
                (
                    outcome.probability * outcome.recovery_amount_send
                    for outcome in route.outcomes
                    if outcome.completion == "failure"
                ),
                Decimal("0"),
            )
            liquidity_numerator = (
                route.liquidity.prefunding_amount_send
                * route.liquidity.annual_cost_of_capital_bps
                / BPS_DENOMINATOR
                * route.liquidity.holding_days
                / DAYS_PER_YEAR
            )
            liquidity_carry = liquidity_numerator / volume
            expected_time = sum(
                (outcome.probability * route.outcome_resolution_hours(outcome) for outcome in route.outcomes),
                Decimal("0"),
            )
            return RouteEvaluation(
                route=route,
                transaction=transaction,
                explicit_fee_send=explicit_fee,
                explicit_fee_transaction_send=transaction_fee,
                explicit_fee_period_amortized_send=period_amortized,
                percentage_fee_send=percentage_fee,
                amount_converted_send=amount_converted,
                effective_fx_rate=effective_fx_rate,
                fx_spread_cost_receive=fx_spread_cost,
                recipient_amount=recipient_amount,
                success_probability=success_probability,
                probability_by_deadline=probability_by_deadline,
                expected_recipient_amount=recipient_amount * success_probability,
                liquidity_carry_numerator_send=liquidity_numerator,
                liquidity_carry_cost_send=liquidity_carry,
                expected_failure_recovery_cost_send=expected_failure_cost,
                expected_recovery_amount_send=expected_recovery,
                expected_sender_cost=explicit_fee + liquidity_carry + expected_failure_cost,
                expected_completion_time_hours=expected_time,
                median_completion_time_hours=_quantile_time(route, Decimal("0.5")),
                tail_completion_time_hours=_quantile_time(route, Decimal("0.95")),
            )
    except DecimalException as exc:
        raise InputError("decimal calculation failed") from exc
