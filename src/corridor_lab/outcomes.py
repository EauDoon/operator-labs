"""Finite outcome-state model used by Corridor Lab routes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .canonical import local_decimal_context


@dataclass(frozen=True)
class Outcome:
    outcome_id: str
    probability: Decimal
    completion: str
    delay_hours: Decimal
    recovery_amount_send: Decimal
    recovery_delay_hours: Decimal

    @property
    def resolution_hours(self) -> Decimal:
        """Time to a final success or completed recovery state."""
        if self.completion == "failure":
            with local_decimal_context():
                return self.delay_hours + self.recovery_delay_hours
        return self.delay_hours
