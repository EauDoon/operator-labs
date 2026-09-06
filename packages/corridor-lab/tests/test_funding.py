"""Hand-worked tests for declared multi-period funding and liquidity."""

import copy
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import fee_helpers as fh  # noqa: E402
from corridor_lab.canonical import InputError  # noqa: E402
from corridor_lab.funding import analyse_funding, parse_funding, run_funding  # noqa: E402
from corridor_lab.report import render_report  # noqa: E402
from corridor_lab.scenario import parse_scenario  # noqa: E402

# The documented schedule, hand-checked in examples/fictional-funding/README.md:
#   opening balance 1000, 30-day periods, settlement delay 1, recovery delay 0
#   period 1: disburse 1000, recover    0
#   period 2: disburse 1000, recover 1000
#   period 3: disburse 1000, recover 1000
SCHEDULE = {
    "opening_balance_send": "1000.00",
    "days_per_period": "30",
    "settlement_delay_periods": 1,
    "recovery_delay_periods": 0,
    "periods": [
        {"period_index": 1, "disbursements_send": "1000.00", "recoveries_send": "0"},
        {"period_index": 2, "disbursements_send": "1000.00", "recoveries_send": "1000.00"},
        {"period_index": 3, "disbursements_send": "1000.00", "recoveries_send": "1000.00"},
    ],
}


def _funding_scenario(routes=None, funding=None):
    data = fh.v2_scenario(
        routes if routes is not None else [_route("cheap", "600", "0.01"), _route("dear", "1000", "0.02")],
    )
    data["funding"] = SCHEDULE if funding is None else funding
    return parse_scenario(data)


def _route(route_id: str, annual_bps: str, failure_probability: str) -> dict:
    route = fh.tiered_route(route_id)
    route.pop("fee_schedule")
    route["fixed_fee_send"] = "6.00"
    route["percent_fee_bps"] = "20"
    route["liquidity"] = {
        "prefunding_amount_send": "20000",
        "annual_cost_of_capital_bps": annual_bps,
        "holding_days": "0.5",
    }
    route["outcomes"] = [
        {
            "outcome_id": "success",
            "probability": str(Decimal("1") - Decimal(failure_probability)),
            "completion": "success",
            "delay_hours": "2",
            "recovery_amount_send": "0",
            "recovery_delay_hours": "0",
        },
        {
            "outcome_id": "failed-recovered",
            "probability": failure_probability,
            "completion": "failure",
            "delay_hours": "3",
            "recovery_amount_send": "950",
            "recovery_delay_hours": "24",
        },
    ]
    return route


class FundingParsingTests(unittest.TestCase):
    def test_rejects_unknown_fields(self):
        data = copy.deepcopy(SCHEDULE)
        data["guess"] = 1
        with self.assertRaisesRegex(InputError, "unsupported field"):
            parse_funding(data)

    def test_requires_periods_and_days(self):
        for field in ("periods", "days_per_period", "opening_balance_send"):
            data = copy.deepcopy(SCHEDULE)
            data.pop(field)
            with self.assertRaisesRegex(InputError, "missing required field"):
                parse_funding(data)

    def test_rejects_empty_periods(self):
        data = copy.deepcopy(SCHEDULE)
        data["periods"] = []
        with self.assertRaisesRegex(InputError, "non-empty array"):
            parse_funding(data)

    def test_rejects_non_increasing_period_index(self):
        data = copy.deepcopy(SCHEDULE)
        data["periods"][2]["period_index"] = 2
        with self.assertRaisesRegex(InputError, "must increase"):
            parse_funding(data)

    def test_rejects_negative_amounts_and_non_positive_days(self):
        data = copy.deepcopy(SCHEDULE)
        data["periods"][0]["disbursements_send"] = "-1"
        with self.assertRaises(InputError):
            parse_funding(data)
        other = copy.deepcopy(SCHEDULE)
        other["days_per_period"] = "0"
        with self.assertRaises(InputError):
            parse_funding(other)

    def test_rejects_out_of_range_delays(self):
        data = copy.deepcopy(SCHEDULE)
        data["recovery_delay_periods"] = 65
        with self.assertRaises(InputError):
            parse_funding(data)

    def test_v1_scenario_rejects_a_funding_block(self):
        data = fh.v2_scenario([_route("a", "600", "0.01")])
        data["contract_version"] = "corridor-lab.scenario/v1"
        data["funding"] = SCHEDULE
        with self.assertRaisesRegex(InputError, "unsupported field"):
            parse_scenario(data)


class FundingCalculationTests(unittest.TestCase):
    def _analyse(self, delay: int | None = None, annual_bps: str = "1000", loss_rate: str = "0.001"):
        return analyse_funding(
            parse_funding(SCHEDULE),
            annual_cost_of_capital_bps=Decimal(annual_bps),
            loss_rate=Decimal(loss_rate),
            recovery_delay_periods=delay,
        )

    def test_hand_calculated_prefunding_and_shortfall_at_zero_delay(self):
        # balance start: 1000, 0, 0 ; trough: 0, -1000, -1000
        # needed: 1000, 2000, 2000  -> required prefunding 2000
        analysis = self._analyse(0)
        self.assertEqual(analysis.required_prefunding_send, Decimal("2000"))
        self.assertEqual(analysis.declared_opening_balance_send, Decimal("1000"))
        self.assertEqual(analysis.shortfall_send, Decimal("1000"))
        self.assertEqual(analysis.shortfall_periods, (2, 3))

    def test_hand_calculated_period_rows_at_zero_delay(self):
        analysis = self._analyse(0)
        rows = {row.period_index: row for row in analysis.periods}
        self.assertEqual(rows[1].balance_start_send, Decimal("1000"))
        self.assertEqual(rows[1].trough_send, Decimal("0"))
        self.assertEqual(rows[2].balance_start_send, Decimal("0"))
        self.assertEqual(rows[2].trough_send, Decimal("-1000"))
        self.assertEqual(rows[2].recoveries_declared_send, Decimal("1000"))
        self.assertEqual(rows[2].recoveries_arriving_send, Decimal("1000"))
        self.assertEqual(rows[1].unsettled_exposure_send, Decimal("1000"))

    def test_recovery_delay_raises_the_required_prefunding(self):
        # With a one-period delay, period 3 sees no recovery yet:
        # balance start 1000, 0, -1000 ; needed 1000, 2000, 3000.
        analysis = self._analyse(1)
        self.assertEqual(analysis.required_prefunding_send, Decimal("3000"))
        self.assertEqual(analysis.shortfall_send, Decimal("2000"))
        self.assertEqual(analysis.recoveries_after_horizon_send, Decimal("1000"))

    def test_no_delay_defers_nothing_beyond_the_horizon(self):
        self.assertEqual(self._analyse(0).recoveries_after_horizon_send, Decimal("0"))

    def test_delay_never_lowers_the_required_prefunding(self):
        results = [self._analyse(delay) for delay in (0, 1, 2)]
        values = [result.required_prefunding_send for result in results]
        self.assertEqual(values, sorted(values))

    def test_average_tied_up_capital_is_a_holding_statistic(self):
        # max(0, balance start) = 1000, 0, 0 -> mean 333.33...
        analysis = self._analyse(0)
        self.assertAlmostEqual(analysis.average_tied_up_capital_send, Decimal("1000") / Decimal("3"), places=20)

    def test_carrying_cost_scales_with_the_declared_capital_cost(self):
        # tied-up total 1000 * bps/10000 * 30/365
        cheap = self._analyse(0, annual_bps="600")
        dear = self._analyse(0, annual_bps="1000")
        places = 20
        self.assertAlmostEqual(
            cheap.carrying_cost_send,
            Decimal("1000") * Decimal("0.06") * Decimal("30") / Decimal("365"),
            places=places,
        )
        self.assertAlmostEqual(
            dear.carrying_cost_send,
            Decimal("1000") * Decimal("0.1") * Decimal("30") / Decimal("365"),
            places=places,
        )
        self.assertLess(cheap.carrying_cost_send, dear.carrying_cost_send)

    def test_expected_loss_is_scalar_applied_to_declared_disbursements(self):
        # 0.001 * 3000 = 3.00
        self.assertEqual(self._analyse(0, loss_rate="0.001").expected_loss_send, Decimal("3"))

    def test_loss_is_never_reported_as_tied_up_capital(self):
        analysis = self._analyse(0)
        self.assertNotEqual(analysis.expected_loss_send, analysis.average_tied_up_capital_send)

    def test_required_prefunding_ignores_the_declared_opening_balance(self):
        rich = copy.deepcopy(SCHEDULE)
        rich["opening_balance_send"] = "99999"
        first = analyse_funding(parse_funding(SCHEDULE), annual_cost_of_capital_bps=Decimal("1000"), loss_rate=Decimal("0"))
        second = analyse_funding(parse_funding(rich), annual_cost_of_capital_bps=Decimal("1000"), loss_rate=Decimal("0"))
        self.assertEqual(first.required_prefunding_send, second.required_prefunding_send)
        self.assertEqual(second.shortfall_send, Decimal("0"))
        self.assertEqual(second.shortfall_periods, ())

    def test_zero_disbursement_schedule_needs_no_prefunding(self):
        data = copy.deepcopy(SCHEDULE)
        for period in data["periods"]:
            period["disbursements_send"] = "0"
        analysis = analyse_funding(parse_funding(data), annual_cost_of_capital_bps=Decimal("1000"), loss_rate=Decimal("0"))
        self.assertEqual(analysis.required_prefunding_send, Decimal("0"))
        self.assertEqual(analysis.shortfall_periods, ())


class FundingReportTests(unittest.TestCase):
    def test_rows_cover_every_route_and_delay(self):
        report = run_funding(_funding_scenario(), [0, 1])
        self.assertEqual(len(report["rows"]), 4)
        self.assertEqual([row["recovery_delay_periods"] for row in report["rows"]], ["0", "1", "0", "1"])

    def test_hand_calculated_report_values(self):
        report = run_funding(_funding_scenario(), [0, 1])
        rows = {(row["route_id"], row["recovery_delay_periods"]): row for row in report["rows"]}
        self.assertEqual(rows[("cheap", "0")]["required_prefunding_send"], "2000.00")
        self.assertEqual(rows[("cheap", "0")]["carrying_cost_send"], "4.93")
        self.assertEqual(rows[("cheap", "0")]["expected_loss_send"], "1.50")
        self.assertEqual(rows[("dear", "0")]["carrying_cost_send"], "8.22")
        self.assertEqual(rows[("dear", "0")]["expected_loss_send"], "3.00")
        self.assertEqual(rows[("dear", "1")]["recoveries_after_horizon_send"], "1000.00")

    def test_requires_a_declared_schedule(self):
        scenario = _funding_scenario()
        scenario = parse_scenario(fh.v2_scenario([_route("cheap", "600", "0.01")]))
        with self.assertRaisesRegex(InputError, "declares no funding schedule"):
            run_funding(scenario)

    def test_rejects_non_integer_delays(self):
        with self.assertRaises(InputError):
            run_funding(_funding_scenario(), [1.5])

    def test_rejects_negative_delays(self):
        with self.assertRaisesRegex(InputError, "funding delay"):
            run_funding(_funding_scenario(), [-1])

    def test_too_many_delays_is_bounded(self):
        with self.assertRaisesRegex(InputError, "16-value budget"):
            run_funding(_funding_scenario(), list(range(20)))

    def test_rejects_routes_absent_scenario(self):
        scenario = _funding_scenario(routes=[])
        with self.assertRaisesRegex(InputError, "routes embedded in the scenario"):
            run_funding(scenario)

    def test_all_three_formats_render(self):
        report = run_funding(_funding_scenario(), [0, 1])
        self.assertIn('"report_version":"corridor-lab.funding/v1"', render_report(report, "json"))
        csv_text = render_report(report, "csv")
        self.assertIn("required_prefunding_send", csv_text)
        markdown = render_report(report, "markdown")
        self.assertIn("## How to read this funding report", markdown)
        self.assertIn("### Declared period detail", markdown)
        self.assertIn("Loss is not capital tied up", markdown)

    def test_report_is_deterministic(self):
        scenario = _funding_scenario()
        self.assertEqual(
            render_report(run_funding(scenario, [0, 1]), "json"),
            render_report(run_funding(scenario, [0, 1]), "json"),
        )

    def test_default_delay_uses_the_declared_schedule_value(self):
        report = run_funding(_funding_scenario())
        self.assertEqual(report["delays"], ["0"])


if __name__ == "__main__":
    unittest.main()
