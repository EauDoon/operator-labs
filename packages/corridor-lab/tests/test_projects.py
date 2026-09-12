import json
import os
import tempfile
import unittest
from pathlib import Path

from corridor_lab.canonical import InputError
from corridor_lab.cli import main as cli_main
from corridor_lab.projects import (
    PROJECT_MANIFEST_NAME,
    PROJECT_MANIFEST_VERSION,
    build_manifest,
    experiment_from_cli,
    load_project,
    make_input_ref,
    manifest_text,
    parse_manifest,
    write_project,
)
from helpers import route, scenario


def build_test_project(root: Path) -> tuple[Path, Path]:
    """Create a self-contained project and return (manifest path, inputs dir)."""
    inputs = root / "inputs"
    inputs.mkdir()
    scenario_path = inputs / "scenario.json"
    routes_path = inputs / "routes"
    baseline_path = inputs / "baseline.json"
    scenario_path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
    routes_path.mkdir()
    (routes_path / "one.json").write_text(json.dumps(route("fictional-route-one")), encoding="utf-8")
    (routes_path / "two.json").write_text(json.dumps(route("fictional-route-two")), encoding="utf-8")
    baseline_path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
    manifest = build_manifest(
        root,
        project_id="fictional-amber-investigation",
        description="A self-contained fictional investigation.",
        scenario=scenario_path,
        routes=routes_path,
        baseline=baseline_path,
        experiments=(experiment_from_cli("deadline-sweep", "transaction-sweep", parameter="deadline_hours", values="1,2,8"),),
    )
    write_project(root, manifest)
    return root / PROJECT_MANIFEST_NAME, inputs


class ProjectManifestTests(unittest.TestCase):
    def test_manifest_round_trips_and_strictly_validates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, _ = build_test_project(root)
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(value["project_version"], PROJECT_MANIFEST_VERSION)
            self.assertEqual(value["scenario"]["path"], "inputs/scenario.json")
            self.assertTrue(value["routes"]["folder"])
            self.assertEqual(value["experiments"][0]["analysis"], "transaction-sweep")
            parsed = parse_manifest(value)
            self.assertEqual(parsed.project_id, "fictional-amber-investigation")
            self.assertEqual(manifest_text(parsed), manifest_path.read_text(encoding="utf-8"))

    def test_unknown_manifest_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, _ = build_test_project(root)
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["unexpected"] = True
            with self.assertRaisesRegex(InputError, "unsupported field"):
                parse_manifest(value)

    def test_manifest_rejects_absolute_and_traversing_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, _ = build_test_project(root)
            base = json.loads(manifest_path.read_text(encoding="utf-8"))
            for replacement in ({"path": "/etc/passwd", "sha256": base["scenario"]["sha256"], "folder": False},
                                {"path": "../outside.json", "sha256": base["scenario"]["sha256"], "folder": False}):
                with self.subTest(path=replacement["path"]):
                    damaged = json.loads(json.dumps(base))
                    damaged["scenario"] = replacement
                    with self.assertRaisesRegex(InputError, "relative project path|forward slashes"):
                        parse_manifest(damaged)

    def test_rejected_unknown_analysis_and_duplicate_experiment_names(self):
        with self.assertRaisesRegex(InputError, "must be one of"):
            experiment_from_cli("bad", "pareto", values="1")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, _ = build_test_project(root)
            base = json.loads(manifest_path.read_text(encoding="utf-8"))
            base["experiments"].append(dict(base["experiments"][0]))
            with self.assertRaisesRegex(InputError, "unique"):
                parse_manifest(base)


class ProjectResolutionTests(unittest.TestCase):
    def test_open_reports_ok_and_resolved_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, _ = build_test_project(root)
            loaded = load_project(manifest_path)
            self.assertTrue(loaded.ok)
            self.assertEqual(loaded.resolved["scenario"], root / "inputs" / "scenario.json")
            self.assertEqual(loaded.resolved["routes"], root / "inputs" / "routes")

    def test_moving_the_directory_keeps_the_project_portable(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "original"
            source.mkdir()
            manifest_path, _ = build_test_project(source)
            moved = Path(temporary) / "moved"
            os.rename(source, moved)
            loaded = load_project(moved / PROJECT_MANIFEST_NAME)
            self.assertTrue(loaded.ok)
            self.assertEqual(loaded.resolved["baseline"], moved / "inputs" / "baseline.json")

    def test_missing_and_changed_inputs_are_reported_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, inputs = build_test_project(root)
            (inputs / "scenario.json").unlink()
            loaded = load_project(manifest_path)
            self.assertFalse(loaded.ok)
            self.assertIn("missing input inputs/scenario.json", loaded.problems[0])
            self.assertEqual(loaded.manifest.project_id, "fictional-amber-investigation")
            (inputs / "scenario.json").write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            (inputs / "baseline.json").write_text(json.dumps(scenario(routes=[route("changed")])), encoding="utf-8")
            loaded = load_project(manifest_path)
            self.assertFalse(loaded.ok)
            self.assertTrue(any("changed since the project was saved" in problem for problem in loaded.problems))

    def test_changed_route_folder_fingerprint_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, inputs = build_test_project(root)
            (inputs / "routes" / "three.json").write_text(json.dumps(route("fictional-route-three")), encoding="utf-8")
            loaded = load_project(manifest_path)
            self.assertFalse(loaded.ok)
            self.assertTrue(any("routes" in problem and "changed" in problem for problem in loaded.problems))

    def test_write_refuses_to_replace_an_existing_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, _ = build_test_project(root)
            manifest = parse_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
            with self.assertRaisesRegex(InputError, "already exists"):
                write_project(root, manifest)


class ProjectCliTests(unittest.TestCase):
    def test_project_cli_create_validate_open_and_run(self):
        with tempfile.TemporaryDirectory() as temporary, __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            scenario_path = inputs / "scenario.json"
            scenario_path.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            project = root / "investigation"
            project.mkdir()
            code = cli_main(["project", "create", "--directory", str(project), "--project-id", "fictional-project",
                             "--description", "A fictional investigation.", "--scenario", str(scenario_path),
                             "--experiment", "deadline-sweep:transaction-sweep:parameter=deadline_hours;values=1,2,8"])
            self.assertEqual(code, 0)
            self.assertTrue((project / PROJECT_MANIFEST_NAME).exists())
            self.assertEqual(cli_main(["project", "validate", str(project)]), 0)
            self.assertEqual(cli_main(["project", "open", str(project)]), 0)
            output = root / "sweep.json"
            self.assertEqual(cli_main(["project", "run", str(project), "--output", str(output)]), 0)
            self.assertIn("corridor-lab.project-run/v1", output.read_text(encoding="utf-8"))
            # inputs are protected: reports cannot replace them
            self.assertEqual(cli_main(["project", "run", str(project), "--output", str(project / "inputs" / "scenario.json")]), 2)
            self.assertEqual(cli_main(["project", "run", str(project), "--output", str(project / "sweep.json")]), 2)

    def test_project_cli_rejects_missing_experiment_fields_and_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temporary, __import__("contextlib").redirect_stdout(__import__("io").StringIO()), __import__("contextlib").redirect_stderr(__import__("io").StringIO()):
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            scenario_path = inputs / "scenario.json"
            scenario_path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            project = root / "investigation"
            project.mkdir()
            self.assertEqual(cli_main(["project", "create", "--directory", str(project), "--project-id", "fictional",
                                       "--scenario", str(scenario_path), "--experiment", "broken:transaction-sweep"]), 2)
            self.assertEqual(cli_main(["project", "create", "--directory", str(project), "--project-id", "fictional",
                                       "--scenario", str(scenario_path), "--experiment", "one:transaction-sweep:parameter=deadline_hours;values=1",
                                       "--experiment", "one:transaction-sweep:parameter=deadline_hours;values=2"]), 2)
            self.assertFalse((project / PROJECT_MANIFEST_NAME).exists())


if __name__ == "__main__":
    unittest.main()
