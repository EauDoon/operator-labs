"""A failed project create or desktop save removes only what it copied."""

import tempfile
import unittest
from pathlib import Path

from support import run_cli, snapshot, write_fixture
from tracecanary.gui_controller import TraceCanaryController


def _sources(root: Path) -> dict[str, Path]:
    contract = write_fixture(root / "src" / "contract.json", "contract.json")
    safe = write_fixture(root / "src" / "x.json", "safe-export.json")
    other = write_fixture(root / "other" / "x.json", "missing-operational-fields.json")
    write_fixture(root / "src" / "exports" / "a.json", "safe-export.json")
    write_fixture(root / "src" / "exports" / "nested" / "b.json", "safe-export.json")
    return {"contract": contract, "safe": safe, "other": other, "exports": root / "src" / "exports"}


class FailedCreateTests(unittest.TestCase):
    def test_every_failed_create_leaves_the_directory_as_it_was_and_a_retry_works(self):
        cases = (
            ("bad id", ("--project-id", "bad id!")),
            ("bad ratio", ("--minimum-ratio", "2")),
            ("bad batch ratio", ("--batch-minimum-ratio", "2")),
            ("half gate", ("--population-minimum", "1000")),
            ("bad gate minimum", ("--population-scope", "span", "--population-minimum", "0")),
            ("long description", ("--description", "x" * 201)),
            ("colliding names", ("--candidate", "OTHER")),
        )
        for label, extra in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paths = _sources(root)
                project = root / "project"
                (project / "inputs").mkdir(parents=True)
                (project / "inputs" / "notes.txt").write_text("kept", encoding="utf-8")
                before = snapshot(project)
                arguments = [str(paths["other"]) if item == "OTHER" else item for item in extra]
                base = ["project", "create", "--directory", project, "--contract", paths["contract"],
                        "--input", paths["safe"], "--batch-dir", paths["exports"], "--batch-recursive"]
                if "--project-id" not in arguments:
                    base += ["--project-id", "fictional-retry"]
                code, _, stderr = run_cli(*base, *arguments)
                self.assertEqual(code, 2, stderr)
                self.assertEqual(snapshot(project), before)
                code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-retry",
                                          "--contract", paths["contract"], "--input", paths["safe"],
                                          "--batch-dir", paths["exports"], "--batch-recursive")
                self.assertEqual(code, 0, stderr)
                self.assertEqual(run_cli("project", "validate", project)[0], 0)
                self.assertEqual((project / "inputs" / "notes.txt").read_text(encoding="utf-8"), "kept")

    def test_a_failed_create_removes_an_inputs_folder_it_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _sources(root)
            project = root / "project"
            project.mkdir()
            code, _, _ = run_cli("project", "create", "--directory", project, "--project-id", "fictional",
                                 "--contract", paths["contract"], "--input", paths["safe"],
                                 "--batch-dir", paths["exports"], "--batch-recursive", "--candidate", paths["other"])
            self.assertEqual(code, 2)
            self.assertEqual(snapshot(project), {})

    def test_a_reused_identical_copy_is_never_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _sources(root)
            project = root / "project"
            write_fixture(project / "inputs" / "contract.json", "contract.json")
            before = snapshot(project)
            code, _, _ = run_cli("project", "create", "--directory", project, "--project-id", "fictional",
                                 "--contract", paths["contract"], "--input", paths["safe"], "--candidate", paths["other"])
            self.assertEqual(code, 2)
            self.assertEqual(snapshot(project), before)


class FailedDesktopSaveTests(unittest.TestCase):
    def test_a_failed_desktop_save_project_rolls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _sources(root)
            project = root / "project"
            project.mkdir()
            controller = TraceCanaryController()
            settings = dict(
                description="", contract_path=paths["contract"], input_path=paths["safe"], baseline_path=None,
                candidate_path=paths["other"], batch_dir=paths["exports"], batch_recursive=True,
                batch_include_paths=False, batch_minimum_ratio=None, minimum_ratio=None,
                population_scope=None, population_minimum=None,
            )
            result = controller.save_project(project, project_id="fictional-desktop", **settings)
            self.assertEqual(result.exit_code, 2)
            self.assertEqual(snapshot(project), {})
            settings["candidate_path"] = None
            settings["minimum_ratio"] = "2"
            result = controller.save_project(project, project_id="fictional-desktop", **settings)
            self.assertEqual(result.exit_code, 2)
            self.assertEqual(snapshot(project), {})
            settings["minimum_ratio"] = None
            result = controller.save_project(project, project_id="fictional-desktop", **settings)
            self.assertEqual(result.exit_code, 0, result.human)
            self.assertEqual(run_cli("project", "validate", project)[0], 0)


if __name__ == "__main__":
    unittest.main()
