import unittest

from helpers import route, scenario
from corridor_lab.scenario import parse_scenario
from corridor_lab.sensitivity import run_sensitivity
from corridor_lab.stress import run_stress_grid
from corridor_lab.report import render_report
from decimal import Decimal


class SensitivityTests(unittest.TestCase):
    def test_higher_spread_cannot_improve_recipient_amount(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        report = run_sensitivity(parsed, "fx_spread_bps", [Decimal("0"), Decimal("100")])
        self.assertEqual(report["rows"][0]["expected_recipient_amount"], "156.80")
        self.assertEqual(report["rows"][1]["expected_recipient_amount"], "155.23")

    def test_unsupported_parameter_fails(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        with self.assertRaisesRegex(Exception, "choose from fx_rate, fixed_fee_send, percent_fee_bps, fx_spread_bps"):
            run_sensitivity(parsed, "liquidity.prefunding_amount_send", [Decimal("1")])
        with self.assertRaisesRegex(Exception, "parameter must not be empty"):
            run_sensitivity(parsed, "  ", [Decimal("1")])

    def test_two_parameter_grid_is_bounded_and_deterministic(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        report = run_stress_grid(
            parsed,
            "fx_rate",
            [Decimal("1.9"), Decimal("2.0")],
            "fx_spread_bps",
            [Decimal("0"), Decimal("100")],
        )
        self.assertEqual(len(report["rows"]), 4)
        self.assertEqual(report["rows"][0]["parameter_a"], "fx_rate")
        self.assertEqual(report["rows"][0]["parameter_b"], "fx_spread_bps")
        csv_text = render_report(report, "csv")
        self.assertIn("parameter_a", csv_text)
        self.assertIn("fx_rate", csv_text)
        self.assertIn("| Route | fx_rate | fx_spread_bps |", render_report(report, "markdown"))
