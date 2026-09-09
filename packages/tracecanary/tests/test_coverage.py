import copy
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tracecanary.coverage import coverage_report
from tracecanary.fixture import bundle
from tracecanary.contract import parse_contract
from tracecanary.report import render_json, render_human

class CoverageTests(unittest.TestCase):
    def test_counts_are_value_free_and_stable(self):
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        payload = fixtures["safe-export.json"]
        report = coverage_report(contract, payload)
        self.assertEqual(report["coverage"]["entities"]["resource"], 1)
        self.assertGreater(report["coverage"]["entities"]["span"], 0)
        for field in report["coverage"]["required_fields"]:
            self.assertGreater(field["present"], 0)
        self.assertEqual(render_json(report), render_json(coverage_report(contract, payload)))
        text = render_json(report) + render_human(report)
        for canary in contract.canaries:
            self.assertNotIn(canary.value, text)
        self.assertNotIn("service.name", render_json(report["coverage"]))

    def test_empty_export_does_not_invent_coverage(self):
        contract = parse_contract(bundle()["contract.json"])
        report = coverage_report(contract, {"resourceSpans": []})
        self.assertEqual(report["coverage"]["entities"]["span"], 0)
        self.assertTrue(all(field["present"] == 0 for field in report["coverage"]["required_fields"]))
        self.assertEqual(report["status"], "regression")
