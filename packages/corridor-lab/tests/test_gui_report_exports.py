import json
import os
import tempfile
import unittest
from pathlib import Path

from corridor_lab.gui_controller import CorridorGuiController
from helpers import route, scenario


class GuiReportExportProtectionTests(unittest.TestCase):
    """Report exports must never replace or nest inside tracked inputs."""

    def _controller_with_files(self, root: Path) -> tuple[CorridorGuiController, Path, Path]:
        scenario_path = root / "scenario.json"
        routes_path = root / "routes.json"
        scenario_path.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
        routes_path.write_text(json.dumps(route("fictional-selected-route")), encoding="utf-8")
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_scenario_file(scenario_path).error)
        self.assertIsNone(controller.load_routes_path(routes_path).error)
        return controller, scenario_path, routes_path

    def test_save_rejects_replacing_scenario_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, scenario_path, _ = self._controller_with_files(Path(temporary))
            before = scenario_path.read_bytes()
            self.assertIsNone(controller.evaluate().error)
            result = controller.save_last_report(scenario_path, "json")
            self.assertIsNotNone(result.error)
            self.assertEqual(scenario_path.read_bytes(), before)

    def test_save_rejects_replacing_routes_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, _, routes_path = self._controller_with_files(Path(temporary))
            before = routes_path.read_bytes()
            self.assertIsNone(controller.compare().error)
            result = controller.save_last_report(routes_path, "json")
            self.assertIsNotNone(result.error)
            self.assertEqual(routes_path.read_bytes(), before)

    def test_save_rejects_destination_inside_routes_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario_path = root / "scenario.json"
            scenario_path.write_text(json.dumps(scenario()), encoding="utf-8")
            routes_folder = root / "routes"
            routes_folder.mkdir()
            (routes_folder / "one.json").write_text(json.dumps(route()), encoding="utf-8")
            controller = CorridorGuiController()
            self.assertIsNone(controller.load_scenario_file(scenario_path).error)
            self.assertIsNone(controller.load_routes_path(routes_folder).error)
            self.assertIsNone(controller.compare().error)
            result = controller.save_last_report(routes_folder / "report.json", "json")
            self.assertIsNotNone(result.error)
            self.assertEqual([child.name for child in routes_folder.iterdir()], ["one.json"])

    def test_save_rejects_hard_link_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, scenario_path, _ = self._controller_with_files(Path(temporary))
            before = scenario_path.read_bytes()
            link = Path(temporary) / "hardlinked-report.json"
            os.link(scenario_path, link)
            self.assertIsNone(controller.evaluate().error)
            result = controller.save_last_report(link, "json")
            self.assertIsNotNone(result.error)
            self.assertEqual(scenario_path.read_bytes(), before)

    def test_save_rejects_symlink_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, scenario_path, _ = self._controller_with_files(Path(temporary))
            before = scenario_path.read_bytes()
            link = Path(temporary) / "symlinked-report.json"
            os.symlink(scenario_path.name, link)
            self.assertIsNone(controller.evaluate().error)
            result = controller.save_last_report(link, "json")
            self.assertIsNotNone(result.error)
            self.assertEqual(scenario_path.read_bytes(), before)

    def test_protection_survives_later_selector_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, scenario_path, routes_path = self._controller_with_files(Path(temporary))
            scenario_before = scenario_path.read_bytes()
            routes_before = routes_path.read_bytes()
            self.assertIsNone(controller.compare().error)
            controller.clear_route_selection()
            self.assertIsNone(controller.validate_and_use_scenario_text(json.dumps(scenario())).error)
            self.assertIsNotNone(controller.save_last_report(routes_path, "json").error)
            self.assertIsNotNone(controller.save_last_report(scenario_path, "json").error)
            self.assertEqual(scenario_path.read_bytes(), scenario_before)
            self.assertEqual(routes_path.read_bytes(), routes_before)

    def test_failed_export_preserves_existing_report_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, scenario_path, _ = self._controller_with_files(Path(temporary))
            destination = Path(temporary) / "existing-report.json"
            destination.write_text("previous report", encoding="utf-8")
            self.assertIsNone(controller.evaluate().error)
            self.assertIsNotNone(controller.save_last_report(scenario_path, "json").error)
            self.assertEqual(destination.read_text(encoding="utf-8"), "previous report")

    def test_successful_save_overwrites_only_user_chosen_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, _, routes_path = self._controller_with_files(Path(temporary))
            destination = Path(temporary) / "reports" / "compare.json"
            self.assertIsNone(controller.compare().error)
            self.assertIsNone(controller.save_last_report(destination, "json").error)
            first = destination.read_text(encoding="utf-8")
            self.assertIsNone(controller.save_last_report(destination, "json").error)
            self.assertEqual(destination.read_text(encoding="utf-8"), first)
            self.assertTrue(routes_path.exists())

    def test_demo_and_in_memory_reports_save_without_input_guards(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        self.assertIsNone(controller.compare().error)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "demo-report.md"
            self.assertIsNone(controller.save_last_report(destination, "markdown").error)
            self.assertIn("fictional-gui-linked-instant", destination.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
