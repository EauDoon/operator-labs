import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.fixture import bundle
from tracecanary.gui_controller import TraceCanaryController
from tracecanary.project import PROJECT_MANIFEST_NAME


def build_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    files = bundle()
    for name in ("contract.json", "safe-export.json", "missing-operational-fields.json", "sparse-retention.json"):
        (root / "inputs").mkdir(exist_ok=True)
        (root / "inputs" / name).write_text(json.dumps(files[name]), encoding="utf-8", newline="\n")
    batch = root / "batch"
    batch.mkdir(exist_ok=True)
    (batch / "safe.json").write_text(json.dumps(files["safe-export.json"]), encoding="utf-8", newline="\n")
    from tracecanary.cli import main

    with redirect_stdout(StringIO()):
        code = main(["project", "create", "--directory", str(root), "--project-id", "fictional-gui-project",
                     "--contract", str(root / "inputs" / "contract.json"),
                     "--input", str(root / "inputs" / "safe-export.json"),
                     "--baseline", str(root / "inputs" / "safe-export.json"),
                     "--candidate", str(root / "inputs" / "missing-operational-fields.json"),
                     "--batch-dir", str(batch), "--batch-include-paths", "--batch-minimum-ratio", "0.95",
                     "--minimum-ratio", "0.95", "--population-scope", "span", "--population-minimum", "1"])
    assert code == 0
    return root / PROJECT_MANIFEST_NAME


class ControllerProjectTests(unittest.TestCase):
    def test_open_project_prepares_every_selector(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = build_project(Path(temporary))
            controller = TraceCanaryController()
            result = controller.open_project(manifest_path)
            self.assertEqual(result.status, "pass")
            paths = result.project_paths
            self.assertEqual(paths.contract.name, "contract.json")
            self.assertEqual(paths.batch_dir.name, "batch")
            self.assertEqual(paths.coverage[0], "0.95")
            self.assertIn("Saved settings are applied", result.human)
            self.assertNotIn("TCANARY", result.human)
            self.assertNotIn("TCANARY", result.json)

    def test_open_project_reports_missing_inputs_as_unresolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = build_project(root)
            (root / "inputs" / "contract.json").unlink()
            result = TraceCanaryController().open_project(manifest_path)
            self.assertEqual(result.status, "unresolved")
            self.assertIn("missing input", result.human)
            self.assertNotIn("TCANARY", result.human)

    def test_save_project_round_trips_through_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary) / "source"
            manifest_path = build_project(source_root)
            controller = TraceCanaryController()
            opened = controller.open_project(manifest_path)
            self.assertEqual(opened.status, "pass")
            destination = Path(temporary) / "saved"
            destination.mkdir()
            saved = controller.save_project(
                destination,
                project_id="fictional-saved-project",
                description="A saved copy.",
                contract_path=str(source_root / "inputs" / "contract.json"),
                input_path=str(source_root / "inputs" / "safe-export.json"),
                baseline_path=str(source_root / "inputs" / "safe-export.json"),
                candidate_path=str(source_root / "inputs" / "missing-operational-fields.json"),
                batch_dir=str(source_root / "batch"),
                batch_recursive=False,
                batch_include_paths=True,
                batch_minimum_ratio="0.95",
                minimum_ratio="0.95",
                population_scope="span",
                population_minimum=1,
            )
            self.assertEqual(saved.status, "pass")
            reopened = TraceCanaryController().open_project(destination / PROJECT_MANIFEST_NAME)
            self.assertEqual(reopened.status, "pass")
            self.assertEqual(reopened.project_paths.coverage, ("0.95", "span", 1))
            self.assertIsNotNone(reopened.project_paths.batch_dir)

    def test_save_project_refuses_existing_manifest_and_reports_clearly(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary) / "source"
            build_project(source_root)
            controller = TraceCanaryController()
            result = controller.save_project(
                source_root,
                project_id="fictional-duplicate",
                description="",
                contract_path=str(source_root / "inputs" / "contract.json"),
                input_path=None,
                baseline_path=None,
                candidate_path=None,
                batch_dir=None,
                batch_recursive=False,
                batch_include_paths=False,
                batch_minimum_ratio=None,
                minimum_ratio=None,
                population_scope=None,
                population_minimum=None,
            )
            self.assertEqual(result.status, "unresolved")
            self.assertIn("already exists", result.human)


if __name__ == "__main__":
    unittest.main()
