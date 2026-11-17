import unittest
from decimal import Decimal

from corridor_lab.canonical import InputError
from corridor_lab.report import render_report
from corridor_lab.scenario import parse_scenario
from corridor_lab.transaction_sweep import run_transaction_grid, run_transaction_sweep
from helpers import route, scenario


class TransactionSweepTests(unittest.TestCase):
    def test_guardrails_follow_each_tested_deadline(self):
        objective = {"metric": "maximize_expected_recipient_amount",
                     "guardrails": {"minimum_probability_by_deadline": "0.5"}}
        original = parse_scenario(scenario([route()], objective))
        report = run_transaction_sweep(original, "deadline_hours", [Decimal("1.99"), Decimal(2)])
        self.assertEqual([row["guardrails_pass"] for row in report["rows"]], [False, True])
        self.assertEqual([row["failed_guardrails"] for row in report["rows"]],
                         [["minimum_probability_by_deadline"], []])
        for format in ("json", "csv", "markdown"):
            self.assertIn("guardrails_pass", render_report(report, format))

    def test_absent_objective_is_unknown_not_a_pass(self):
        original = parse_scenario(scenario([route()]))
        row = run_transaction_sweep(original, "deadline_hours", [Decimal(2)])["rows"][0]
        self.assertIsNone(row["guardrails_pass"])
        self.assertIsNone(row["failed_guardrails"])
        self.assertIn("unknown", render_report({"report_version": "corridor-lab.transaction-sweep/v1", "rows": [row]}, "markdown"))

    def test_sweep_and_grid_guardrail_results_agree(self):
        objective = {"metric": "maximize_expected_recipient_amount",
                     "guardrails": {"minimum_probability_by_deadline": "0.5", "maximum_tail_hours": "4"}}
        original = parse_scenario(scenario([route()], objective))
        values = [Decimal(1), Decimal(2)]
        sweep = run_transaction_sweep(original, "deadline_hours", values)
        grid = run_transaction_grid(original, "deadline_hours", values, "volume_per_period", [Decimal(100)])
        self.assertEqual([r["guardrails_pass"] for r in sweep["rows"]], [r["guardrails_pass"] for r in grid["rows"]])
        self.assertEqual(sweep["rows"][0]["failed_guardrails"], ["minimum_probability_by_deadline", "maximum_tail_hours"])
        self.assertEqual(sweep["rows"][1]["failed_guardrails"], ["maximum_tail_hours"])

    def test_older_sweep_reports_still_render_with_unknown_guardrails(self):
        report = run_transaction_sweep(parse_scenario(scenario([route()])), "deadline_hours", [Decimal(2)])
        del report["rows"][0]["guardrails_pass"]
        del report["rows"][0]["failed_guardrails"]
        self.assertIn("unknown | unknown", render_report(report, "markdown"))
        self.assertIn("guardrails_pass", render_report(report, "csv"))

    def test_deadline_boundary_and_unchanged_input(self):
        original = parse_scenario(scenario([route()]))
        report = run_transaction_sweep(original, "deadline_hours", [Decimal("1.99"), Decimal(2)])
        self.assertEqual([r["probability_by_deadline"] for r in report["rows"]], ["0", "0.8"])
        self.assertEqual(original.transaction.deadline_hours, Decimal(3))
        for format in ("json", "csv", "markdown"):
            self.assertIn("deadline_hours", render_report(report, format))

    def test_volume_reduces_carry_cost(self):
        rows = run_transaction_sweep(parse_scenario(scenario([route()])), "volume_per_period", [Decimal(1), Decimal(100)])["rows"]
        self.assertGreater(Decimal(rows[0]["expected_sender_cost"]), Decimal(rows[1]["expected_sender_cost"]))

    def test_rejects_invalid_or_unbounded_values(self):
        source = parse_scenario(scenario([route()]))
        for parameter, values in [("send_amount", [Decimal(0)]), ("deadline_hours", [Decimal(-1)]), ("fx_rate", [Decimal(1)]), ("send_amount", []), ("send_amount", [Decimal("NaN")])]:
            with self.subTest(parameter=parameter, values=values), self.assertRaises(InputError):
                run_transaction_sweep(source, parameter, values)
