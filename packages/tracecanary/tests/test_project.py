import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.fixture import bundle
from tracecanary.project import (
    PROJECT_MANIFEST_NAME,
    PROJECT_MANIFEST_VERSION,
    build_manifest,
    load_project,
    parse_manifest,
    write_project,
)


def make_project(root: Path, *, minimum_ratio: str | None = "0.95") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    files = bundle()
    for name in ("contract.json", "safe-export.json", "missing-operational-fields.json", "sparse-retention.json"):
        (root / "inputs").mkdir(exist_ok=True)
        (root / "inputs" / name).write_text(json.dumps(files[name]), encoding="utf-8", newline="\n")
    batch = root / "batch"
    batch.mkdir(exist_ok=True)
    (batch / "safe.json").write_text(json.dumps(files["safe-export.json"]), encoding="utf-8", newline="\n")
    (batch / "leak.json").write_text(json.dumps(files["leaked-prompt.json"]), encoding="utf-8", newline="\n")
    manifest = build_manifest(
        root,
        project_id="fictional-campaign",
        description="A synthetic privacy investigation.",
        contract=root / "inputs" / "contract.json",
        input=root / "inputs" / "safe-export.json",
        baseline=root / "inputs" / "safe-export.json",
        candidate=root / "inputs" / "missing-operational-fields.json",
        batch=batch,
        batch_recursive=False,
        batch_include_paths=True,
        batch_minimum_ratio=minimum_ratio,
        minimum_ratio=minimum_ratio,
        population_scope="span",
        population_minimum=1,
    )
    write_project(root, manifest)
    return root / PROJECT_MANIFEST_NAME


class ProjectManifestTests(unittest.TestCase):
    def test_manifest_round_trips_and_strictly_validates(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = make_project(Path(temporary))
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(value["project_version"], PROJECT_MANIFEST_VERSION)
            self.assertEqual(value["batch"]["minimum_ratio"], "0.95")
            self.assertEqual(value["coverage"]["minimum_ratio"], "0.95")
            self.assertEqual(value["coverage"]["population_scope"], "span")
            parsed = parse_manifest(value)
            self.assertEqual(parsed.project_id, "fictional-campaign")

    def test_unknown_manifest_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = make_project(Path(temporary))
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["unexpected"] = True
            with self.assertRaisesRegex(Exception, "unsupported or missing fields"):
                parse_manifest(value)

    def test_manifest_rejects_absolute_paths_and_bad_thresholds(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = make_project(Path(temporary))
            base = json.loads(manifest_path.read_text(encoding="utf-8"))
            for damaged in ({"contract": {"path": "/etc/passwd", "sha256": base["contract"]["sha256"]}},
                            {"coverage": {"minimum_ratio": "0.1234567"}}):
                with self.subTest(damaged=damaged):
                    broken = json.loads(json.dumps(base))
                    broken.update(damaged)
                    with self.assertRaises(Exception):
                        parse_manifest(broken)


class ProjectResolutionTests(unittest.TestCase):
    def test_open_reports_ok_and_resolved_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = make_project(root)
            loaded = load_project(manifest_path)
            self.assertTrue(loaded.ok)
            self.assertEqual(loaded.resolved["contract"], root / "inputs" / "contract.json")
            self.assertEqual(loaded.resolved["batch directory"], root / "batch")

    def test_moving_the_directory_keeps_the_project_portable(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "original"
            make_project(source)
            moved = Path(temporary) / "moved"
            os.rename(source, moved)
            loaded = load_project(moved / PROJECT_MANIFEST_NAME)
            self.assertTrue(loaded.ok)
            self.assertEqual(loaded.resolved["candidate"], moved / "inputs" / "missing-operational-fields.json")

    def test_missing_and_changed_inputs_are_reported_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = make_project(root)
            (root / "inputs" / "contract.json").unlink()
            loaded = load_project(manifest_path)
            self.assertFalse(loaded.ok)
            self.assertIn("missing input inputs/contract.json", loaded.problems[0])
            (root / "batch" / "extra.json").write_text(json.dumps(bundle()["safe-export.json"]), encoding="utf-8")
            loaded = load_project(manifest_path)
            self.assertTrue(any("batch directory" in problem and "changed" in problem for problem in loaded.problems))

    def test_write_refuses_to_replace_an_existing_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = make_project(root)
            manifest = parse_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
            with self.assertRaisesRegex(Exception, "already exists"):
                write_project(root, manifest)


class ProjectCliTests(unittest.TestCase):
    def test_project_cli_create_validate_open(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            source = Path(temporary) / "source"
            source.mkdir()
            files = bundle()
            contract = source / "contract.json"
            contract.write_text(json.dumps(files["contract.json"]), encoding="utf-8")
            safe = source / "safe-export.json"
            safe.write_text(json.dumps(files["safe-export.json"]), encoding="utf-8")
            batch = source / "batch"
            batch.mkdir()
            (batch / "one.json").write_text(json.dumps(files["safe-export.json"]), encoding="utf-8")
            from tracecanary.cli import main

            project = Path(temporary) / "investigation"
            project.mkdir()
            code = main(["project", "create", "--directory", str(project), "--project-id", "fictional-project",
                         "--contract", str(contract), "--input", str(safe), "--batch-dir", str(batch),
                         "--minimum-ratio", "0.95", "--population-scope", "span", "--population-minimum", "1"])
            self.assertEqual(code, 0)
            self.assertTrue((project / PROJECT_MANIFEST_NAME).exists())
            self.assertTrue((project / "inputs" / "safe-export.json").exists())
            self.assertEqual(main(["project", "validate", str(project)]), 0)
            self.assertEqual(main(["project", "open", str(project)]), 0)

    def test_promote_baseline_validates_first_and_updates_the_manifest(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            from tracecanary.cli import main

            root = Path(temporary)
            manifest_path = make_project(root)
            leaked = root / "leaked.json"
            leaked.write_text(json.dumps(bundle()["leaked-prompt.json"]), encoding="utf-8")
            self.assertEqual(main(["project", "promote-baseline", str(root), "--candidate", str(leaked)]), 2)
            baseline_before = json.loads(manifest_path.read_text(encoding="utf-8"))["baseline"]["sha256"]
            safe = root / "safe.json"
            safe.write_text(json.dumps(bundle()["safe-export.json"]), encoding="utf-8")
            self.assertEqual(main(["project", "promote-baseline", str(root), "--candidate", str(safe)]), 0)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["baseline"]["path"], "safe.json")
            self.assertEqual(manifest["baseline"]["sha256"], __import__("hashlib").sha256(safe.read_bytes()).hexdigest())
            self.assertEqual(main(["project", "validate", str(root)]), 0)

    def test_project_cli_rejects_unknown_analysis_and_reports_missing_inputs(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            from tracecanary.cli import main

            project = Path(temporary) / "investigation"
            project.mkdir()
            self.assertEqual(main(["project", "create", "--directory", str(project), "--project-id", "fictional",
                                   "--contract", str(project / "nope.json")]), 2)
            manifest_path = make_project(Path(temporary) / "complete")
            (Path(temporary) / "complete" / "inputs" / "contract.json").unlink()
            self.assertEqual(main(["project", "validate", str(manifest_path)]), 2)
            self.assertEqual(main(["project", "open", str(manifest_path)]), 2)


if __name__ == "__main__":
    unittest.main()
