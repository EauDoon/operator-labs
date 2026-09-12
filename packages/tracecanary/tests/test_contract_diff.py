"""Contract-change review as a change in checking coverage."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import canonical_json
from tracecanary.cli import EXIT_PASS, EXIT_REGRESSION, EXIT_UNRESOLVED, main
from tracecanary.contract import parse_contract
from tracecanary.contract_diff import (
    CHANGED,
    DISCLAIMER,
    INCREASED,
    REDUCED,
    REVIEW_VERSION,
    UNCHANGED,
    VERDICTS,
    render_contract_review_human,
    review_contract_change,
)


SEMCONV = "opentelemetry/semconv/1.43.0"


def _v2(**overrides: object) -> dict:
    contract = {
        "contract_version": "tracecanary/v2",
        "semantic_conventions_version": SEMCONV,
        "canaries": [
            {"label": "synthetic-prompt", "category": "prompt", "value": "TCANARY_PROMPT_11111111"},
            {"label": "synthetic-result", "category": "tool_result", "value": "TCANARY_RESULT_22222222"},
        ],
        "forbidden_attribute_keys": ["gen_ai.prompt", "gen_ai.tool.call.result"],
        "forbidden_attribute_key_prefixes": ["enduser."],
        "forbidden_path_prefixes": ["/resourceSpans/*/scopeSpans/*/spans/*/attributes/*/value/bytesValue"],
        "required_retained_fields": [{"scope": "resource", "key": "service.name"}, {"scope": "span", "key": "gen_ai.operation.name"}],
        "retention": {
            "version": "tracecanary.retention/v1",
            "requirements": [
                {
                    "requirement_id": "operation-name",
                    "scope": "span",
                    "key": "gen_ai.operation.name",
                    "value_types": ["stringValue", "intValue"],
                    "minimum_count": 2,
                    "comparison": "count",
                },
                {
                    "requirement_id": "service-name",
                    "scope": "resource",
                    "key": "service.name",
                    "value_types": ["stringValue"],
                    "minimum_count": 1,
                    "comparison": "presence",
                },
            ],
        },
        "limits": {"max_input_bytes": 1000000, "max_nesting": 100, "max_batch_files": 8},
    }
    contract.update(overrides)
    return contract


def _review(before: dict, after: dict) -> dict:
    return review_contract_change(parse_contract(deepcopy(before)), parse_contract(deepcopy(after)))


def _changes(review: dict, category: str) -> list[dict]:
    return [item for item in review["changes"] if item["category"] == category]


def _one(review: dict, category: str) -> dict:
    found = _changes(review, category)
    assert len(found) == 1, f"expected one {category} change, got {found}"
    return found[0]


class VerdictTests(unittest.TestCase):
    def test_identical_contracts_are_unchanged(self) -> None:
        review = _review(_v2(), _v2())
        self.assertEqual(review["verdict"], UNCHANGED)
        self.assertIn(review["verdict"], VERDICTS)
        self.assertEqual(review["changes"], [])
        self.assertEqual(review["review_version"], REVIEW_VERSION)

    def test_verdict_prefers_a_reduction(self) -> None:
        before = _v2()
        after = _v2()
        after["canaries"] = [after["canaries"][0]]
        after["forbidden_attribute_keys"] = [after["forbidden_attribute_keys"][0], "gen_ai.completion"]
        review = _review(before, after)
        self.assertEqual(review["verdict"], REDUCED)
        self.assertEqual(review["counts"]["reduced"], 2)
        self.assertEqual(review["counts"]["increased"], 1)

    def test_increase_without_reduction_is_increased(self) -> None:
        before = _v2()
        after = _v2()
        after["canaries"].append({"label": "synthetic-extra", "category": "extra", "value": "TCANARY_EXTRA_33333333"})
        self.assertEqual(_review(before, after)["verdict"], INCREASED)

    def test_disclaimer_is_present_in_every_output_form(self) -> None:
        before = _v2()
        after = _v2()
        after["canaries"] = [after["canaries"][0]]
        review = _review(before, after)
        self.assertEqual(review["disclaimer"], DISCLAIMER)
        self.assertIn(DISCLAIMER, canonical_json(review))
        self.assertIn(DISCLAIMER, render_contract_review_human(review))
        unchanged = _review(_v2(), _v2())
        self.assertIn(DISCLAIMER, canonical_json(unchanged))
        self.assertIn(DISCLAIMER, render_contract_review_human(unchanged))


class CanaryTests(unittest.TestCase):
    def test_removed_canary_is_reported_by_label_and_reduces_coverage(self) -> None:
        before = _v2()
        after = _v2()
        after["canaries"] = [after["canaries"][0]]
        change = _one(_review(before, after), "canary")
        self.assertEqual(change["classification"], REDUCED)
        self.assertEqual(change["target"], "synthetic-result")
        self.assertEqual(change["change"], "removed")

    def test_added_canary_increases_coverage(self) -> None:
        before = _v2()
        after = _v2()
        after["canaries"].append({"label": "synthetic-extra", "category": "extra", "value": "TCANARY_EXTRA_33333333"})
        change = _one(_review(before, after), "canary")
        self.assertEqual(change["classification"], INCREASED)
        self.assertEqual(change["target"], "synthetic-extra")

    def test_the_canary_value_never_appears(self) -> None:
        before = _v2()
        after = _v2()
        after["canaries"] = [after["canaries"][0]]
        review = _review(before, after)
        rendered = canonical_json(review) + render_contract_review_human(review)
        self.assertNotIn("TCANARY_PROMPT_11111111", rendered)
        self.assertNotIn("TCANARY_RESULT_22222222", rendered)
        self.assertNotIn("TCANARY_", rendered)

    def test_unchanged_label_with_a_changed_category_is_noted(self) -> None:
        before = _v2()
        after = _v2()
        after["canaries"][0]["category"] = "completion"
        change = _one(_review(before, after), "canary")
        self.assertEqual(change["classification"], CHANGED)
        self.assertEqual(change["change"], "category changed")
        self.assertEqual(change["before"], "prompt")
        self.assertEqual(change["after"], "completion")

    def test_replaced_value_is_noted_without_rendering_it(self) -> None:
        before = _v2()
        after = _v2()
        after["canaries"][0]["value"] = "TCANARY_PROMPT_99999999"
        change = _one(_review(before, after), "canary")
        self.assertEqual(change["classification"], CHANGED)
        self.assertEqual(change["change"], "value replaced")
        self.assertNotIn("TCANARY_", canonical_json(change))


class ProhibitionTests(unittest.TestCase):
    def test_removed_forbidden_key_reduces_coverage(self) -> None:
        before = _v2()
        after = _v2(forbidden_attribute_keys=["gen_ai.prompt"])
        change = _one(_review(before, after), "forbidden_attribute_keys")
        self.assertEqual(change["classification"], REDUCED)
        self.assertEqual(change["target"], "gen_ai.tool.call.result")

    def test_added_forbidden_key_prefix_increases_coverage(self) -> None:
        before = _v2()
        after = _v2(forbidden_attribute_key_prefixes=["enduser.", "user."])
        change = _one(_review(before, after), "forbidden_attribute_key_prefixes")
        self.assertEqual(change["classification"], INCREASED)
        self.assertEqual(change["target"], "user.")

    def test_removed_forbidden_path_prefix_reduces_coverage(self) -> None:
        before = _v2()
        after = _v2(forbidden_path_prefixes=[])
        change = _one(_review(before, after), "forbidden_path_prefixes")
        self.assertEqual(change["classification"], REDUCED)

    def test_added_forbidden_path_prefix_increases_coverage(self) -> None:
        before = _v2(forbidden_path_prefixes=[])
        after = _v2()
        change = _one(_review(before, after), "forbidden_path_prefixes")
        self.assertEqual(change["classification"], INCREASED)


class RetentionTests(unittest.TestCase):
    @staticmethod
    def _requirement(after: dict, identifier: str, **fields: object) -> None:
        for requirement in after["retention"]["requirements"]:
            if requirement["requirement_id"] == identifier:
                requirement.update(fields)

    def test_removed_requirement_reduces_coverage(self) -> None:
        before = _v2()
        after = _v2()
        after["retention"]["requirements"] = [after["retention"]["requirements"][1]]
        change = _one(_review(before, after), "retention")
        self.assertEqual(change["classification"], REDUCED)
        self.assertEqual(change["change"], "requirement removed")
        self.assertEqual(change["target"], "operation-name")

    def test_added_requirement_increases_coverage(self) -> None:
        before = _v2()
        after = _v2()
        after["retention"]["requirements"].append(
            {
                "requirement_id": "request-model",
                "scope": "span",
                "key": "gen_ai.request.model",
                "minimum_count": 1,
                "comparison": "presence",
            }
        )
        change = _one(_review(before, after), "retention")
        self.assertEqual(change["classification"], INCREASED)
        self.assertEqual(change["change"], "requirement added")
        self.assertEqual(change["target"], "request-model")

    def test_lowered_minimum_count_reduces_coverage(self) -> None:
        after = _v2()
        self._requirement(after, "operation-name", minimum_count=1)
        change = _one(_review(_v2(), after), "retention")
        self.assertEqual(change["classification"], REDUCED)
        self.assertEqual(change["change"], "minimum_count lowered")
        self.assertEqual(change["before"], 2)
        self.assertEqual(change["after"], 1)

    def test_raised_minimum_count_increases_coverage(self) -> None:
        after = _v2()
        self._requirement(after, "operation-name", minimum_count=5)
        change = _one(_review(_v2(), after), "retention")
        self.assertEqual(change["classification"], INCREASED)

    def test_removed_value_types_reduces_coverage(self) -> None:
        after = _v2()
        self._requirement(after, "operation-name", value_types=None)
        change = _one(_review(_v2(), after), "retention")
        self.assertEqual(change["classification"], REDUCED)
        self.assertEqual(change["change"], "value_types removed")

    def test_narrowed_value_types_increases_coverage(self) -> None:
        after = _v2()
        self._requirement(after, "operation-name", value_types=["stringValue"])
        change = _one(_review(_v2(), after), "retention")
        self.assertEqual(change["classification"], INCREASED)
        self.assertEqual(change["change"], "value_types narrowed")

    def test_widened_value_types_reduces_coverage(self) -> None:
        after = _v2()
        self._requirement(after, "operation-name", value_types=["stringValue", "intValue", "boolValue"])
        change = _one(_review(_v2(), after), "retention")
        self.assertEqual(change["classification"], REDUCED)
        self.assertEqual(change["change"], "value_types widened")

    def test_declared_value_types_increases_coverage(self) -> None:
        before = _v2()
        for requirement in before["retention"]["requirements"]:
            requirement.pop("value_types", None)
        after = _v2()
        changes = _changes(_review(before, after), "retention")
        self.assertEqual(len(changes), 2)
        for change in changes:
            self.assertEqual(change["classification"], INCREASED)
            self.assertEqual(change["change"], "value_types declared")

    def test_changed_comparison_mode_is_changed(self) -> None:
        after = _v2()
        self._requirement(after, "operation-name", comparison="presence")
        change = _one(_review(_v2(), after), "retention")
        self.assertEqual(change["classification"], CHANGED)
        self.assertEqual(change["change"], "comparison changed")
        self.assertEqual(change["before"], "count")
        self.assertEqual(change["after"], "presence")

    def test_removed_matching_key_reduces_coverage(self) -> None:
        before, _ = self._matched_ratio_pair()
        before["retention"]["requirements"][0]["matching_keys"] = [
            {"scope": "resource", "key": "service.name"},
            {"scope": "span", "key": "gen_ai.request.id"},
        ]
        after = deepcopy(before)
        after["retention"]["requirements"][0]["matching_keys"] = [{"scope": "resource", "key": "service.name"}]
        change = _one(_review(before, after), "retention")
        self.assertEqual(change["classification"], REDUCED)
        self.assertEqual(change["change"], "matching key removed")
        self.assertIn("span:gen_ai.request.id", change["target"])

    def test_added_matching_key_increases_coverage(self) -> None:
        before, _ = self._matched_ratio_pair()
        after = deepcopy(before)
        after["retention"]["requirements"][0]["matching_keys"] = [
            {"scope": "resource", "key": "service.name"},
            {"scope": "span", "key": "gen_ai.request.id"},
        ]
        change = _one(_review(before, after), "retention")
        self.assertEqual(change["classification"], INCREASED)
        self.assertEqual(change["change"], "matching key added")

    def _matched_ratio_pair(self) -> tuple[dict, dict]:
        """Two contracts whose only difference is the declared denominator."""
        base = _v2()
        base["retention"]["requirements"] = [
            {
                "requirement_id": "operation-name",
                "scope": "span",
                "key": "gen_ai.operation.name",
                "comparison": "matched_ratio",
                "matching_keys": [{"scope": "resource", "key": "service.name"}],
                "denominator_requirement_id": "service-name",
            },
            {
                "requirement_id": "service-name",
                "scope": "resource",
                "key": "service.name",
                "comparison": "presence",
            },
            {
                "requirement_id": "span-count",
                "scope": "span",
                "key": "gen_ai.span.kind",
                "comparison": "presence",
            },
        ]
        after = deepcopy(base)
        after["retention"]["requirements"][0]["denominator_requirement_id"] = "span-count"
        return base, after

    def test_changed_denominator_is_changed(self) -> None:
        before, after = self._matched_ratio_pair()
        change = _one(_review(before, after), "retention")
        self.assertEqual(change["classification"], CHANGED)
        self.assertEqual(change["change"], "denominator changed")
        self.assertEqual(change["before"], "service-name")
        self.assertEqual(change["after"], "span-count")

    def test_whole_retention_object_removed_reduces_coverage(self) -> None:
        before = _v2()
        after = _v2()
        after.pop("retention")
        review = _review(before, after)
        self.assertEqual(review["verdict"], REDUCED)
        self.assertEqual(len(_changes(review, "retention")), 2)


class RetainedFieldTests(unittest.TestCase):
    def test_removed_retained_field_reduces_coverage(self) -> None:
        before = _v2()
        after = _v2(required_retained_fields=[{"scope": "resource", "key": "service.name"}])
        change = _one(_review(before, after), "required_retained_fields")
        self.assertEqual(change["classification"], REDUCED)
        self.assertEqual(change["target"], "span:gen_ai.operation.name")

    def test_added_retained_field_increases_coverage(self) -> None:
        before = _v2(required_retained_fields=[{"scope": "resource", "key": "service.name"}])
        after = _v2()
        change = _one(_review(before, after), "required_retained_fields")
        self.assertEqual(change["classification"], INCREASED)


class LimitTests(unittest.TestCase):
    def test_altered_max_input_bytes_is_changed_and_explains_direction(self) -> None:
        after = _v2(limits={"max_input_bytes": 2000000, "max_nesting": 100, "max_batch_files": 8})
        change = _one(_review(_v2(), after), "limits")
        self.assertEqual(change["classification"], CHANGED)
        self.assertEqual(change["target"], "max_input_bytes")
        self.assertEqual(change["before"], 1000000)
        self.assertEqual(change["after"], 2000000)
        self.assertIn("larger inputs are accepted", change["note"])
        self.assertIn("not that checking got weaker or stronger", change["note"])

    def test_altered_max_nesting_and_max_batch_files_are_changed(self) -> None:
        after = _v2(limits={"max_input_bytes": 1000000, "max_nesting": 50, "max_batch_files": 4})
        review = _review(_v2(), after)
        targets = {item["target"]: item["classification"] for item in _changes(review, "limits")}
        self.assertEqual(targets, {"max_nesting": CHANGED, "max_batch_files": CHANGED})
        self.assertEqual(review["verdict"], UNCHANGED)


class VersionTests(unittest.TestCase):
    def test_changed_semantic_conventions_version_is_changed(self) -> None:
        """The pinned semconv version can only change when the package changes,
        so the review is driven by two constructed contracts."""
        before = parse_contract(_v2())
        after = replace(before, semantic_conventions_version="opentelemetry/semconv/1.44.0")
        review = review_contract_change(before, after)
        change = _one(review, "version")
        self.assertEqual(change["classification"], CHANGED)
        self.assertEqual(change["target"], "semantic_conventions_version")
        self.assertIn("pinned specifications", change["note"])

    def test_changed_contract_version_is_changed(self) -> None:
        before_document = _v2()
        before_document.pop("retention")
        before_document["contract_version"] = "tracecanary/v1"
        after_document = deepcopy(before_document)
        after_document["contract_version"] = "tracecanary/v2"
        review = _review(before_document, after_document)
        change = _one(review, "version")
        self.assertEqual(change["classification"], CHANGED)
        self.assertEqual(change["target"], "contract_version")
        self.assertIn("pinned specifications", change["note"])
        # A version change alone does not reduce or increase coverage.
        self.assertEqual(review["verdict"], UNCHANGED)


class CliContractDiffTests(unittest.TestCase):
    def _write(self, directory: Path, name: str, document: dict) -> Path:
        path = directory / name
        path.write_text(canonical_json(document), encoding="utf-8")
        return path

    def _run(self, *extra: str) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(list(extra))
        return status, output.getvalue(), error.getvalue()

    def test_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self._write(root, "before.json", _v2())
            unchanged = self._write(root, "unchanged.json", _v2())
            increased = self._write(root, "increased.json", _v2(forbidden_attribute_keys=["gen_ai.prompt", "gen_ai.tool.call.result", "gen_ai.completion"]))
            reduced = self._write(root, "reduced.json", _v2(forbidden_attribute_keys=["gen_ai.prompt"]))

            status, output, error = self._run("contract-diff", "--before", str(before), "--after", str(unchanged))
            self.assertEqual(status, EXIT_PASS)
            self.assertEqual(error, "")
            self.assertIn("COVERAGE_UNCHANGED", output)

            status, output, error = self._run("contract-diff", "--before", str(before), "--after", str(increased))
            self.assertEqual(status, EXIT_PASS)
            self.assertIn("COVERAGE_INCREASED", output)

            status, output, error = self._run("contract-diff", "--before", str(before), "--after", str(reduced))
            self.assertEqual(status, EXIT_REGRESSION)
            self.assertIn("COVERAGE_REDUCED", output)

    def test_json_format_and_disclaimer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self._write(root, "before.json", _v2())
            reduced = self._write(root, "reduced.json", _v2(forbidden_attribute_keys=["gen_ai.prompt"]))
            status, output, error = self._run("contract-diff", "--before", str(before), "--after", str(reduced), "--format", "json")
        self.assertEqual(status, EXIT_REGRESSION)
        payload = json.loads(output)
        self.assertEqual(payload["verdict"], REDUCED)
        self.assertEqual(payload["disclaimer"], DISCLAIMER)

    def test_invalid_contract_is_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self._write(root, "before.json", _v2())
            broken = self._write(root, "broken.json", {"contract_version": "tracecanary/v9"})
            status, output, error = self._run("contract-diff", "--before", str(before), "--after", str(broken))
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("UNRESOLVED", error)

    def test_no_canary_value_is_ever_printed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self._write(root, "before.json", _v2())
            reduced = self._write(root, "reduced.json", _v2(canaries=[{"label": "synthetic-prompt", "category": "prompt", "value": "TCANARY_PROMPT_11111111"}]))
            status, output, error = self._run("contract-diff", "--before", str(before), "--after", str(reduced))
        self.assertEqual(status, EXIT_REGRESSION)
        self.assertNotIn("TCANARY_", output + error)

    def test_help_documents_the_command(self) -> None:
        status, output, error = self._run("contract-diff", "--help")
        self.assertEqual(status, EXIT_PASS)
        self.assertIn("--before", output)
        self.assertIn("--after", output)


if __name__ == "__main__":
    unittest.main()
