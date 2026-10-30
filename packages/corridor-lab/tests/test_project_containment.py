"""load_project refuses inputs that resolve outside the project directory."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from corridor_lab.cli import main as cli_main
from corridor_lab.gui_controller import CorridorGuiController
from corridor_lab.projects import PROJECT_MANIFEST_NAME, build_manifest, experiment_from_cli, load_project, write_project
from helpers import make_directory_link, remove_directory_link, route, scenario


def _quiet(*args: str) -> tuple[int, str]:
    stderr = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
        code = cli_main(list(args))
    return code, stderr.getvalue()


def _project(root: Path) -> Path:
    project = root / "project"
    inputs = project / "inputs"
    inputs.mkdir(parents=True)
    scenario_path = inputs / "scenario.json"
    scenario_path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8", newline="\n")
    manifest = build_manifest(
        project,
        project_id="fictional-contained",
        scenario=scenario_path,
        experiments=(experiment_from_cli("deadline", "deadline-target", probability="0.5"),),
    )
    write_project(project, manifest)
    return project


class LinkedInputDirectoryTests(unittest.TestCase):
    def test_inputs_reached_through_a_directory_link_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _project(root)
            outside = root / "outside"
            shutil.move(str(project / "inputs"), str(outside))
            if not make_directory_link(project / "inputs", outside):
                self.skipTest("this account can create neither directory symlinks nor junctions")
            try:
                loaded = load_project(project)
                self.assertEqual(
                    loaded.problems,
                    ("scenario: inputs/scenario.json resolves outside the project directory",),
                )
                self.assertNotIn("scenario", loaded.resolved)
                for command in (("project", "validate", str(project)), ("project", "open", str(project)),
                                ("project", "run", str(project))):
                    with self.subTest(command=command[1]):
                        code, stderr = _quiet(*command)
                        self.assertEqual(code, 2)
                        self.assertIn("resolves outside the project directory", stderr)
                result = CorridorGuiController().open_project(project)
                self.assertIsNotNone(result.error)
                self.assertIn("resolves outside the project directory", result.error)
            finally:
                remove_directory_link(project / "inputs")
            self.assertTrue((outside / "scenario.json").is_file())

    def test_ordinary_and_moved_projects_stay_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _project(root)
            self.assertEqual(load_project(project).problems, ())
            moved = root / "moved"
            project.rename(moved)
            self.assertEqual(load_project(moved).problems, ())
            self.assertEqual(_quiet("project", "validate", str(moved))[0], 0)


@unittest.skipUnless(os.name == "nt", "drive-relative paths exist only on Windows")
class DriveRelativeReferenceTests(unittest.TestCase):
    def test_a_drive_relative_reference_is_refused_from_relative_and_absolute_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            project = _project(root)
            outside = root / "outside"
            outside.mkdir()
            shutil.copyfile(project / "inputs" / "scenario.json", outside / "scenario.json")
            manifest_path = project / PROJECT_MANIFEST_NAME
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            document["scenario"]["path"] = f"{root.drive}outside/scenario.json"
            manifest_path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
            previous = Path.cwd()
            os.chdir(root)
            try:
                for argument in ("project", str(project)):
                    with self.subTest(argument=argument):
                        loaded = load_project(argument)
                        self.assertEqual(len(loaded.problems), 1)
                        self.assertIn("is not a portable relative project path", loaded.problems[0])
                        self.assertNotIn("scenario", loaded.resolved)
                        code, stderr = _quiet("project", "validate", argument)
                        self.assertEqual(code, 2)
                        self.assertIn("is not a portable relative project path", stderr)
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
