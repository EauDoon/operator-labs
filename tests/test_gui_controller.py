import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from helpers import route, scenario
import corridor_lab.route as route_module
from corridor_lab.gui import run_smoke_test
from corridor_lab.gui_controller import CorridorGuiController
from corridor_lab.canonical import InputError, MAX_INPUT_BYTES, MAX_ROUTES
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
        self.assertIsNone(controller.pareto().error)
        self.assertTrue(controller.render_last_report("csv").startswith("route_id,"))

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
        malicious = route("formula-route")
        malicious["label"] = " \r@SUM(A1:A2)"
        controller = CorridorGuiController()
        controller.scenario = parse_scenario(scenario(routes=[malicious]))
        self.assertIsNone(controller.evaluate().error)
        csv_text = controller.render_last_report("csv")
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
        self.assertIn("run Compare, Evaluate, Sensitivity, Pareto, or Grid", controller.last_error)

    def test_stress_grid_rejects_empty_comma_separated_values(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        result = controller.stress_grid("fx_spread_bps", "10,,50", "delay_hours", "0,24")
        self.assertIsNone(result.report)
        self.assertIn("comma-separated decimals", result.error)

    def test_sensitivity_rejects_blank_parameter_name(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        result = controller.sensitivity("   ", "10,25")
        self.assertIsNone(result.report)
        self.assertIn("parameter must not be empty", result.error)
        padded = controller.sensitivity(" fx_spread_bps ", "10,25")
        self.assertIsNone(padded.error)

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

    def test_gui_route_folder_is_bounded_before_files_are_parsed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(MAX_ROUTES + 1):
                (root / f"route-{index}.json").touch()
            result = CorridorGuiController().load_routes_path(root)
        self.assertIsNone(result.report)
        self.assertIn(f"exceeds the {MAX_ROUTES}-route budget", result.error)

    def test_route_folder_callers_do_not_follow_json_symlinks(self):
        from corridor_lab.cli import _load_routes_argument

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / "routes"
            selected.mkdir()
            (selected / "inside.json").write_text(json.dumps(route("inside-route")), encoding="utf-8")
            outside = root / "outside.json"
            outside.write_text(json.dumps(route("outside-route")), encoding="utf-8")
            try:
                (selected / "linked.json").symlink_to(outside)
                linked_folder = root / "linked-routes"
                linked_folder.symlink_to(selected, target_is_directory=True)
            except (NotImplementedError, OSError):
                self.skipTest("symlinks are unavailable")
            self.assertEqual([item.route_id for item in _load_routes_argument(str(selected))], ["inside-route"])
            controller = CorridorGuiController()
            self.assertIsNone(controller.load_routes_path(selected).error)
            self.assertEqual([item.route_id for item in controller.selected_routes], ["inside-route"])
            self.assertEqual([item.route_id for item in _load_routes_argument(str(selected / "linked.json"))], ["outside-route"])
            self.assertIsNone(controller.load_routes_path(selected / "linked.json").error)
            self.assertEqual([item.route_id for item in controller.selected_routes], ["outside-route"])
            with self.assertRaisesRegex(InputError, "not a folder"):
                _load_routes_argument(str(linked_folder))
            self.assertIn("not a folder", controller.load_routes_path(linked_folder).error)

    def test_route_folder_does_not_use_cached_windows_directory_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary) / "routes"
            selected.mkdir()
            inside = selected / "inside.json"
            inside.write_text(json.dumps(route("inside-route")), encoding="utf-8")
            actual = inside.stat()
            cached = route_module.os.stat_result(
                (actual.st_mode, 0, 0, actual.st_nlink, actual.st_uid, actual.st_gid,
                 actual.st_size, actual.st_atime, actual.st_mtime, actual.st_ctime)
            )

            class WindowsDirEntry:
                name = inside.name
                path = str(inside)

                def is_file(self, *, follow_symlinks=True):
                    return True

                def stat(self, *, follow_symlinks=True):
                    return cached

            with patch.object(route_module.os, "scandir") as scandir:
                scandir.return_value.__enter__.return_value = iter([WindowsDirEntry()])
                routes = route_module.load_route_folder(selected)
            self.assertEqual([item.route_id for item in routes], ["inside-route"])

    def test_route_folder_callers_reject_a_file_swapped_after_scanning(self):
        from corridor_lab.cli import _load_routes_argument

        for caller in ("cli", "gui"):
            with self.subTest(caller=caller), tempfile.TemporaryDirectory() as temporary:
                selected = Path(temporary) / "routes"
                selected.mkdir()
                inside = selected / "inside.json"
                inside.write_text(json.dumps(route("inside-route")), encoding="utf-8")
                replacement = selected / "replacement.tmp"
                replacement.write_text(json.dumps(route("replacement-route")), encoding="utf-8")
                original_reader = route_module._read_scanned_route

                def swap_before_open(*args):
                    replacement.replace(inside)
                    return original_reader(*args)

                with patch.object(route_module, "_read_scanned_route", side_effect=swap_before_open):
                    if caller == "cli":
                        with self.assertRaisesRegex(InputError, "changed while being read"):
                            _load_routes_argument(str(selected))
                    else:
                        result = CorridorGuiController().load_routes_path(selected)
                        self.assertIn("changed while being read", result.error)
