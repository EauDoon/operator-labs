import json
import tempfile
import unittest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch

import corridor_lab.route as route_module
from corridor_lab.cli import main as cli_main
from corridor_lab.gui_controller import BUILTIN_DEMO_SCENARIO, CorridorGuiController
from helpers import route, scenario


class StructuredTransactionEditingTests(unittest.TestCase):
    def test_applied_edits_preserve_exact_decimal_digits(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        result = controller.apply_transaction_edits(send_amount="1234.567890", deadline_hours="8.5", volume_per_period="120")
        self.assertIsNone(result.error)
        fields = controller.transaction_fields()
        self.assertEqual(fields["send_amount"], "1234.567890")
        self.assertEqual(fields["deadline_hours"], "8.5")
        self.assertEqual(fields["volume_per_period"], "120")
        self.assertTrue(controller.scenario_unsaved)
        self.assertIn('"send_amount": "1234.567890"', controller.scenario_draft_text)

    def test_empty_fields_leave_declared_values_unchanged(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        self.assertIsNone(controller.apply_transaction_edits(deadline_hours="4").error)
        self.assertIsNone(controller.apply_transaction_edits(send_amount="  ").error)
        fields = controller.transaction_fields()
        self.assertEqual(fields["send_amount"], "1000.00")
        self.assertEqual(fields["deadline_hours"], "4")
        self.assertEqual(fields["volume_per_period"], "100")

    def test_rejected_draft_keeps_active_scenario_report_and_draft(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        self.assertIsNone(controller.compare().error)
        report_before = controller.last_report
        draft_before = controller.scenario_draft_text
        rejected = controller.apply_transaction_edits(send_amount="-1")
        self.assertIsNotNone(rejected.error)
        self.assertEqual(controller.transaction_fields()["send_amount"], "1000.00")
        self.assertEqual(controller.scenario_draft_text, draft_before)
        self.assertIs(controller.last_report, report_before)
        self.assertFalse(controller.scenario_unsaved)

    def test_applied_edit_clears_the_previous_report(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        self.assertIsNone(controller.compare().error)
        self.assertIsNotNone(controller.last_report)
        self.assertIsNone(controller.apply_transaction_edits(deadline_hours="12").error)
        self.assertIsNone(controller.last_report)

    def test_edits_round_trip_through_the_json_editor(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        self.assertIsNone(controller.apply_transaction_edits(send_amount="2500.50").error)
        parsed = json.loads(controller.scenario_draft_text)
        self.assertEqual(parsed["transaction"]["send_amount"], "2500.50")
        self.assertIsNone(controller.validate_and_use_scenario_text(controller.scenario_draft_text).error)
        self.assertEqual(controller.transaction_fields()["send_amount"], "2500.50")

    def test_structured_edits_after_file_load_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            scenario_path = Path(temporary) / "scenario.json"
            data = scenario()
            data["transaction"]["send_precision"] = 2  # bare JSON number in the file
            data["transaction"]["send_amount"] = "1234.50"
            scenario_path.write_text(json.dumps(data), encoding="utf-8")
            controller = CorridorGuiController()
            self.assertIsNone(controller.load_scenario_file(scenario_path).error)
            result = controller.apply_transaction_edits(deadline_hours="6")
            self.assertIsNone(result.error)
            reparsed = json.loads(controller.scenario_draft_text)
            self.assertEqual(reparsed["transaction"]["send_precision"], 2)
            self.assertEqual(reparsed["transaction"]["send_amount"], "1234.50")
            self.assertEqual(reparsed["transaction"]["deadline_hours"], "6")
            self.assertIsNone(controller.validate_and_use_scenario_text(controller.scenario_draft_text).error)
            self.assertEqual(controller.transaction_fields()["deadline_hours"], "6")
            self.assertTrue(controller.scenario_unsaved)

    def test_structured_edits_never_route_through_binary_floats(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        exact = "0.145"
        with patch("corridor_lab.gui_controller.float", side_effect=AssertionError("float used")):
            result = controller.apply_transaction_edits(send_amount=exact)
        self.assertIsNone(result.error)
        self.assertEqual(controller.transaction_fields()["send_amount"], exact)
        as_decimal = Decimal(controller.transaction_fields()["send_amount"])
        self.assertEqual(as_decimal, Decimal("0.145"))


class WorkbenchAnalysisTests(unittest.TestCase):
    def test_declared_analyses_run_against_the_demo(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        for action in (controller.cost_ledger, controller.deadline_profile, controller.outcome_ledger,
                       controller.guardrail_headroom, controller.loss_profile, controller.feasible_amount,
                       controller.break_even_check):
            with self.subTest(action=action.__name__):
                self.assertIsNone(action().error)
                self.assertIsNotNone(controller.render_last_report("markdown"))
        self.assertIsNone(controller.deadline_target("0.95").error)
        self.assertIsNone(controller.resolution_quantiles("0.5,0.95,1").error)
        self.assertIsNone(controller.transaction_grid("deadline_hours", "1,2", "volume_per_period", "10,100").error)

    def test_deadline_target_and_quantiles_reject_out_of_range_values(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        self.assertIsNotNone(controller.deadline_target("1.5").error)
        self.assertIsNotNone(controller.resolution_quantiles("0,0.5").error)
        self.assertIsNotNone(controller.transaction_grid("deadline_hours", "1", "deadline_hours", "2").error)

    def test_controller_matches_the_cli_report_for_the_same_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario_path = root / "scenario.json"
            self.assertEqual(cli_main(["init", "--output", str(scenario_path)]), 0)
            expected: dict[str, dict] = {}
            for command, extra in (
                ("cost-ledger", []),
                ("deadline-profile", []),
                ("guardrail-headroom", []),
                ("outcome-ledger", []),
                ("deadline-target", ["--probability", "0.9"]),
                ("resolution-quantiles", ["--probabilities", "0.5,0.95"]),
            ):
                output = root / f"{command}.json"
                self.assertEqual(cli_main([command, str(scenario_path), *extra, "--format", "json", "--output", str(output)]), 0)
                expected[command] = json.loads(output.read_text(encoding="utf-8"))
            controller = CorridorGuiController()
            self.assertIsNone(controller.load_scenario_file(scenario_path).error)
            self.assertEqual(controller.cost_ledger().report, expected["cost-ledger"])
            self.assertEqual(controller.deadline_profile().report, expected["deadline-profile"])
            self.assertEqual(controller.guardrail_headroom().report, expected["guardrail-headroom"])
            self.assertEqual(controller.outcome_ledger().report, expected["outcome-ledger"])
            self.assertEqual(controller.deadline_target("0.9").report, expected["deadline-target"])
            self.assertEqual(controller.resolution_quantiles("0.5,0.95").report, expected["resolution-quantiles"])

    def test_scenario_diff_reports_candidate_minus_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path = root / "baseline.json"
            candidate_path = root / "candidate.json"
            baseline = json.loads(json.dumps(BUILTIN_DEMO_SCENARIO))
            baseline["transaction"]["send_amount"] = "100.00"
            for outcome in baseline["routes"][0]["outcomes"] + baseline["routes"][1]["outcomes"]:
                if outcome["completion"] == "failure":
                    outcome["recovery_amount_send"] = "98"
            candidate = json.loads(json.dumps(BUILTIN_DEMO_SCENARIO))
            candidate["transaction"]["send_amount"] = "300.00"
            for outcome in candidate["routes"][0]["outcomes"] + candidate["routes"][1]["outcomes"]:
                if outcome["completion"] == "failure":
                    outcome["recovery_amount_send"] = "294"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            controller = CorridorGuiController()
            self.assertIsNone(controller.load_scenario_file(candidate_path).error)
            result = controller.diff_against_baseline(baseline_path)
            self.assertIsNone(result.error)
            report = result.report
            self.assertEqual(report["baseline_scenario_id"], "fictional-gui-amber-to-birch")
            self.assertEqual(report["scenario_id"], "fictional-gui-amber-to-birch")
            recipient_rows = [row for row in report["rows"] if row["metric"] == "expected_recipient_amount"]
            self.assertTrue(recipient_rows)
            for row in recipient_rows:
                self.assertEqual(Decimal(row["delta"]), Decimal(row["candidate"]) - Decimal(row["baseline"]))
                self.assertGreater(Decimal(row["delta"]), 0)
            self.assertEqual(controller.last_report_inputs, (candidate_path, baseline_path))

    def test_scenario_diff_requires_compatible_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incompatible_path = root / "incompatible.json"
            incompatible = json.loads(json.dumps(BUILTIN_DEMO_SCENARIO))
            incompatible["transaction"]["receive_currency"] = "ZZZ"
            incompatible["scenario_id"] = "fictional-incompatible"
            incompatible_path.write_text(json.dumps(incompatible), encoding="utf-8")
            controller = CorridorGuiController()
            self.assertIsNone(controller.load_builtin_demo().error)
            result = controller.diff_against_baseline(incompatible_path)
            self.assertIsNotNone(result.error)
            self.assertIn("matching currencies", result.error)


if __name__ == "__main__":
    unittest.main()
