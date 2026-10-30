"""Saved project routes stand in when the project scenario embeds none."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from corridor_lab.analysis import deadline_target
from corridor_lab.cli import main as cli_main
from corridor_lab.comparison import evaluate_scenario
from corridor_lab.gui_controller import CorridorGuiController
from corridor_lab.scenario import load_scenario, parse_scenario
from corridor_lab.variants import variant_comparison
from helpers import ROOT, route, scenario

EXAMPLE = ROOT / "examples" / "fictional-corridor"


def run_cli(*args: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli_main([str(arg) for arg in args])
    return code, stdout.getvalue(), stderr.getvalue()


def example_project(root: Path, *, routes: str = "folder") -> Path:
    """A project laid out like examples/fictional-corridor: routes beside, not in, the scenario."""
    project = root / "project"
    inputs = project / "inputs"
    inputs.mkdir(parents=True)
    shutil.copyfile(EXAMPLE / "scenario.json", inputs / "scenario.json")
    if routes == "folder":
        shutil.copytree(EXAMPLE / "routes", inputs / "routes")
        selection = inputs / "routes"
    else:
        shutil.copyfile(EXAMPLE / "routes" / "linked-instant.json", inputs / "linked-instant.json")
        selection = inputs / "linked-instant.json"
    code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-saved-routes",
                              "--scenario", inputs / "scenario.json", "--routes", selection,
                              "--experiment", "dl:deadline-target:probability=0.9")
    assert code == 0, stderr
    return project


def merged_example(selection: list[Path]) -> dict:
    raw = json.loads((EXAMPLE / "scenario.json").read_text(encoding="utf-8"))
    raw["routes"] = [json.loads(path.read_text(encoding="utf-8")) for path in selection]
    return raw


class SavedRoutesCliTests(unittest.TestCase):
    def test_project_run_uses_the_saved_route_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = example_project(Path(temporary))
            scenario_bytes = (project / "inputs" / "scenario.json").read_bytes()
            code, stdout, stderr = run_cli("project", "run", project, "--format", "json")
            self.assertEqual(code, 0, stderr)
            report = json.loads(stdout)
            self.assertEqual(report["status"], "pass")
            expected = deadline_target(parse_scenario(merged_example(sorted((EXAMPLE / "routes").glob("*.json")))), "0.9")
            self.assertEqual(report["items"][0]["report"], json.loads(json.dumps(expected)))
            self.assertEqual((project / "inputs" / "scenario.json").read_bytes(), scenario_bytes)

    def test_a_single_saved_route_file_also_stands_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = example_project(Path(temporary), routes="file")
            code, stdout, stderr = run_cli("project", "run", project, "--format", "json")
            self.assertEqual(code, 0, stderr)
            expected = deadline_target(parse_scenario(merged_example([EXAMPLE / "routes" / "linked-instant.json"])), "0.9")
            self.assertEqual(json.loads(stdout)["items"][0]["report"], json.loads(json.dumps(expected)))

    def test_route_variants_compare_and_show_against_saved_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = example_project(Path(temporary))
            scenario_bytes = (project / "inputs" / "scenario.json").read_bytes()
            code, _, stderr = run_cli("project", "add-variant", project, "--variant", "cheap",
                                      "--changes", "route.fictional-correspondent-style.fixed_fee_send=1")
            self.assertEqual(code, 0, stderr)
            code, stdout, stderr = run_cli("project", "compare-variants", project, "--format", "json")
            self.assertEqual(code, 0, stderr)
            rows = json.loads(stdout)["rows"]
            self.assertEqual({row["variant"] for row in rows}, {"scenario", "cheap"})
            self.assertEqual(len({row["route_id"] for row in rows}), 4)
            code, stdout, stderr = run_cli("project", "show-variant", project, "--variant", "cheap", "--format", "json")
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout)["rows"], [
                {"section": "route fictional-correspondent-style", "field": "fixed_fee_send", "base": "5", "variant": "1"},
            ])
            code, stdout, stderr = run_cli("project", "run-variants", project, "--experiment", "dl", "--format", "json")
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout)["status"], "pass")
            self.assertEqual((project / "inputs" / "scenario.json").read_bytes(), scenario_bytes)

    def test_duplicate_route_ids_across_saved_routes_exit_2(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = example_project(Path(temporary))
            # Re-create the project with a folder holding two copies of one route.
            shutil.rmtree(project)
            inputs = project / "inputs"
            (inputs / "routes").mkdir(parents=True)
            shutil.copyfile(EXAMPLE / "scenario.json", inputs / "scenario.json")
            for name in ("a.json", "b.json"):
                shutil.copyfile(EXAMPLE / "routes" / "linked-instant.json", inputs / "routes" / name)
            code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-duplicate",
                                      "--scenario", inputs / "scenario.json", "--routes", inputs / "routes",
                                      "--experiment", "dl:deadline-target:probability=0.9")
            self.assertEqual(code, 0, stderr)
            for command in (("project", "run", project), ("project", "compare-variants", project)):
                with self.subTest(command=command[1]):
                    code, _, stderr = run_cli(*command)
                    self.assertEqual(code, 2)
                    self.assertIn("duplicate route_id", stderr)
                    self.assertNotIn("Traceback", stderr)

    def test_embedded_routes_still_win_over_saved_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            inputs = project / "inputs"
            (inputs / "routes").mkdir(parents=True)
            scenario_path = inputs / "scenario.json"
            scenario_path.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8", newline="\n")
            (inputs / "routes" / "other.json").write_text(json.dumps(route("fictional-saved")), encoding="utf-8", newline="\n")
            code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-embedded",
                                      "--scenario", scenario_path, "--routes", inputs / "routes",
                                      "--experiment", "dl:deadline-target:probability=0.5")
            self.assertEqual(code, 0, stderr)
            run_cli("project", "add-variant", project, "--variant", "slow", "--changes", "transaction.deadline_hours=1")
            code, stdout, _ = run_cli("project", "run", project, "--format", "json")
            self.assertEqual(code, 0)
            # The 0.3.0 result: the embedded route only, the saved folder unused.
            expected_run = deadline_target(load_scenario(scenario_path), "0.5")
            self.assertEqual(json.loads(stdout)["items"][0]["report"], json.loads(json.dumps(expected_run)))
            code, stdout, _ = run_cli("project", "compare-variants", project, "--format", "json")
            self.assertEqual(code, 0)
            from corridor_lab.projects import load_project

            loaded = load_project(project)
            raw = json.loads(scenario_path.read_text(encoding="utf-8"))
            expected_compare = variant_comparison(raw, dict(loaded.manifest.derived_variants), "fictional-embedded")
            self.assertEqual(json.loads(stdout), json.loads(json.dumps(expected_compare)))
            self.assertEqual({row["route_id"] for row in json.loads(stdout)["rows"]}, {"fictional-embedded"})
            self.assertEqual(
                [item["route_id"] for item in evaluate_scenario(load_scenario(scenario_path))["routes"]],
                ["fictional-embedded"],
            )


class SavedRoutesControllerTests(unittest.TestCase):
    def test_open_project_runs_experiments_and_route_variants_on_saved_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = example_project(root)
            original = (project / "inputs" / "scenario.json").read_bytes()
            controller = CorridorGuiController()
            opened = controller.open_project(project)
            self.assertIsNone(opened.error)
            self.assertTrue(opened.report["saved_routes_stand_in"])
            self.assertEqual(len(controller.scenario.routes), 4)
            self.assertEqual(len(controller.selected_routes), 4)
            run = controller.run_saved_experiment("dl")
            self.assertIsNone(run.error)
            added = controller.add_variant("cheap", {"routes": {"fictional-linked-instant": {"fixed_fee_send": "1"}}})
            self.assertIsNone(added.error)
            self.assertIsNone(controller.apply_variant("cheap").error)
            self.assertIsNone(controller.compare_variants().error)
            destination = root / "saved"
            destination.mkdir()
            controller.scenario_file = project / "inputs" / "scenario.json"
            saved = controller.save_project(destination, "fictional-resaved")
            self.assertIsNone(saved.error)
            self.assertEqual((destination / "inputs" / "scenario.json").read_bytes(), original)
            self.assertEqual((project / "inputs" / "scenario.json").read_bytes(), original)

    def test_open_project_with_embedded_routes_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            inputs = project / "inputs"
            (inputs / "routes").mkdir(parents=True)
            scenario_path = inputs / "scenario.json"
            scenario_path.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8", newline="\n")
            (inputs / "routes" / "other.json").write_text(json.dumps(route("fictional-saved")), encoding="utf-8", newline="\n")
            code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-embedded",
                                      "--scenario", scenario_path, "--routes", inputs / "routes")
            self.assertEqual(code, 0, stderr)
            controller = CorridorGuiController()
            opened = controller.open_project(project)
            self.assertIsNone(opened.error)
            self.assertFalse(opened.report["saved_routes_stand_in"])
            self.assertEqual([item.route_id for item in controller.scenario.routes], ["fictional-embedded"])
            self.assertEqual([item.route_id for item in controller.selected_routes], ["fictional-saved"])


if __name__ == "__main__":
    unittest.main()
