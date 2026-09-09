import unittest
from decimal import Decimal
from helpers import route, scenario
from corridor_lab.scenario import parse_scenario
from corridor_lab.transaction_sweep import run_transaction_sweep
from corridor_lab.canonical import InputError
from corridor_lab.report import render_report


class TransactionSweepTests(unittest.TestCase):
    def test_deadline_boundary_and_unchanged_input(self):
        original = parse_scenario(scenario([route()]))
        report = run_transaction_sweep(original, "deadline_hours", [Decimal("1.99"), Decimal("2")])
        self.assertEqual([r["probability_by_deadline"] for r in report["rows"]], ["0", "0.8"])
        self.assertEqual(original.transaction.deadline_hours, Decimal("3"))
        for format in ("json", "csv", "markdown"):
            self.assertIn("deadline_hours", render_report(report, format))

    def test_volume_reduces_carry_cost(self):
        rows = run_transaction_sweep(parse_scenario(scenario([route()])), "volume_per_period", [Decimal("1"), Decimal("100")])["rows"]
        self.assertGreater(Decimal(rows[0]["expected_sender_cost"]), Decimal(rows[1]["expected_sender_cost"]))

    def test_rejects_invalid_or_unbounded_values(self):
        source = parse_scenario(scenario([route()]))
        for parameter, values in [("send_amount", [Decimal("0")]), ("deadline_hours", [Decimal("-1")]), ("fx_rate", [Decimal("1")]), ("send_amount", []), ("send_amount", [Decimal("NaN")])]:
            with self.subTest(parameter=parameter, values=values), self.assertRaises(InputError):
                run_transaction_sweep(source, parameter, values)
