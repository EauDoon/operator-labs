"""Real synthetic OTLP inspection and exact coverage decision oracles."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import InputError
from tracecanary.contract import parse_contract
from tracecanary.fixture import bundle
from tracecanary.inspection import coverage_gate, inspect_contract
from tracecanary.report import render_human, render_json


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


class CoverageDiffTests(unittest.TestCase):
    def test_rate_drop_despite_unchanged_raw_count(self):
        from tracecanary.comparison import diff_traces
        from tracecanary.inspection import coverage_diff
        fixtures = bundle()
        before = fixtures["safe-export.json"]
        after = copy.deepcopy(before)
        span = copy.deepcopy(after["resourceSpans"][0]["scopeSpans"][0]["spans"][0])
        span["attributes"] = []
        after["resourceSpans"][0]["scopeSpans"][0]["spans"].append(span)
        contract = parse_contract(fixtures["contract.json"])
        self.assertEqual(diff_traces(contract, before, after)["status"], "pass")
        report = coverage_diff(contract, before, after)
        self.assertEqual(report["status"], "regression")
        self.assertEqual(report["coverage_diff"]["fields"][1]["rate_delta"], "-1/2")
        after["resourceSpans"][0]["scopeSpans"][0]["spans"][1]["attributes"] = copy.deepcopy(before["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"])
        self.assertEqual(coverage_diff(contract, before, after)["status"], "pass")

    def test_empty_and_invalid_baseline_are_unresolved(self):
        from tracecanary.inspection import coverage_diff
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        empty = {"resourceSpans": []}
        self.assertEqual(coverage_diff(contract, empty, fixtures["safe-export.json"])["status"], "unresolved")
        self.assertEqual(coverage_diff(contract, fixtures["safe-export.json"], empty)["status"], "unresolved")


class RetentionMatrixTests(unittest.TestCase):
    def test_empty_attributes_and_nested_events_use_safe_pointers(self):
        from tracecanary.inspection import retention_matrix
        fixtures = bundle()
        payload = fixtures["safe-export.json"]
        extra = copy.deepcopy(payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0])
        extra.pop("attributes")
        extra["events"][0].pop("attributes")
        payload["resourceSpans"][0]["scopeSpans"][0]["spans"].append(extra)
        report = retention_matrix(parse_contract(fixtures["contract.json"]), payload)
        self.assertEqual(report["status"], "pass")
        fields = report["retention_matrix"]["fields"]
        self.assertEqual(fields[1]["missing_paths"], ["/resourceSpans/0/scopeSpans/0/spans/1"])
        self.assertEqual(fields[2]["missing_paths"], ["/resourceSpans/0/scopeSpans/0/spans/1/events/0"])
        self.assertNotIn("service.name", render_json(report) + render_human(report))

    def test_check_budget_is_enforced_without_partial_output(self):
        from unittest.mock import patch

        from tracecanary.inspection import retention_matrix
        fixtures = bundle()
        with patch("tracecanary.inspection.MAX_MATRIX_CHECKS", 2), self.assertRaises(InputError):
            retention_matrix(parse_contract(fixtures["contract.json"]), fixtures["safe-export.json"])


class BatchCoverageTests(unittest.TestCase):
    def test_aggregate_weights_entities_and_accounts_for_invalid_files(self):
        import json
        import tempfile

        from tracecanary.cli import _run_batch
        fixtures = bundle()
        first = fixtures["safe-export.json"]
        second = copy.deepcopy(first)
        span = copy.deepcopy(second["resourceSpans"][0]["scopeSpans"][0]["spans"][0])
        span["attributes"] = []
        second["resourceSpans"][0]["scopeSpans"][0]["spans"].extend([copy.deepcopy(span), span])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps(first))
            (root / "b.json").write_text(json.dumps(second))
            (root / "c.json").write_text("invalid")
            report = _run_batch(parse_contract(fixtures["contract.json"]), root, False, False, coverage=True)
        self.assertEqual(report["status"], "unresolved")
        summary = report["coverage_summary"]
        self.assertEqual((summary["validated_items"], summary["unresolved_items"]), (2, 1))
        field = summary["required_fields"][1]
        self.assertEqual((field["present"], field["entities"], field["ratio"]), (2, 4, "1/2"))
        self.assertTrue(all("path" not in item for item in report["items"]))

    def test_empty_population_has_no_invented_ratio(self):
        import json
        import tempfile

        from tracecanary.cli import _run_batch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps({"resourceSpans": []}))
            report = _run_batch(parse_contract(bundle()["contract.json"]), root, False, False, coverage=True)
        self.assertTrue(all(field["ratio"] is None for field in report["coverage_summary"]["required_fields"]))
