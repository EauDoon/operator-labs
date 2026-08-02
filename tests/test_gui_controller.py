import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from helpers import route, scenario
from corridor_lab.gui import run_smoke_test
from corridor_lab.gui_controller import CorridorGuiController
from corridor_lab.canonical import MAX_INPUT_BYTES
from corridor_lab.scenario import parse_scenario


class GuiControllerTests(unittest.TestCase):
    def test_builtin_demo_supports_all_actions_and_stable_reports(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        self.assertIsNone(controller.compare().error)
        first_json = controller.render_last_report("json")
        second_json = controller.render_last_report("json")
        self.assertEqual(first_json, second_json)
        self.assertIn('"declared_inputs"', first_json)
        self.assertIsNone(controller.evaluate().error)
        self.assertIsNone(controller.sensitivity("fx_spread_bps", "10,25,50").error)
        self.assertIn("probability_by_deadline_definition", controller.render_last_report("csv"))

    def test_file_scenario_and_route_folder_drive_compare(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario_path = root / "scenario.json"
            routes_path = root / "routes"
            routes_path.mkdir()
            scenario_path.write_text(json.dumps(scenario()), encoding="utf-8")
            (routes_path / "route.json").write_text(json.dumps(route("fictional-selected-route")), encoding="utf-8")
            controller = CorridorGuiController()
            self.assertIsNone(controller.load_scenario_file(scenario_path).error)
            self.assertIsNone(controller.load_routes_path(routes_path).error)
            result = controller.compare()
            self.assertIsNone(result.error)
            self.assertEqual(result.report["routes"][0]["route_id"], "fictional-selected-route")

    def test_formula_safe_csv_export_and_explicit_save(self):
        malicious = route(" \t=1+1")
        malicious["label"] = " \r@SUM(A1:A2)"
        controller = CorridorGuiController()
        controller.scenario = parse_scenario(scenario(routes=[malicious]))
        self.assertIsNone(controller.evaluate().error)
        csv_text = controller.render_last_report("csv")
        self.assertIn("' \t=1+1", csv_text)
        self.assertIn("' \r@SUM(A1:A2)", csv_text)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.csv"
            self.assertIsNone(controller.save_last_report(output, "csv").error)
            with output.open("r", encoding="utf-8", newline="") as report_file:
                self.assertEqual(report_file.read(), csv_text)

    def test_validation_errors_are_retained_for_the_gui(self):
        controller = CorridorGuiController()
        result = controller.compare()
        self.assertIsNone(result.report)
        self.assertIn("load a fictional scenario", result.error)
        self.assertIsNone(controller.render_last_report("markdown"))
        self.assertIn("run Compare", controller.last_error)

    def test_editor_template_validation_rolls_back_on_invalid_draft(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        active_id = controller.scenario.scenario_id
        template = controller.load_fictional_template()
        self.assertIn('"fictional": true', template)
        invalid = template.replace('"fictional": true', '"fictional": false', 1)
        result = controller.validate_and_use_scenario_text(invalid)
        self.assertIsNotNone(result.error)
        self.assertEqual(controller.scenario.scenario_id, active_id)
        self.assertEqual(controller.scenario_source, "Built-in fictional Amber to Birch demo")
        self.assertIsNone(controller.validate_and_use_scenario_text(template).error)
        self.assertEqual(controller.scenario_source, "Validated in-memory fictional scenario")

    def test_editor_save_is_explicit_and_requires_a_valid_fictional_draft(self):
        controller = CorridorGuiController()
        controller.load_builtin_demo()
        active_id = controller.scenario.scenario_id
        draft = controller.load_fictional_template()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "scenario.json"
            self.assertIsNone(controller.save_scenario_text(output, draft).error)
            with output.open("r", encoding="utf-8", newline="") as scenario_file:
                self.assertEqual(scenario_file.read(), draft)
            self.assertEqual(controller.scenario.scenario_id, active_id)
            self.assertIsNotNone(controller.save_scenario_text(output, "{}").error)
            self.assertEqual(controller.scenario.scenario_id, active_id)

    def test_headless_gui_smoke_test(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(run_smoke_test(), 0)

    def test_gui_scenario_file_read_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oversized.json"
            path.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
            result = CorridorGuiController().load_scenario_file(path)
        self.assertIsNone(result.report)
        self.assertIn("input exceeds", result.error)
