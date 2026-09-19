import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.batching import run_batch
from tracecanary.contract import parse_contract
from tracecanary.cli import main
from tracecanary.fixture import bundle


class BatchPopulationGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.files = bundle()
        cls.contract = parse_contract(cls.files["contract.json"])
        for name, data in cls.files.items():
            (cls.root / name).write_text(json.dumps(data), encoding="utf-8", newline="\n")

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def test_gate_applies_to_every_valid_file_without_duplicating_findings(self):
        report = run_batch(self.contract, self.root, False, False, None, coverage=False,
                           population_scope="link", population_minimum=3)
        valid_items = [item for item in report["items"] if "population_gate" in item["report"]]
        self.assertEqual(len(valid_items), 9)  # every structurally valid export
        for item in valid_items:
            self.assertEqual(item["report"]["population_gate"]["scope"], "link")
            self.assertEqual(item["report"]["population_gate"]["observed"], 0)
        codes = {v["code"] for item in valid_items if item["id"] == "item-0002" for v in item["report"]["violations"]}
        self.assertEqual(codes, {"TC003", "TC013"})  # leak stays, gate added, no duplicates
        unresolved = [item for item in report["items"] if item["status"] == "unresolved"]
        self.assertEqual(len(unresolved), 2)  # contract.json and invalid-export.json stay unresolved
        self.assertEqual(report["status"], "unresolved")

    def test_gate_passes_when_population_is_sufficient(self):
        report = run_batch(self.contract, self.root, False, False, None, coverage=False,
                           population_scope="span", population_minimum=1)
        safe_item = next(item for item in report["items"] if item["id"] == "item-0001")
        self.assertEqual(safe_item["status"], "unresolved")  # contract.json is not a trace
        leak_item = next(item for item in report["items"] if "leaked-prompt" in (item.get("path") or "") or item["id"] == "item-0002")
        self.assertIn("TC003", {v["code"] for v in leak_item["report"]["violations"]})
        gate_codes = {v["code"] for item in report["items"] for v in item["report"].get("violations", []) if v["code"] == "TC013"}
        self.assertEqual(gate_codes, set())  # span minimum 1 is met everywhere valid

    def test_gate_with_no_scope_or_minimum_is_ignored(self):
        report = run_batch(self.contract, self.root, False, False, None, population_scope=None, population_minimum=None)
        self.assertTrue(all("population_gate" not in item["report"] for item in report["items"]))

    def test_cli_agrees_with_library_for_gated_batch(self):
        from tracecanary.cli import main

        output = self.root.parent / "gated-batch.json"
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = main(["batch", "--contract", str(self.root / "contract.json"), "--input-dir", str(self.root),
                         "--population-scope", "link", "--population-minimum", "3", "--format", "json", "--output", str(output)])
        self.assertEqual(code, 2)  # the directory contains unresolved inputs; precedence applies
        cli_report = json.loads(output.read_text(encoding="utf-8"))
        library = run_batch(self.contract, self.root, False, False, None, population_scope="link", population_minimum=3)
        self.assertEqual(cli_report, library)

    def test_cli_requires_minimum_with_scope(self):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = main(["batch", "--contract", str(self.root / "contract.json"), "--input-dir", str(self.root),
                         "--population-scope", "link"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
