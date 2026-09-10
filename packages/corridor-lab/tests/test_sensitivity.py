import unittest
from decimal import Decimal

from corridor_lab.canonical import InputError
from corridor_lab.report import render_report
from corridor_lab.scenario import parse_scenario
from corridor_lab.sensitivity import run_sensitivity
from corridor_lab.stress import run_stress_grid
from helpers import route, scenario


class SensitivityTests(unittest.TestCase):
    def test_higher_spread_cannot_improve_recipient_amount(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        report = run_sensitivity(parsed, "fx_spread_bps", [Decimal(0), Decimal(100)])
        self.assertEqual(report["rows"][0]["expected_recipient_amount"], "156.80")
        self.assertEqual(report["rows"][1]["expected_recipient_amount"], "155.23")

    def test_unsupported_parameter_fails(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        with self.assertRaisesRegex(Exception, "choose from fx_rate, fixed_fee_send, percent_fee_bps, fx_spread_bps"):
            run_sensitivity(parsed, "liquidity.prefunding_amount_send", [Decimal(1)])
        with self.assertRaisesRegex(Exception, "parameter must not be empty"):
            run_sensitivity(parsed, "  ", [Decimal(1)])

    def test_two_parameter_grid_is_bounded_and_deterministic(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        report = run_stress_grid(
            parsed,
            "fx_rate",
            [Decimal("1.9"), Decimal("2.0")],
            "fx_spread_bps",
            [Decimal(0), Decimal(100)],
        )
        self.assertEqual(len(report["rows"]), 4)
        self.assertEqual(report["rows"][0]["parameter_a"], "fx_rate")
        self.assertEqual(report["rows"][0]["parameter_b"], "fx_spread_bps")
        csv_text = render_report(report, "csv")
        self.assertIn("parameter_a", csv_text)
        self.assertIn("fx_rate", csv_text)
        self.assertIn("| Route | fx_rate | fx_spread_bps |", render_report(report, "markdown"))

    def test_non_finite_and_non_decimal_sensitivity_values_are_rejected(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        route_model = parsed.routes[0]
        cases = (
            ([Decimal("NaN")], "must be finite"),
            ([Decimal("Infinity")], "must be finite"),
            ([Decimal("-Infinity")], "must be finite"),
            ([float("inf")], "must be a decimal string or integer"),
            ("10,25", "must be a list of decimals"),
        )
        for values, message in cases:
            with self.subTest(values=values):
                with self.assertRaisesRegex(InputError, message):
                    run_sensitivity(parsed, "fx_spread_bps", values)
                if not isinstance(values, str):
                    with self.assertRaisesRegex(InputError, message):
                        route_model.changed_parameter("fx_spread_bps", values[0])

    def test_duplicate_sensitivity_and_stress_values_are_rejected(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        with self.assertRaisesRegex(InputError, "sensitivity must not contain duplicate values"):
            run_sensitivity(parsed, "fx_spread_bps", [Decimal(10), Decimal("10.0")])
        with self.assertRaisesRegex(InputError, "stress grid parameter-a must not contain duplicate values"):
            run_stress_grid(
                parsed,
                "fx_rate",
                [Decimal("1.7"), Decimal("1.70")],
                "fx_spread_bps",
                [Decimal(25), Decimal(50)],
            )
        with self.assertRaisesRegex(InputError, "stress grid parameter-b must not contain duplicate values"):
            run_stress_grid(
                parsed,
                "fx_rate",
                [Decimal("1.7"), Decimal("1.8")],
                "fx_spread_bps",
                [Decimal(25), Decimal(25)],
            )
