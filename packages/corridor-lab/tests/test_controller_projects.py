import json
import tempfile
import unittest
from pathlib import Path

from corridor_lab.cli import main as cli_main
from corridor_lab.gui_controller import CorridorGuiController
from corridor_lab.projects import PROJECT_MANIFEST_NAME
from helpers import route, scenario


def make_project(root: Path, *, with_routes: bool = True, with_baseline: bool = True) -> Path:
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    scenario_path = inputs / "scenario.json"
    scenario_path.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
    routes_path = None
    if with_routes:
        routes_path = inputs / "routes"
        routes_path.mkdir(exist_ok=True)
        (routes_path / "one.json").write_text(json.dumps(route("fictional-route-one")), encoding="utf-8")
    baseline_path = None
    if with_baseline:
        baseline_path = inputs / "baseline.json"
        baseline_path.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
    manifest = cli_main(["project", "create", "--directory", str(root), "--project-id", "fictional-gui-project",
                         "--scenario", str(scenario_path),
                         *(["--routes", str(routes_path)] if routes_path else []),
                         *(["--baseline", str(baseline_path)] if baseline_path else []),
                         "--experiment", "deadline-sweep:transaction-sweep:parameter=deadline_hours;values=1,2,8"])
    assert manifest == 0
    return root / PROJECT_MANIFEST_NAME


class ControllerProjectTests(unittest.TestCase):
    def test_open_project_loads_inputs_baseline_and_experiments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = make_project(root)
            controller = CorridorGuiController()
            result = controller.open_project(manifest_path)
            self.assertIsNone(result.error)
            self.assertEqual(result.report["project_id"], "fictional-gui-project")
            self.assertEqual(result.report["experiments"], ["deadline-sweep"])
            self.assertEqual(controller.scenario_source, str(root / "inputs" / "scenario.json"))
            self.assertIsNotNone(controller.selected_routes)
            self.assertEqual(controller.baseline_file, root / "inputs" / "baseline.json")
            self.assertEqual(controller.saved_experiment_names(), ("deadline-sweep",))
            self.assertIsNone(controller.last_report)

    def test_open_project_with_missing_input_reports_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = make_project(root)
            (root / "inputs" / "scenario.json").unlink()
            controller = CorridorGuiController()
            result = controller.open_project(manifest_path)
            self.assertIsNotNone(result.error)
            self.assertIn("missing input", result.error)
            self.assertIsNone(controller.scenario)
            self.assertEqual(controller.saved_experiment_names(), ())

    def test_run_saved_experiment_matches_the_cli_report(self):
        with tempfile.TemporaryDirectory() as temporary, __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            project_root = Path(temporary) / "project"
            project_root.mkdir()
            manifest_path = make_project(project_root)
            controller = CorridorGuiController()
            self.assertIsNone(controller.open_project(manifest_path).error)
            result = controller.run_saved_experiment("deadline-sweep")
            self.assertIsNone(result.error)
            cli_output = Path(temporary) / "cli-run.json"
            self.assertEqual(cli_main(["project", "run", str(project_root), "--output", str(cli_output)]), 0)
            combined = json.loads(cli_output.read_text(encoding="utf-8"))
            self.assertEqual(result.report, combined["items"][0]["report"])
            self.assertIn(str(project_root / "inputs" / "scenario.json"), [str(path) for path in controller.last_report_inputs])

    def test_staged_experiments_persist_through_save_project(self):
        with tempfile.TemporaryDirectory() as temporary, __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            source_root = Path(temporary) / "source"
            source_root.mkdir()
            manifest_path = make_project(source_root)
            controller = CorridorGuiController()
            self.assertIsNone(controller.open_project(manifest_path).error)
            staged = controller.add_saved_experiment(
                "volume-grid", "transaction-grid",
                {"parameter_a": "deadline_hours", "values_a": "1,2", "parameter_b": "volume_per_period", "values_b": "10,100"},
            )
            self.assertIsNone(staged.error)
            duplicate = controller.add_saved_experiment(
                "volume-grid", "transaction-grid",
                {"parameter_a": "deadline_hours", "values_a": "1,2", "parameter_b": "volume_per_period", "values_b": "10,100"},
            )
            self.assertIsNotNone(duplicate.error)
            destination = Path(temporary) / "saved-project"
            destination.mkdir()
            saved = controller.save_project(destination, "fictional-saved-project", "A saved copy.")
            self.assertIsNone(saved.error)
            fresh = CorridorGuiController()
            reopened = fresh.open_project(destination / PROJECT_MANIFEST_NAME)
            self.assertIsNone(reopened.error)
            self.assertEqual(sorted(fresh.saved_experiment_names()), ["deadline-sweep", "volume-grid"])
            self.assertIsNone(fresh.run_saved_experiment("volume-grid").error)

    def test_save_project_requires_file_backed_scenario(self):
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_builtin_demo().error)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "project"
            destination.mkdir()
            result = controller.save_project(destination, "fictional-project")
            self.assertIsNotNone(result.error)
            self.assertIn("from a file", result.error)


if __name__ == "__main__":
    unittest.main()
