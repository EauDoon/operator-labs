"""tracecanary project refresh accepts deliberately edited inputs after validating them."""

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from support import make_directory_link, remove_directory_link, run_cli, write_fixture, write_json
from tracecanary.fixture import bundle
from tracecanary.project import PROJECT_MANIFEST_NAME, load_project, refresh_project


def make_project(root: Path) -> Path:
    project = root / "project"
    inputs = project / "inputs"
    write_fixture(inputs / "contract.json", "contract.json")
    write_fixture(inputs / "input.json", "safe-export.json")
    write_fixture(inputs / "baseline.json", "safe-export.json")
    write_fixture(inputs / "candidate.json", "missing-operational-fields.json")
    write_fixture(inputs / "exports" / "a.json", "safe-export.json")
    code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-refresh",
                              "--contract", inputs / "contract.json", "--input", inputs / "input.json",
                              "--baseline", inputs / "baseline.json", "--candidate", inputs / "candidate.json",
                              "--batch-dir", inputs / "exports", "--batch-minimum-ratio", "0.5",
                              "--population-scope", "span", "--population-minimum", "1")
    assert code == 0, stderr
    return project


def without_digests(project: Path) -> dict:
    document = json.loads((project / PROJECT_MANIFEST_NAME).read_text(encoding="utf-8"))
    for key in ("contract", "input", "baseline", "candidate", "batch"):
        document[key].pop("sha256")
    return document


def reformat(path: Path) -> None:
    write_json(path, json.loads(path.read_text(encoding="utf-8")), indent=2)


class RefreshTests(unittest.TestCase):
    def test_a_deliberate_contract_edit_is_accepted_after_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            before = without_digests(project)
            contract_path = project / "inputs" / "contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["canaries"].append({"label": "added-canary", "category": "prompt", "value": "TCANARY_0123456789abcdef01"})
            write_json(contract_path, contract)
            code, _, stderr = run_cli("project", "validate", project)
            self.assertEqual(code, 2)
            self.assertIn("contract: inputs/contract.json changed since the project was saved", stderr)
            code, stdout, stderr = run_cli("project", "refresh", project, "--input", "contract")
            self.assertEqual(code, 0, stderr)
            self.assertEqual(stdout, f"contract: inputs/contract.json refreshed\nManifest updated: {project / PROJECT_MANIFEST_NAME}\n")
            self.assertEqual(run_cli("project", "validate", project)[0], 0)
            self.assertEqual(without_digests(project), before)

    def test_every_label_refreshes_and_output_carries_no_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            inputs = project / "inputs"
            for name in ("contract.json", "input.json", "baseline.json", "candidate.json", "exports/a.json"):
                reformat(inputs / name)
            arguments = [part for label in ("contract", "input", "baseline", "candidate", "batch") for part in ("--input", label)]
            code, stdout, stderr = run_cli("project", "refresh", project, *arguments)
            self.assertEqual(code, 0, stderr)
            self.assertEqual(stdout.count(" refreshed\n"), 5)
            self.assertIsNone(re.search(r"[0-9a-f]{12}", stdout + stderr))
            self.assertEqual(run_cli("project", "validate", project)[0], 0)

    def test_an_unchanged_input_keeps_the_manifest_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            before = (project / PROJECT_MANIFEST_NAME).read_bytes()
            code, stdout, _ = run_cli("project", "refresh", project, "--input", "contract", "--input", "batch")
            self.assertEqual(code, 0)
            self.assertEqual(stdout, "contract: inputs/contract.json unchanged\nbatch: inputs/exports unchanged\n")
            self.assertEqual((project / PROJECT_MANIFEST_NAME).read_bytes(), before)

    def test_inputs_that_fail_their_validator_are_refused(self):
        cases = (
            ("contract", "contract.json", {"contract_version": "tracecanary/v1"}, "does not validate"),
            ("input", "input.json", {"resourceSpans": "not a list"}, "does not validate"),
            ("baseline", "baseline.json", bundle()["leaked-prompt.json"], "does not satisfy the contract"),
        )
        for label, name, value, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                project = make_project(Path(temporary))
                before = (project / PROJECT_MANIFEST_NAME).read_bytes()
                write_json(project / "inputs" / name, value)
                code, stdout, stderr = run_cli("project", "refresh", project, "--input", label)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn(f"{label}: inputs/{name} {message}", stderr)
                self.assertIn("manifest left unchanged", stderr)
                self.assertEqual((project / PROJECT_MANIFEST_NAME).read_bytes(), before)
                canaries = [item["value"] for item in bundle()["contract.json"]["canaries"]]
                self.assertFalse(any(value in stderr for value in canaries))

    def test_leaking_candidates_and_failing_batch_exports_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            write_fixture(project / "inputs" / "candidate.json", "leaked-prompt.json")
            write_fixture(project / "inputs" / "exports" / "b.json", "leaked-tool-arguments.json")
            code, stdout, stderr = run_cli("project", "refresh", project, "--input", "candidate", "--input", "batch")
            self.assertEqual(code, 0, stderr)
            self.assertIn("candidate: inputs/candidate.json refreshed", stdout)
            self.assertIn("batch: inputs/exports refreshed", stdout)
            self.assertEqual(run_cli("campaign", "run", project)[0], 1)

    def test_an_unnamed_modified_input_blocks_and_is_named(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            before = (project / PROJECT_MANIFEST_NAME).read_bytes()
            reformat(project / "inputs" / "input.json")
            reformat(project / "inputs" / "candidate.json")
            code, _, stderr = run_cli("project", "refresh", project, "--input", "input")
            self.assertEqual(code, 2)
            self.assertIn("candidate: inputs/candidate.json changed since the project was saved", stderr)
            self.assertNotIn("input: inputs/input.json", stderr)
            self.assertEqual((project / PROJECT_MANIFEST_NAME).read_bytes(), before)

    def test_unknown_undeclared_and_repeated_labels_exit_2(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = make_project(root)
            before = (project / PROJECT_MANIFEST_NAME).read_bytes()
            for labels, message in ((("scenario",), "unknown refresh input label"),
                                    (("contract", "contract"), "repeated")):
                arguments = [part for label in labels for part in ("--input", label)]
                code, _, stderr = run_cli("project", "refresh", project, *arguments)
                self.assertEqual(code, 2)
                self.assertIn(message, stderr)
            self.assertEqual((project / PROJECT_MANIFEST_NAME).read_bytes(), before)
            bare = root / "bare"
            write_fixture(bare / "contract.json", "contract.json")
            run_cli("project", "create", "--directory", bare, "--project-id", "bare", "--contract", bare / "contract.json")
            for label in ("input", "baseline", "candidate", "batch"):
                code, _, stderr = run_cli("project", "refresh", bare, "--input", label)
                self.assertEqual(code, 2)
                self.assertIn(f"{label}: the project manifest declares no such input", stderr)

    def test_a_refreshed_contract_the_baseline_no_longer_satisfies_warns(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            contract_path = project / "inputs" / "contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["required_retained_fields"].append({"scope": "span", "key": "fictional.never.present"})
            write_json(contract_path, contract)
            code, _, stderr = run_cli("project", "refresh", project, "--input", "contract")
            self.assertEqual(code, 0, stderr)
            self.assertIn("TraceCanary: WARNING: baseline: inputs/baseline.json no longer satisfies the refreshed contract", stderr)

    def test_a_named_input_reached_through_a_directory_link_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = make_project(root)
            outside = root / "outside"
            shutil.move(str(project / "inputs"), str(outside))
            if not make_directory_link(project / "inputs", outside):
                self.skipTest("this account can create neither directory symlinks nor junctions")
            try:
                before = (project / PROJECT_MANIFEST_NAME).read_bytes()
                code, _, stderr = run_cli("project", "refresh", project, "--input", "contract")
                self.assertEqual(code, 2)
                self.assertIn("contract: inputs/contract.json resolves outside the project directory", stderr)
                self.assertEqual((project / PROJECT_MANIFEST_NAME).read_bytes(), before)
            finally:
                remove_directory_link(project / "inputs")

    def test_library_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            reformat(project / "inputs" / "baseline.json")
            result = refresh_project(project, ["baseline"])
            self.assertEqual((result.problems, result.written), ((), True))
            self.assertEqual([(item.label, item.changed) for item in result.outcomes], [("baseline", True)])
            self.assertEqual(load_project(project).problems, ())


if __name__ == "__main__":
    unittest.main()
