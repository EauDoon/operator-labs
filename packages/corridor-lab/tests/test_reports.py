import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from corridor_lab.canonical import atomic_write_text
from corridor_lab.comparison import evaluate_scenario
from corridor_lab.report import render_report
from corridor_lab.scenario import parse_scenario
from helpers import route, scenario


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

    def test_markdown_explains_an_all_ineligible_ranking(self):
        objective = {
            "metric": "maximize_expected_recipient_amount",
            "guardrails": {"minimum_probability_by_deadline": "0.9", "maximum_tail_hours": "4"},
        }
        report = evaluate_scenario(parse_scenario(scenario(routes=[route()], objective=objective)))
        markdown = render_report(report, "markdown")
        self.assertIn("No routes met every declared guardrail.", markdown)
        self.assertIn("### Guardrail rejections", markdown)
        self.assertIn(
            "| fictional-route | Minimum successful-by-deadline probability; Maximum tail time |",
            markdown,
        )

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
        data = route("formula-route")
        data["label"] = " \r@SUM(A1:A2)"
        report = evaluate_scenario(parse_scenario(scenario(routes=[data])))
        csv_text = render_report(report, "csv")
        self.assertIn("' \r@SUM(A1:A2)", csv_text)

    def test_batch_markdown_includes_requested_paths(self):
        report = {
            "report_version": "corridor-lab.batch/v1",
            "status": "pass",
            "items": [{"id": "scenario-0001", "status": "pass", "path": "[review](README.md).json"}],
        }
        markdown = render_report(report, "markdown")
        self.assertIn("| Item | Status | Path |", markdown)
        self.assertIn(r"| scenario-0001 | pass | \[review\]\(README.md\).json |", markdown)

    def test_batch_markdown_includes_evaluation_errors(self):
        report = {
            "report_version": "corridor-lab.batch/v1",
            "status": "unresolved",
            "items": [
                {
                    "id": "scenario-0001",
                    "status": "unresolved",
                    "path": "broken.json",
                    "report": {"status": "unresolved", "error": "broken.json: evaluate requires routes embedded in the scenario"},
                }
            ],
        }
        markdown = render_report(report, "markdown")
        self.assertIn("| Item | Status | Path | Error |", markdown)
        self.assertIn(
            "| scenario-0001 | unresolved | broken.json | broken.json: evaluate requires routes embedded in the scenario |",
            markdown,
        )

    def test_atomic_write_preserves_target_and_removes_temporary_file_on_replace_failure(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"
            target.write_text("old\n", encoding="utf-8")
            with patch("corridor_lab.canonical.os.replace", side_effect=OSError("replace failed")), self.assertRaises(OSError):
                atomic_write_text(target, "new\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
