"""A population gate needs both a scope and a minimum on every surface."""

import json
import tempfile
import unittest
from pathlib import Path

from support import run_cli, write_fixture
from tracecanary.batching import run_batch
from tracecanary.campaign import run_campaign
from tracecanary.canonical import InputError
from tracecanary.contract import load_contract
from tracecanary.project import PROJECT_MANIFEST_NAME

MESSAGE = "a population gate needs both a scope and a minimum"


def _inputs(root: Path) -> tuple[Path, Path]:
    contract = write_fixture(root / "contract.json", "contract.json")
    exports = root / "exports"
    write_fixture(exports / "a.json", "safe-export.json")
    write_fixture(exports / "b.json", "safe-export.json")
    return contract, exports


class BatchSurfaceTests(unittest.TestCase):
    def test_batch_and_coverage_batch_refuse_half_a_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            contract, exports = _inputs(Path(temporary))
            for command in ("batch", "coverage-batch"):
                base = (command, "--contract", contract, "--input-dir", exports)
                for half in (("--population-minimum", "1000"), ("--population-scope", "span")):
                    with self.subTest(command=command, half=half[0]):
                        code, stdout, stderr = run_cli(*base, *half)
                        self.assertEqual(code, 2)
                        self.assertEqual(stdout, "")
                        self.assertIn(MESSAGE, stderr)
                with self.subTest(command=command, half="both"):
                    code, stdout, _ = run_cli(*base, "--population-scope", "span", "--population-minimum", "1000")
                    self.assertEqual(code, 1)
                    self.assertIn("TC013", stdout)

    def test_library_batch_and_campaign_refuse_half_a_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            contract_path, exports = _inputs(Path(temporary))
            contract = load_contract(contract_path)
            for scope, minimum in (("span", None), (None, 5)):
                with self.subTest(scope=scope, minimum=minimum):
                    with self.assertRaisesRegex(InputError, MESSAGE):
                        run_batch(contract, exports, False, False, population_scope=scope, population_minimum=minimum)
                    with self.assertRaisesRegex(InputError, MESSAGE):
                        run_campaign(contract, batch=exports, population_scope=scope, population_minimum=minimum)


class ProjectSurfaceTests(unittest.TestCase):
    def _create(self, root: Path, *extra: str) -> tuple[int, str, Path]:
        contract, _ = _inputs(root / "sources")
        project = root / "project"
        project.mkdir()
        code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-gate",
                                  "--contract", contract, *extra)
        return code, stderr, project

    def test_project_create_refuses_half_a_gate(self):
        for half in (("--population-minimum", "1000"), ("--population-scope", "span")):
            with self.subTest(half=half[0]), tempfile.TemporaryDirectory() as temporary:
                code, stderr, project = self._create(Path(temporary), *half)
                self.assertEqual(code, 2)
                self.assertIn("population", stderr)
                self.assertFalse((project / PROJECT_MANIFEST_NAME).exists())

    def test_campaign_run_refuses_a_half_gate_after_merging_saved_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, stderr, project = self._create(root, "--input", str(write_fixture(root / "in.json", "safe-export.json")))
            self.assertEqual(code, 0, stderr)
            for half in (("--population-minimum", "1000"), ("--population-scope", "span")):
                with self.subTest(half=half[0]):
                    code, stdout, stderr = run_cli("campaign", "run", project, *half)
                    self.assertEqual(code, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn(MESSAGE, stderr)
            code, stdout, _ = run_cli("campaign", "run", project, "--population-scope", "span", "--population-minimum", "1000")
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stdout)["phases"]["population_gate"]["status"], "regression")

    def test_overriding_one_half_of_a_saved_gate_still_works(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, stderr, project = self._create(
                root, "--input", str(write_fixture(root / "in.json", "safe-export.json")),
                "--population-scope", "span", "--population-minimum", "1",
            )
            self.assertEqual(code, 0, stderr)
            code, stdout, _ = run_cli("campaign", "run", project)
            self.assertEqual(code, 0)
            code, stdout, _ = run_cli("campaign", "run", project, "--population-minimum", "1000")
            self.assertEqual(code, 1)
            gate = json.loads(stdout)["phases"]["population_gate"]
            self.assertEqual((gate["scope"], gate["minimum"]), ("span", 1000))
            code, stdout, _ = run_cli("campaign", "run", project, "--population-scope", "resource")
            self.assertEqual(json.loads(stdout)["phases"]["population_gate"]["scope"], "resource")


if __name__ == "__main__":
    unittest.main()
