from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import load_json
from tracecanary.comparison import diff_traces
from tracecanary.contract import load_contract
from tracecanary.otlp import validate_trace

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_contract(FIXTURES / "contract.json")

    def _trace(self, name: str) -> dict:
        payload = load_json(FIXTURES / name, max_bytes=self.contract.max_input_bytes, max_depth=self.contract.max_nesting)
        validate_trace(payload)
        return payload

    def test_retention_regression_includes_candidate_and_baseline_findings(self) -> None:
        report = diff_traces(self.contract, self._trace("safe-export.json"), self._trace("missing-operational-fields.json"))
        self.assertEqual(report["status"], "regression")
        self.assertEqual({item["code"] for item in report["violations"]}, {"TC004", "TC005"})

    def test_identical_traces_compare_equally(self) -> None:
        safe = self._trace("safe-export.json")
        self.assertEqual(diff_traces(self.contract, safe, safe)["status"], "pass")

    def test_unsafe_baseline_is_unresolved(self) -> None:
        report = diff_traces(self.contract, self._trace("leaked-prompt.json"), self._trace("safe-export.json"))
        self.assertEqual(report["status"], "unresolved")
        self.assertEqual(report["violations"][0]["code"], "TC900")
