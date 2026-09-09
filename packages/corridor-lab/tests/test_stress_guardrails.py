import unittest
from decimal import Decimal
from helpers import route, scenario
from corridor_lab.scenario import parse_scenario
from corridor_lab.stress import run_stress_grid
from corridor_lab.report import render_report

class StressGuardrailTests(unittest.TestCase):
    def test_reports_all_failed_cells_without_implicit_objective(self):
        objective = {"metric": "minimize_expected_sender_cost", "guardrails": {"minimum_probability_by_deadline": "0.9"}}
        source = parse_scenario(scenario([route()], objective))
        report = run_stress_grid(source, "fx_rate", [Decimal("1"), Decimal("2")], "fx_spread_bps", [Decimal("0")])
        self.assertEqual(report["guardrail_summary"][0]["passing_cells"], 0)
        self.assertEqual(report["guardrail_summary"][0]["total_cells"], 2)
        self.assertEqual(report["rows"][0]["failed_guardrails"], ["minimum_probability_by_deadline"])
        self.assertIn("Passing cells", render_report(report, "markdown"))
        self.assertIn("guardrails_pass", render_report(report, "csv"))
        plain = run_stress_grid(parse_scenario(scenario([route()])), "fx_rate", [Decimal("1")], "fx_spread_bps", [Decimal("0")])
        self.assertNotIn("guardrail_summary", plain)
        self.assertNotIn("guardrails_pass", plain["rows"][0])
