"""Transparent Decimal-only calculation model for a single route."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException

from .canonical import InputError, decimal_text, local_decimal_context
from .route import Route
from .scenario import Transaction

BPS_DENOMINATOR = Decimal(10000)
DAYS_PER_YEAR = Decimal(365)


@dataclass(frozen=True)
class RouteEvaluation:
    route: Route
    transaction: Transaction
    explicit_fee_send: Decimal
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
        """Costs independent of the stated transaction volume."""
        with local_decimal_context():
            return self.explicit_fee_send + self.expected_failure_recovery_cost_send

    def as_dict(self) -> dict[str, object]:
        tx = self.transaction
        return {
            "route_id": self.route.route_id,
            "label": self.route.label,
            "currency": {"send": tx.send_currency, "receive": tx.receive_currency},
            "recipient_amount": money_text(self.recipient_amount, tx.receive_precision, tx.rounding),
            "expected_recipient_amount": money_text(self.expected_recipient_amount, tx.receive_precision, tx.rounding),
            "explicit_fee_send": money_text(self.explicit_fee_send, tx.send_precision, tx.rounding),
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


def money_text(value: Decimal, precision: int, rounding: str) -> str:
    try:
        with local_decimal_context():
            quantizer = Decimal(1).scaleb(-precision)
            quantized = value.quantize(quantizer, rounding=rounding)
            return format(quantized, f".{precision}f")
    except DecimalException as exc:
        raise InputError("cannot render decimal amount") from exc


def _quantile_time(route: Route, threshold: Decimal) -> Decimal:
    with local_decimal_context():
        cumulative = Decimal(0)
        ordered = sorted(route.outcomes, key=lambda outcome: (outcome.resolution_hours, outcome.outcome_id))
        for outcome in ordered:
            cumulative += outcome.probability
            if cumulative >= threshold:
                return outcome.resolution_hours
    raise AssertionError("validated probabilities must cover every quantile")


def evaluate_route(route: Route, transaction: Transaction) -> RouteEvaluation:
    """Evaluate a declared route using only declared assumptions.

    The reported recipient amount is conditional on successful completion.
    Expected recipient amount assigns zero recipient value to failure outcomes.
    Failure and recovery cost is the principal not returned in a failure state;
    it deliberately excludes already separately reported explicit fees.
    """
    try:
        with local_decimal_context():
            percentage_fee = transaction.send_amount * route.percent_fee_bps / BPS_DENOMINATOR
            explicit_fee = route.fixed_fee_send + percentage_fee
            if explicit_fee > transaction.send_amount:
                raise InputError(f"route {route.route_id} fees exceed the send amount")
            amount_converted = transaction.send_amount - explicit_fee
            gross_recipient = amount_converted * route.fx_rate
            fx_spread_cost = gross_recipient * route.fx_spread_bps / BPS_DENOMINATOR
            recipient_amount = gross_recipient - fx_spread_cost
            effective_fx_rate = route.fx_rate * (Decimal(1) - route.fx_spread_bps / BPS_DENOMINATOR)

            success_probability = sum(
                (outcome.probability for outcome in route.outcomes if outcome.completion == "success"), Decimal(0)
            )
            probability_by_deadline = sum(
                (
                    outcome.probability
                    for outcome in route.outcomes
                    if outcome.completion == "success" and outcome.delay_hours <= transaction.deadline_hours
                ),
                Decimal(0),
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
                Decimal(0),
            )
            expected_recovery = sum(
                (
                    outcome.probability * outcome.recovery_amount_send
                    for outcome in route.outcomes
                    if outcome.completion == "failure"
                ),
                Decimal(0),
            )
            liquidity_numerator = (
                route.liquidity.prefunding_amount_send
                * route.liquidity.annual_cost_of_capital_bps
                / BPS_DENOMINATOR
                * route.liquidity.holding_days
                / DAYS_PER_YEAR
            )
            liquidity_carry = liquidity_numerator / transaction.volume_per_period
            expected_time = sum(
                (outcome.probability * outcome.resolution_hours for outcome in route.outcomes), Decimal(0)
            )
            return RouteEvaluation(
                route=route,
                transaction=transaction,
                explicit_fee_send=explicit_fee,
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
