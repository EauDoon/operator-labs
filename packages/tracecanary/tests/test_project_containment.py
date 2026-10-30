"""load_project refuses inputs that resolve outside the project directory."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from support import make_directory_link, remove_directory_link, run_cli, write_fixture
from tracecanary.gui_controller import TraceCanaryController
from tracecanary.project import PROJECT_MANIFEST_NAME, load_project


def _project(root: Path) -> Path:
    project = root / "project"
    inputs = project / "inputs"
    write_fixture(inputs / "contract.json", "contract.json")
    write_fixture(inputs / "safe.json", "safe-export.json")
    write_fixture(inputs / "exports" / "a.json", "safe-export.json")
    code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-contained",
                              "--contract", inputs / "contract.json", "--input", inputs / "safe.json",
                              "--batch-dir", inputs / "exports")
    assert code == 0, stderr
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
                self.assertEqual(loaded.problems, (
                    "contract: inputs/contract.json resolves outside the project directory",
                    "input: inputs/safe.json resolves outside the project directory",
                    "batch directory: inputs/exports resolves outside the project directory",
                ))
                self.assertEqual(loaded.resolved, {})
                for command in (("project", "validate", project), ("project", "open", project),
                                ("campaign", "run", project)):
                    with self.subTest(command=command[:2]):
                        code, _, stderr = run_cli(*command)
                        self.assertEqual(code, 2)
                        self.assertIn("resolves outside the project directory", stderr)
                result = TraceCanaryController().open_project(project)
                self.assertEqual(result.exit_code, 2)
                self.assertIsNone(result.project_paths)
                self.assertIn("resolves outside the project directory", result.human)
            finally:
                remove_directory_link(project / "inputs")
            self.assertTrue((outside / "contract.json").is_file())

    def test_ordinary_and_moved_projects_stay_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _project(root)
            self.assertEqual(load_project(project).problems, ())
            moved = root / "moved"
            project.rename(moved)
            self.assertEqual(load_project(moved).problems, ())
            self.assertEqual(run_cli("project", "validate", moved)[0], 0)


@unittest.skipUnless(os.name == "nt", "drive-relative paths exist only on Windows")
class DriveRelativeReferenceTests(unittest.TestCase):
    def test_a_drive_relative_reference_is_refused_from_relative_and_absolute_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            project = _project(root)
            shutil.copytree(project / "inputs", root / "outside")
            manifest_path = project / PROJECT_MANIFEST_NAME
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            document["contract"]["path"] = f"{root.drive}outside/contract.json"
            manifest_path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
            previous = Path.cwd()
            os.chdir(root)
            try:
                for argument in ("project", str(project)):
                    with self.subTest(argument=argument):
                        loaded = load_project(Path(argument))
                        self.assertEqual(len(loaded.problems), 1)
                        self.assertIn("is not a portable relative project path", loaded.problems[0])
                        self.assertNotIn("contract", loaded.resolved)
                        code, _, stderr = run_cli("project", "validate", argument)
                        self.assertEqual(code, 2)
                        self.assertIn("is not a portable relative project path", stderr)
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
