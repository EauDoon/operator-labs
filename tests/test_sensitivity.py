import unittest

from helpers import route, scenario
from corridor_lab.scenario import parse_scenario
from corridor_lab.sensitivity import run_sensitivity
from decimal import Decimal


class SensitivityTests(unittest.TestCase):
    def test_higher_spread_cannot_improve_recipient_amount(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        report = run_sensitivity(parsed, "fx_spread_bps", [Decimal("0"), Decimal("100")])
        self.assertEqual(report["rows"][0]["expected_recipient_amount"], "156.80")
        self.assertEqual(report["rows"][1]["expected_recipient_amount"], "155.23")

    def test_unsupported_parameter_fails(self):
        parsed = parse_scenario(scenario(routes=[route()]))
        with self.assertRaises(Exception):
            run_sensitivity(parsed, "liquidity.prefunding_amount_send", [Decimal("1")])
