"""Independent Decimal oracles for explicit fictional scenario inspection."""
import unittest
from decimal import Decimal, localcontext

from helpers import route, scenario
from corridor_lab.analysis import guardrail_headroom
from corridor_lab.canonical import InputError
from corridor_lab.scenario import parse_scenario
from corridor_lab.report import render_report


class HeadroomTests(unittest.TestCase):
    def test_signed_margins_and_equality_match_declared_guards(self):
        objective = {"metric": "minimize_expected_sender_cost", "guardrails": {
            "minimum_probability_by_deadline": "0.9", "maximum_tail_hours": "4"}}
        source = parse_scenario(scenario([route()], objective))
        expected = guardrail_headroom(source)
        self.assertEqual([row["headroom"] for row in expected["rows"]], ["-0.1", "-1"])
        self.assertTrue(all(not row["passes"] for row in expected["rows"]))
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(guardrail_headroom(source), expected)
        objective["guardrails"].update(minimum_probability_by_deadline="0.8", maximum_tail_hours="5")
        self.assertTrue(all(row["passes"] for row in guardrail_headroom(parse_scenario(scenario([route()], objective)))["rows"]))
        for output_format in ("json", "csv", "markdown"):
            self.assertIn("headroom", render_report(expected, output_format))

    def test_missing_objective_does_not_infer_guardrails(self):
        with self.assertRaises(InputError):
            guardrail_headroom(parse_scenario(scenario([route()])))
