import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tracecanary.canonical import InputError
from tracecanary.cli import _run_batch
from tracecanary.contract import parse_contract
from tracecanary.fixture import bundle


class BatchBaselineTests(unittest.TestCase):
    def test_retention_loss_detected_across_candidates(self):
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe.json").write_text(json.dumps(fixtures["safe-export.json"]))
            (root / "loss.json").write_text(json.dumps(fixtures["missing-operational-fields.json"]))
            (root / "broken.json").write_text("{")
            report = _run_batch(contract, root, False, False, fixtures["safe-export.json"])
            self.assertEqual(report["status"], "unresolved")
            self.assertEqual([item["status"] for item in report["items"]], ["unresolved", "regression", "pass"])
            self.assertTrue(any(v["code"] == "TC005" for v in report["items"][1]["report"]["violations"]))
            self.assertNotIn(directory, json.dumps(report))
            with self.assertRaises(InputError):
                _run_batch(contract, root, False, False, fixtures["missing-operational-fields.json"])
