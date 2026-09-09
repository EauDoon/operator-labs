import unittest
from helpers import route, scenario
from corridor_lab.scenario import parse_scenario
from corridor_lab.scenario_diff import diff_scenarios
from corridor_lab.canonical import InputError
from corridor_lab.report import render_report

class ScenarioDiffTests(unittest.TestCase):
    def test_changed_fees_and_route_membership(self):
        a = scenario([route("common"), route("removed")])
        b = scenario([route("common"), route("added")])
        b["routes"][0]["fixed_fee_send"] = "2"
        report = diff_scenarios(parse_scenario(a), parse_scenario(b))
        self.assertEqual(report["added_routes"], ["added"])
        self.assertEqual(report["removed_routes"], ["removed"])
        cost = next(r for r in report["rows"] if r["metric"] == "expected_sender_cost")
        self.assertEqual(cost["delta"], "1")
        for format in ("json", "markdown", "csv"):
            self.assertIn("expected_sender_cost", render_report(report, format))

    def test_currency_mismatch_and_identity(self):
        raw = scenario([route()])
        a = parse_scenario(raw)
        self.assertTrue(all(r["delta"] == "0" for r in diff_scenarios(a, a)["rows"]))
        raw["transaction"]["receive_currency"] = "OTHER"
        with self.assertRaises(InputError):
            diff_scenarios(a, parse_scenario(raw))
