"""Offline control and telemetry completeness decision checks."""
import copy
import unittest

from tracecanary.contract import parse_contract
from tracecanary.fixture import bundle
from tracecanary.inspection import coverage_gate, retention_matrix
from tracecanary.report import render_human, render_json


class ExtendedRetentionTests(unittest.TestCase):
    def test_scope_and_link_requirements_flow_through_existing_checks(self):
        fixtures = bundle()
        fixtures["contract.json"]["required_retained_fields"] = [
            {"scope": "scope", "key": "instrumentation.tag"}, {"scope": "link", "key": "link.tag"}]
        contract = parse_contract(fixtures["contract.json"])
        payload = fixtures["safe-export.json"]
        scope = payload["resourceSpans"][0]["scopeSpans"][0]
        scope["scope"]["attributes"] = [{"key": "instrumentation.tag", "value": {"boolValue": True}}]
        scope["spans"][0]["links"] = [{"attributes": [{"key": "link.tag", "value": {"boolValue": True}}]}, {}]
        report = coverage_gate(contract, payload, "1")
        self.assertEqual(report["status"], "regression")
        self.assertEqual(report["coverage"]["required_fields"][1]["present"], 1)
        matrix = retention_matrix(contract, payload)
        self.assertEqual(matrix["retention_matrix"]["fields"][1]["missing_paths"],
                         ["/resourceSpans/0/scopeSpans/0/spans/0/links/1"])
        from tracecanary.comparison import diff_traces
        candidate = copy.deepcopy(payload)
        candidate["resourceSpans"][0]["scopeSpans"][0]["scope"].pop("attributes")
        self.assertEqual(diff_traces(contract, payload, candidate)["status"], "regression")

    def test_absent_scope_object_is_a_missing_retention_population(self):
        fixtures = bundle()
        fixtures["contract.json"]["required_retained_fields"] = [{"scope": "scope", "key": "instrumentation.tag"}]
        payload = fixtures["safe-export.json"]
        payload["resourceSpans"][0]["scopeSpans"][0].pop("scope")
        report = retention_matrix(parse_contract(fixtures["contract.json"]), payload)
        self.assertEqual(report["coverage"]["required_fields"][0]["entities"], 1)
        self.assertEqual(report["retention_matrix"]["fields"][0]["missing_paths"], ["/resourceSpans/0/scopeSpans/0/scope"])


class ControlCheckTests(unittest.TestCase):
    def test_complete_positive_control_counts_without_exposing_values(self):
        from tracecanary.inspection import control_check
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        payload = fixtures["safe-export.json"]
        payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"].append(
            {"key": "synthetic.control", "value": {"arrayValue": {"values": [
                {"stringValue": item.value} for item in contract.canaries]}}})
        report = control_check(contract, payload)
        self.assertEqual(report["status"], "pass")
        self.assertEqual([row["occurrences"] for row in report["control"]["canaries"]], [1] * 4)
        output = render_json(report) + render_human(report)
        for canary in contract.canaries:
            self.assertNotIn(canary.value, output)
        self.assertIn("positive control", render_human(report))

    def test_missing_or_only_substring_canaries_are_unresolved(self):
        from tracecanary.inspection import control_check
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        payload = fixtures["safe-export.json"]
        payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] = "prefix" + contract.canaries[0].value
        report = control_check(contract, payload)
        self.assertEqual(report["status"], "unresolved")
        self.assertEqual(report["summary"]["total"], 4)


class PopulationGateTests(unittest.TestCase):
    def test_empty_or_small_exports_fail_without_losing_privacy_findings(self):
        from tracecanary.inspection import population_gate
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        self.assertEqual(population_gate(contract, fixtures["safe-export.json"], "span", 1)["status"], "pass")
        report = population_gate(contract, fixtures["safe-export.json"], "span", 2)
        self.assertEqual(report["population_gate"], {"scope": "span", "minimum": 2, "observed": 1})
        self.assertEqual(report["status"], "regression")
        self.assertEqual(population_gate(contract, {"resourceSpans": []}, "span", 1)["status"], "regression")
        self.assertEqual(population_gate(contract, fixtures["leaked-prompt.json"], "span", 1)["status"], "regression")

    def test_invalid_gates_do_not_weaken_checks(self):
        from tracecanary.canonical import InputError
        from tracecanary.inspection import population_gate
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        for scope, count in (("unknown", 1), ("span", 0), ("span", True), ("span", 1.0), ("span", 1000001)):
            with self.assertRaises(InputError):
                population_gate(contract, fixtures["safe-export.json"], scope, count)


class DroppedTelemetryTests(unittest.TestCase):
    def test_nested_drop_counters_are_descriptive_unless_explicitly_gated(self):
        from tracecanary.inspection import dropped_telemetry
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        payload = fixtures["safe-export.json"]
        resource = payload["resourceSpans"][0]
        resource["resource"]["droppedAttributesCount"] = 2
        scope = resource["scopeSpans"][0]
        scope["scope"]["droppedAttributesCount"] = 3
        span = scope["spans"][0]
        span.update(droppedAttributesCount=5, droppedEventsCount=7, droppedLinksCount=11)
        span["events"][0]["droppedAttributesCount"] = 13
        span["links"] = [{"droppedAttributesCount": 17}]
        report = dropped_telemetry(contract, payload)
        self.assertEqual(report["status"], "pass")
        rows = report["dropped_telemetry"]["scopes"]
        self.assertEqual([row["attributes"] for row in rows], [2, 3, 5, 13, 17])
        self.assertEqual(sum(row["events"] for row in rows), 7)
        self.assertEqual(sum(row["links"] for row in rows), 11)
        report = dropped_telemetry(contract, payload, require_zero=True)
        self.assertEqual(report["status"], "regression")
        self.assertEqual(report["summary"]["total"], 5)

    def test_absent_counters_do_not_hide_privacy_findings(self):
        from tracecanary.inspection import dropped_telemetry
        fixtures = bundle()
        contract = parse_contract(fixtures["contract.json"])
        self.assertEqual(dropped_telemetry(contract, fixtures["safe-export.json"], require_zero=True)["status"], "pass")
        self.assertEqual(dropped_telemetry(contract, fixtures["leaked-prompt.json"], require_zero=True)["status"], "regression")
