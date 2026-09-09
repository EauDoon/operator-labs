"""Real synthetic OTLP inspection and exact coverage decision oracles."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.contract import parse_contract
from tracecanary.fixture import bundle
from tracecanary.inspection import inspect_contract, coverage_gate
from tracecanary.canonical import InputError
from tracecanary.report import render_json, render_human


class ContractInspectionTests(unittest.TestCase):
    def test_inspection_omits_canary_values_and_field_keys(self):
        contract = parse_contract(bundle()["contract.json"])
        report = inspect_contract(contract)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["inspection"]["canary_count"], 4)
        text = render_json(report) + render_human(report)
        for canary in contract.canaries:
            self.assertNotIn(canary.value, text)
        self.assertNotIn("service.name", text)

    def test_impossible_retention_rule_is_reported_by_ordinal(self):
        raw = bundle()["contract.json"]
        raw["forbidden_attribute_key_prefixes"].append("service.")
        report = inspect_contract(parse_contract(raw))
        self.assertEqual(report["status"], "regression")
        self.assertEqual(report["inspection"]["retention_conflicts"], ["required-0001"])


class CoverageGateTests(unittest.TestCase):
    def test_exact_half_threshold_and_existing_check_semantics(self):
        fixtures = bundle()
        payload = fixtures["safe-export.json"]
        extra = copy.deepcopy(payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0])
        extra["attributes"] = []
        payload["resourceSpans"][0]["scopeSpans"][0]["spans"].append(extra)
        contract = parse_contract(fixtures["contract.json"])
        self.assertEqual(coverage_gate(contract, payload, "0.5")["status"], "pass")
        report = coverage_gate(contract, payload, "0.500001")
        self.assertEqual(report["status"], "regression")
        self.assertEqual(report["coverage_gate"]["fields"][1]["meets_minimum"], False)

    def test_empty_populations_and_invalid_thresholds_fail_closed(self):
        contract = parse_contract(bundle()["contract.json"])
        self.assertEqual(coverage_gate(contract, {"resourceSpans": []}, "0")["status"], "unresolved")
        for threshold in ("NaN", "1.1", "-0.1", "1e-10", "0.1234567", 0.5):
            with self.assertRaises(InputError):
                coverage_gate(contract, bundle()["safe-export.json"], threshold)
