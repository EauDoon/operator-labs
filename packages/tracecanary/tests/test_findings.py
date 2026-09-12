"""Summary, grouping, filtering, and explanation over reports."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import InputError
from tracecanary.checker import check_trace
from tracecanary.cli import EXIT_PASS, EXIT_REGRESSION, EXIT_UNRESOLVED, main
from tracecanary.comparison import diff_traces
from tracecanary.contract import load_contract
from tracecanary.findings import (
    GROUP_KEYS,
    KNOWN_CODES,
    explain,
    filter_findings,
    group_findings,
    grouped_report,
    render_groups,
    render_summary,
    summarize,
)
from tracecanary.otlp import validate_trace
from tracecanary.report import render_human, render_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"
CANARY = "TCANARY_PROMPT_71f0e04f"


def _load(name: str) -> dict:
    from tracecanary.canonical import load_json

    contract = load_contract(FIXTURES / "contract.json")
    payload = load_json(FIXTURES / name, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    validate_trace(payload)
    return payload


class SummarizeTests(unittest.TestCase):
    def _report(self, name: str = "leaked-prompt.json") -> dict:
        contract = load_contract(FIXTURES / "contract.json")
        return check_trace(contract, _load(name))

    def test_summary_shape_and_status(self) -> None:
        summary = summarize(self._report())
        self.assertEqual(summary["status"], "regression")
        self.assertEqual(summary["total"], 2)
        self.assertFalse(summary["unresolved"])
        self.assertEqual(summary["by_code"], {"TC001": 1, "TC002": 1})
        self.assertEqual(summary["by_scope"], {"span": 1})
        self.assertEqual(summary["by_category"], {"prompt": 1})

    def test_summary_is_deterministic(self) -> None:
        report = self._report()
        self.assertEqual(json.dumps(summarize(report), sort_keys=True), json.dumps(summarize(report), sort_keys=True))

    def test_unresolved_status_is_flagged(self) -> None:
        contract = load_contract(FIXTURES / "contract.json")
        report = diff_traces(contract, _load("missing-operational-fields.json"), _load("safe-export.json"))
        self.assertTrue(summarize(report)["unresolved"])

    def test_summary_never_carries_a_canary_value(self) -> None:
        text = json.dumps(summarize(self._report()), sort_keys=True)
        self.assertNotIn(CANARY, text)
        self.assertNotIn("TCANARY_", text)

    def test_summary_panel_is_deterministic_and_value_free(self) -> None:
        report = self._report()
        first = render_summary(report, redacted_values=(CANARY,))
        second = render_summary(report, redacted_values=(CANARY,))
        self.assertEqual(first, second)
        self.assertIn("REGRESSION", first)
        self.assertIn("by code: TC001=1; TC002=1", first)
        self.assertNotIn(CANARY, first)


class GroupingTests(unittest.TestCase):
    def _report(self) -> dict:
        contract = load_contract(FIXTURES / "contract.json")
        return check_trace(contract, _load("leaked-prompt.json"))

    def test_grouping_by_every_supported_key(self) -> None:
        report = self._report()
        for key in GROUP_KEYS:
            with self.subTest(key=key):
                groups = group_findings(report, key)
                self.assertTrue(groups)
                for group in groups:
                    self.assertEqual(set(group), {"group", "count", "codes", "messages"})
                    self.assertEqual(sum(item["count"] for item in groups), 2)

    def test_group_by_code_collects_codes_and_messages(self) -> None:
        groups = group_findings(self._report(), "code")
        self.assertEqual([item["group"] for item in groups], ["TC001", "TC002"])
        self.assertEqual(groups[0]["codes"], ["TC001"])
        self.assertEqual(groups[0]["messages"], ["synthetic canary survived export"])

    def test_findings_without_the_key_form_the_empty_group(self) -> None:
        groups = group_findings(self._report(), "scope")
        self.assertEqual([item["group"] for item in groups], ["", "span"])
        self.assertEqual(groups[0]["count"], 1)

    def test_grouping_is_deterministic(self) -> None:
        report = self._report()
        first = json.dumps(group_findings(report, "category"), sort_keys=True)
        second = json.dumps(group_findings(report, "category"), sort_keys=True)
        self.assertEqual(first, second)

    def test_unknown_group_by_is_rejected(self) -> None:
        with self.assertRaises(InputError):
            group_findings(self._report(), "value")

    def test_grouped_output_carries_no_value(self) -> None:
        report = self._report()
        for key in GROUP_KEYS:
            with self.subTest(key=key):
                payload = grouped_report(report, group_findings(report, key))
                self.assertNotIn(CANARY, json.dumps(payload, sort_keys=True))
                self.assertNotIn(CANARY, render_groups(group_findings(report, key), key, redacted_values=(CANARY,)))

    def test_render_groups_with_no_findings(self) -> None:
        contract = load_contract(FIXTURES / "contract.json")
        report = check_trace(contract, _load("safe-export.json"))
        self.assertIn("no findings to group", render_groups(group_findings(report, "code"), "code"))


class FilterTests(unittest.TestCase):
    def _report(self) -> dict:
        contract = load_contract(FIXTURES / "contract.json")
        return check_trace(contract, _load("leaked-prompt.json"))

    def test_filtering_recomputes_the_summary(self) -> None:
        report = self._report()
        self.assertEqual(report["summary"]["total"], 2)
        filtered = filter_findings(report, codes=("TC002",))
        self.assertEqual(filtered["summary"]["total"], 1)
        self.assertEqual(filtered["summary"]["canary_leaks"], 0)
        self.assertEqual(filtered["summary"]["forbidden_attributes"], 1)
        self.assertEqual([item["code"] for item in filtered["violations"]], ["TC002"])

    def test_filtering_never_changes_status(self) -> None:
        """Hiding a finding must not turn a regression into a pass."""
        report = self._report()
        self.assertEqual(report["status"], "regression")
        emptied = filter_findings(report, codes=("TC900",))
        self.assertEqual(emptied["summary"]["total"], 0)
        self.assertEqual(emptied["status"], "regression")

    def test_filtering_an_unresolved_report_stays_unresolved(self) -> None:
        contract = load_contract(FIXTURES / "contract.json")
        report = diff_traces(contract, _load("missing-operational-fields.json"), _load("safe-export.json"))
        self.assertEqual(report["status"], "unresolved")
        self.assertEqual(filter_findings(report, codes=("TC001",))["status"], "unresolved")

    def test_filter_by_scope_and_category(self) -> None:
        report = self._report()
        self.assertEqual(filter_findings(report, scopes=("span",))["summary"]["total"], 1)
        self.assertEqual(filter_findings(report, categories=("prompt",))["summary"]["total"], 1)
        self.assertEqual(filter_findings(report, scopes=("resource",))["summary"]["total"], 0)
        self.assertEqual(filter_findings(report, scopes=("span",), categories=("prompt",))["summary"]["total"], 0)

    def test_filter_returns_a_new_report(self) -> None:
        report = self._report()
        filtered = filter_findings(report, codes=("TC001",))
        self.assertIsNot(filtered, report)
        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(set(filtered), set(report))

    def test_empty_selection_is_not_a_constraint(self) -> None:
        report = self._report()
        self.assertEqual(filter_findings(report, codes=())["summary"]["total"], 2)

    def test_unknown_filter_code_is_rejected(self) -> None:
        with self.assertRaises(InputError):
            filter_findings(self._report(), codes=("TC999",))

    def test_filtered_report_still_renders_without_values(self) -> None:
        filtered = filter_findings(self._report(), codes=("TC001",), redacted_values=(CANARY,))
        self.assertNotIn(CANARY, render_human(filtered) + render_json(filtered))


class ExplainTests(unittest.TestCase):
    def test_explain_states_the_coverage_caveats(self) -> None:
        contract = load_contract(FIXTURES / "contract.json")
        text = explain(check_trace(contract, _load("leaked-prompt.json")), redacted_values=(CANARY,))
        self.assertIn("what was checked", text)
        self.assertIn("what failed", text)
        self.assertIn("what remains unknown", text)
        self.assertIn("exact matching", text)
        self.assertIn("transformation is not covered", text)
        self.assertIn("`path` pointers are structural and omit values by design", text)

    def test_explain_of_a_diff_describes_both_contributions(self) -> None:
        contract = load_contract(FIXTURES / "contract.json")
        report = diff_traces(contract, _load("safe-export.json"), _load("missing-operational-fields.json"))
        text = explain(report, redacted_values=(CANARY,))
        self.assertIn("diff contribution", text)
        self.assertIn("baseline", text)
        self.assertIn("candidate", text)

    def test_explain_of_an_unresolved_diff_names_the_baseline_failure(self) -> None:
        contract = load_contract(FIXTURES / "contract.json")
        report = diff_traces(contract, _load("missing-operational-fields.json"), _load("safe-export.json"))
        text = explain(report, redacted_values=(CANARY,))
        self.assertIn("the baseline did not satisfy the contract", text)

    def test_explain_is_deterministic_and_value_free(self) -> None:
        contract = load_contract(FIXTURES / "contract.json")
        report = check_trace(contract, _load("leaked-prompt.json"))
        self.assertEqual(explain(report), explain(report))
        self.assertNotIn(CANARY, explain(report, redacted_values=(CANARY,)))


class CliFindingViewTests(unittest.TestCase):
    def _run(self, command: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(command)
        return status, output.getvalue(), error.getvalue()

    def _check(self, *extra: str) -> tuple[int, str, str]:
        return self._run(
            [
                "check",
                "--contract",
                str(FIXTURES / "contract.json"),
                "--input",
                str(FIXTURES / "leaked-prompt.json"),
                *extra,
            ]
        )

    def test_summary_flag_prints_a_panel_and_keeps_the_exit_code(self) -> None:
        status, output, error = self._check("--summary")
        self.assertEqual(status, EXIT_REGRESSION)
        self.assertEqual(error, "")
        self.assertIn("TraceCanary summary: REGRESSION", output)
        self.assertIn("by code: TC001=1; TC002=1", output)

    def test_group_by_applies_to_human_output(self) -> None:
        status, output, error = self._check("--group-by", "code")
        self.assertEqual(status, EXIT_REGRESSION)
        self.assertIn("TraceCanary groups by code", output)
        self.assertIn("TC001: 1 finding(s)", output)

    def test_group_by_applies_to_json_output(self) -> None:
        status, output, error = self._check("--group-by", "category", "--format", "json")
        self.assertEqual(status, EXIT_REGRESSION)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "regression")
        self.assertEqual([item["group"] for item in payload["groups"]], ["", "prompt"])

    def test_filter_code_narrows_the_report_without_changing_the_exit_code(self) -> None:
        status, output, error = self._check("--filter-code", "TC002")
        self.assertEqual(status, EXIT_REGRESSION)
        self.assertIn("TC002", output)
        self.assertNotIn("TC001", output)

    def test_unknown_filter_code_is_exit_two_with_an_actionable_message(self) -> None:
        status, output, error = self._check("--filter-code", "TC999")
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("unknown TraceCanary code TC999", error)
        self.assertIn("known codes are", error)

    def test_unknown_group_by_is_exit_two(self) -> None:
        status, output, error = self._check("--group-by", "value")
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("invalid choice", error)

    def test_passing_run_still_exits_zero_with_a_view(self) -> None:
        status, output, error = self._run(
            [
                "check",
                "--contract",
                str(FIXTURES / "contract.json"),
                "--input",
                str(FIXTURES / "safe-export.json"),
                "--summary",
                "--group-by",
                "code",
            ]
        )
        self.assertEqual(status, EXIT_PASS)
        self.assertIn("PASS", output)

    def test_every_known_code_is_accepted(self) -> None:
        for code in KNOWN_CODES:
            with self.subTest(code=code):
                status, _output, error = self._check("--filter-code", code)
                self.assertEqual(status, EXIT_REGRESSION)
                self.assertEqual(error, "")

    def test_diff_supports_the_same_views(self) -> None:
        status, output, error = self._run(
            [
                "diff",
                "--contract",
                str(FIXTURES / "contract.json"),
                "--baseline",
                str(FIXTURES / "safe-export.json"),
                "--candidate",
                str(FIXTURES / "missing-operational-fields.json"),
                "--summary",
                "--group-by",
                "scope",
            ]
        )
        self.assertEqual(status, EXIT_REGRESSION)
        self.assertIn("by scope: event=2", output)


class AdversarialNonLeakageTests(unittest.TestCase):
    """Put a canary value where a renderer might echo it and prove it does not."""

    def test_value_in_attribute_key_span_name_and_label_is_never_rendered(self) -> None:
        """A value hidden in a span name or an attribute key must not reach any view."""
        marker = "TCANARY_ADVERSARY_5f2c"
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [item.unlink() for item in directory.iterdir()] or directory.rmdir())
        contract_path = directory / "contract.json"
        contract_path.write_text(
            json.dumps(
                {
                    "contract_version": "tracecanary/v1",
                    "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
                    "canaries": [{"label": "synthetic-x", "category": "x", "value": marker}],
                    "forbidden_attribute_key_prefixes": ["attr."],
                    "required_retained_fields": [{"scope": "resource", "key": "service.name"}],
                }
            ),
            encoding="utf-8",
        )
        trace = {
            "resourceSpans": [
                {
                    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "svc"}}]},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "name": f"span-{marker}",
                                    "attributes": [{"key": f"attr.{marker}", "value": {"stringValue": "safe"}}],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        trace_path = directory / "trace.json"
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        contract = load_contract(contract_path)
        payload = _load_dict(trace_path, contract)
        report = check_trace(contract, payload)
        self.assertEqual(report["status"], "regression")
        rendered = "\n".join(
            [
                render_human(report),
                render_json(report),
                render_summary(report, redacted_values=(marker,)),
                explain(report, redacted_values=(marker,)),
                render_groups(group_findings(report, "code", redacted_values=(marker,)), "code", redacted_values=(marker,)),
                render_groups(group_findings(report, "key", redacted_values=(marker,)), "key", redacted_values=(marker,)),
                json.dumps(summarize(report, redacted_values=(marker,)), sort_keys=True),
                json.dumps(grouped_report(report, group_findings(report, "key")), sort_keys=True),
            ]
        )
        self.assertNotIn(marker, rendered)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["check", "--contract", str(contract_path), "--input", str(trace_path), "--summary"])
        self.assertEqual(status, EXIT_REGRESSION)
        self.assertNotIn(marker, output.getvalue())

    def test_value_in_a_contract_label_makes_the_contract_unusable(self) -> None:
        marker = "TCANARY_LABEL_2b7d"
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [item.unlink() for item in directory.iterdir()] or directory.rmdir())
        contract_path = directory / "contract.json"
        contract_path.write_text(
            json.dumps(
                {
                    "contract_version": "tracecanary/v1",
                    "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
                    # The second label carries the first canary's value, which a
                    # contract must never do because labels are report-visible.
                    "canaries": [
                        {"label": "safe-label", "category": "x", "value": marker},
                        {"label": marker, "category": "y", "value": "another-safe-value"},
                    ],
                    "required_retained_fields": [],
                }
            ),
            encoding="utf-8",
        )
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(["validate", str(contract_path)])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertNotIn(marker, output.getvalue() + error.getvalue())


def _load_dict(path: Path, contract: object) -> dict:
    from tracecanary.canonical import load_json

    payload = load_json(path, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    validate_trace(payload)
    return payload


if __name__ == "__main__":
    unittest.main()
