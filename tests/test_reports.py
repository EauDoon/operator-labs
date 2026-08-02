import unittest
from pathlib import Path

from helpers import route, scenario
from corridor_lab.comparison import evaluate_scenario
from corridor_lab.report import render_report
from corridor_lab.scenario import parse_scenario


class ReportTests(unittest.TestCase):
    def test_json_report_is_byte_stable(self):
        report = evaluate_scenario(parse_scenario(scenario(routes=[route()])))
        self.assertEqual(render_report(report, "json"), render_report(report, "json"))
        self.assertTrue(render_report(report, "json").endswith("\n"))

    def test_csv_and_markdown_have_expected_headers(self):
        report = evaluate_scenario(parse_scenario(scenario(routes=[route()])))
        self.assertTrue(render_report(report, "csv").startswith("route_id,"))
        self.assertTrue(render_report(report, "markdown").startswith("# Corridor Lab report\n"))
        self.assertIn("successful completion by declared deadline", render_report(report, "csv"))

    def test_markdown_explains_metrics_without_changing_json_or_csv_contracts(self):
        report = evaluate_scenario(parse_scenario(scenario(routes=[route()])))
        markdown = render_report(report, "markdown")
        self.assertIn("## How to read this report", markdown)
        self.assertIn("Recipient figures are in `RCV`", markdown)
        self.assertIn("does not recommend a route", markdown)
        self.assertNotIn("How to read", render_report(report, "json"))
        self.assertNotIn("How to read", render_report(report, "csv"))

    def test_worked_markdown_fixture_matches_renderer(self):
        root = Path(__file__).resolve().parents[1]
        scenario_file = root / "examples" / "fictional-corridor" / "scenario.json"
        routes_folder = root / "examples" / "fictional-corridor" / "routes"
        from corridor_lab.cli import _load_routes_argument
        from corridor_lab.comparison import compare_routes
        from corridor_lab.scenario import load_scenario

        parsed = load_scenario(scenario_file)
        report = compare_routes(parsed.transaction, _load_routes_argument(str(routes_folder)), parsed.objective, parsed.scenario_id)
        expected = (root / "examples" / "fictional-corridor" / "expected" / "compare.md").read_text(encoding="utf-8")
        self.assertEqual(render_report(report, "markdown"), expected)

    def test_csv_formula_text_is_prefixed_with_an_apostrophe(self):
        data = route(" \t=1+1")
        data["label"] = " \r@SUM(A1:A2)"
        report = evaluate_scenario(parse_scenario(scenario(routes=[data])))
        csv_text = render_report(report, "csv")
        self.assertIn("' \t=1+1", csv_text)
        self.assertIn("' \r@SUM(A1:A2)", csv_text)
