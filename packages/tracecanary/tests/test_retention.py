from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import canonical_json
from tracecanary.checker import check_trace
from tracecanary.cli import EXIT_PASS, EXIT_REGRESSION, EXIT_UNRESOLVED, main
from tracecanary.comparison import diff_traces
from tracecanary.contract import ContractError, load_contract, parse_contract
from tracecanary.otlp import validate_trace
from tracecanary.report import UnsafeReportError, render_human, render_json

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"

RETENTION_VERSION = "tracecanary.retention/v1"
CANARY = "TCANARY_VALUE_0001"


def _attribute(key: str, value: str = "value", kind: str = "stringValue") -> dict:
    return {"key": key, "value": {kind: value}}


def _span(name: str = "span", attributes: tuple[dict, ...] = ()) -> dict:
    return {"name": name, "attributes": list(attributes)}


def _trace(
    spans: tuple[dict, ...],
    resource_attributes: tuple[dict, ...] = (),
    scope_attributes: tuple[dict, ...] | None = None,
) -> dict:
    scope: dict = {"name": "test.instrumentation"}
    if scope_attributes is not None:
        scope["attributes"] = list(scope_attributes)
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": list(resource_attributes)},
                "scopeSpans": [{"scope": scope, "spans": list(spans)}],
            }
        ]
    }


def _requirement(**overrides: object) -> dict:
    requirement: dict = {"requirement_id": "op", "scope": "span", "key": "gen_ai.operation.name"}
    requirement.update(overrides)
    return requirement


def _retention(requirements: list[dict], version: str = RETENTION_VERSION) -> dict:
    return {"version": version, "requirements": requirements}


def _contract(retention: dict | None = None, version: str = "tracecanary/v2", **extra: object) -> dict:
    data: dict = {
        "contract_version": version,
        "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
        "canaries": [{"label": "synthetic", "category": "test", "value": CANARY}],
        "required_retained_fields": [],
    }
    if retention is not None:
        data["retention"] = retention
    data.update(extra)
    return data


def _ratio_requirements() -> list[dict]:
    return [
        _requirement(requirement_id="operation-total", key="gen_ai.operation.name", minimum_count=1, comparison="presence"),
        _requirement(
            requirement_id="model-annotated",
            key="gen_ai.request.model",
            value_types=["stringValue"],
            minimum_count=1,
            comparison="matched_ratio",
            matching_keys=[{"scope": "resource", "key": "service.name"}],
            denominator_requirement_id="operation-total",
        ),
    ]


class V1ContractUnchangedTests(unittest.TestCase):
    """A v1 contract must parse and check exactly as it did before v2 existed."""

    def test_v1_fixture_contract_still_parses_without_retention(self) -> None:
        contract = parse_contract(
            {
                "contract_version": "tracecanary/v1",
                "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
                "canaries": [{"label": "a", "category": "test", "value": "synthetic"}],
                "required_retained_fields": [{"scope": "span", "key": "gen_ai.operation.name"}],
            }
        )
        self.assertEqual(contract.contract_version, "tracecanary/v1")
        self.assertIsNone(contract.retention)

    def test_v1_rejects_the_retention_field(self) -> None:
        data = _contract(version="tracecanary/v1", retention=_retention([_requirement()]))
        with self.assertRaisesRegex(ContractError, "unsupported"):
            parse_contract(data)

    def test_v1_rejection_messages_are_unchanged(self) -> None:
        base = {
            "contract_version": "tracecanary/v1",
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [{"label": "a", "category": "test", "value": "synthetic"}],
            "required_retained_fields": [],
        }
        with self.assertRaisesRegex(ContractError, "unsupported"):
            parse_contract({**base, "extra": 1})
        with self.assertRaisesRegex(ContractError, "missing required fields"):
            parse_contract({key: value for key, value in base.items() if key != "canaries"})
        with self.assertRaisesRegex(ContractError, "unsupported contract version"):
            parse_contract({**base, "contract_version": "tracecanary/v9"})
        with self.assertRaisesRegex(ContractError, "semantic-conventions"):
            parse_contract({**base, "semantic_conventions_version": "opentelemetry/semconv/9.9.9"})

    def test_v1_check_report_shape_is_unchanged(self) -> None:
        contract = load_contract(FIXTURES / "contract.json")
        payload = validate_and_load(FIXTURES / "safe-export.json", contract.max_input_bytes, contract.max_nesting)
        report = check_trace(contract, payload)
        self.assertEqual(
            set(report["summary"]),
            {
                "baseline_regressions",
                "canary_leaks",
                "forbidden_attributes",
                "forbidden_paths",
                "missing_retained_fields",
                "total",
            },
        )
        self.assertEqual(report["status"], "pass")

    def test_v2_accepts_every_v1_field(self) -> None:
        data: dict = {
            "contract_version": "tracecanary/v2",
            "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
            "canaries": [{"label": "a", "category": "test", "value": "synthetic"}],
            "forbidden_attribute_keys": ["gen_ai.prompt"],
            "forbidden_attribute_key_prefixes": ["enduser."],
            "forbidden_path_prefixes": ["/resourceSpans"],
            "required_retained_fields": [{"scope": "span", "key": "gen_ai.operation.name"}],
            "limits": {"max_input_bytes": 2048, "max_nesting": 10, "max_batch_files": 2},
        }
        contract = parse_contract(data)
        self.assertEqual(contract.contract_version, "tracecanary/v2")
        self.assertIsNone(contract.retention)
        self.assertEqual(contract.forbidden_attribute_keys, ("gen_ai.prompt",))
        self.assertEqual(contract.max_input_bytes, 2048)

    def test_v2_still_rejects_unknown_top_level_fields(self) -> None:
        with self.assertRaisesRegex(ContractError, "unsupported"):
            parse_contract(_contract(retention=_retention([_requirement()]), extra=1))


class RetentionValidationTests(unittest.TestCase):
    def _assert_invalid_retention(self, retention: object, fragment: str) -> None:
        with self.assertRaisesRegex(ContractError, re.escape(fragment)):
            parse_contract(_contract(retention=retention))

    def _assert_invalid_requirements(self, requirements: object, fragment: str) -> None:
        self._assert_invalid_retention(_retention(requirements), fragment)

    def _assert_invalid_requirement(self, requirement: dict, fragment: str) -> None:
        self._assert_invalid_requirements([requirement], fragment)

    def test_valid_optional_fields_default_correctly(self) -> None:
        contract = parse_contract(_contract(retention=_retention([_requirement()])))
        assert contract.retention is not None
        requirement = contract.retention.requirements[0]
        self.assertIsNone(requirement.value_types)
        self.assertEqual(requirement.minimum_count, 1)
        self.assertEqual(requirement.comparison, "presence")
        self.assertIsNone(requirement.matching_keys)
        self.assertIsNone(requirement.denominator_requirement_id)

    def test_retention_must_be_an_object(self) -> None:
        self._assert_invalid_retention([], "retention must be a JSON object")

    def test_retention_rejects_unsupported_fields(self) -> None:
        self._assert_invalid_retention({"version": RETENTION_VERSION, "requirements": [_requirement()], "extra": 1}, "retention contains unsupported fields")

    def test_retention_version_is_required(self) -> None:
        self._assert_invalid_retention({"requirements": [_requirement()]}, "retention requires a version")

    def test_retention_version_is_pinned(self) -> None:
        self._assert_invalid_retention(_retention([_requirement()], version="tracecanary.retention/v9"), "tracecanary.retention/v1")

    def test_requirements_are_required(self) -> None:
        self._assert_invalid_retention({"version": RETENTION_VERSION}, "retention requires requirements")

    def test_requirements_must_be_a_non_empty_array(self) -> None:
        for value in ([], {}, "op"):
            with self.subTest(value=value):
                self._assert_invalid_requirements(value, "retention.requirements must be a non-empty array")

    def test_requirements_are_bounded(self) -> None:
        requirements = [_requirement(requirement_id=f"r{index}", key=f"key.{index}") for index in range(65)]
        self._assert_invalid_requirements(requirements, "at most 64")

    def test_requirement_must_be_an_object(self) -> None:
        self._assert_invalid_requirements(["op"], "must be a JSON object")

    def test_requirement_rejects_unsupported_fields(self) -> None:
        self._assert_invalid_requirement({**_requirement(), "bonus": 1}, "contains unsupported fields")

    def test_requirement_id_is_required_and_non_empty(self) -> None:
        self._assert_invalid_requirement({"scope": "span", "key": "k"}, "non-empty requirement_id")
        self._assert_invalid_requirement({"requirement_id": "", "scope": "span", "key": "k"}, "non-empty requirement_id")

    def test_requirement_id_length_is_bounded(self) -> None:
        self._assert_invalid_requirement(_requirement(requirement_id="a" * 65), "at most 64 characters")

    def test_requirement_id_pattern_is_enforced(self) -> None:
        for value in ("_leading", "has space", "trailing!"):
            with self.subTest(value=value):
                self._assert_invalid_requirement(_requirement(requirement_id=value), "[A-Za-z0-9][A-Za-z0-9._:/-]*")

    def test_requirement_id_must_be_unique(self) -> None:
        self._assert_invalid_requirements([_requirement(), _requirement(key="other.key")], "repeats an existing requirement_id")

    def test_scope_is_required_and_pinned(self) -> None:
        self._assert_invalid_requirement({"requirement_id": "op", "key": "k"}, "scope must be one of")
        self._assert_invalid_requirement(_requirement(scope="attribute"), "scope must be one of")

    def test_all_documented_scopes_are_accepted(self) -> None:
        for scope in ("resource", "scope", "span", "event", "link"):
            with self.subTest(scope=scope):
                contract = parse_contract(_contract(retention=_retention([_requirement(scope=scope)])))
                assert contract.retention is not None
                self.assertEqual(contract.retention.requirements[0].scope, scope)

    def test_key_is_required_and_non_empty(self) -> None:
        self._assert_invalid_requirement({"requirement_id": "op", "scope": "span"}, "key must be a non-empty string")
        self._assert_invalid_requirement(_requirement(key=""), "key must be a non-empty string")

    def test_value_types_must_be_a_non_empty_array(self) -> None:
        for value in ([], "stringValue"):
            with self.subTest(value=value):
                self._assert_invalid_requirement(_requirement(value_types=value), "value_types must be a non-empty array")

    def test_value_types_are_pinned(self) -> None:
        self._assert_invalid_requirement(_requirement(value_types=["stringValue", "textValue"]), "unsupported OTLP value kind")

    def test_value_types_must_not_contain_duplicates(self) -> None:
        self._assert_invalid_requirement(_requirement(value_types=["stringValue", "stringValue"]), "must not contain duplicates")

    def test_minimum_count_must_be_a_positive_integer(self) -> None:
        for value in (0, -1, True, 1.5, "1"):
            with self.subTest(value=value):
                self._assert_invalid_requirement(_requirement(minimum_count=value), "integer of at least 1")

    def test_comparison_is_pinned(self) -> None:
        self._assert_invalid_requirement(_requirement(comparison="ratio"), "comparison must be one of")

    def test_matching_keys_must_be_a_non_empty_array(self) -> None:
        for value in ([], "service.name"):
            with self.subTest(value=value):
                self._assert_invalid_requirement(
                    _requirement(comparison="matched_ratio", matching_keys=value, denominator_requirement_id="other"),
                    "matching_keys must be a non-empty array",
                )

    def test_matching_keys_are_bounded(self) -> None:
        keys = [{"scope": "span", "key": f"key.{index}"} for index in range(9)]
        self._assert_invalid_requirement(
            _requirement(comparison="matched_ratio", matching_keys=keys, denominator_requirement_id="other"),
            "at most 8",
        )

    def test_matching_key_requires_exactly_scope_and_key(self) -> None:
        self._assert_invalid_requirement(
            _requirement(comparison="matched_ratio", matching_keys=[{"scope": "span"}], denominator_requirement_id="other"),
            "without exactly scope and key",
        )

    def test_matching_key_scope_and_key_must_be_valid(self) -> None:
        self._assert_invalid_requirement(
            _requirement(comparison="matched_ratio", matching_keys=[{"scope": "bogus", "key": "k"}], denominator_requirement_id="other"),
            "matching key scope or key is invalid",
        )

    def test_matching_keys_must_be_unique(self) -> None:
        keys = [{"scope": "span", "key": "k"}, {"scope": "span", "key": "k"}]
        self._assert_invalid_requirement(
            _requirement(comparison="matched_ratio", matching_keys=keys, denominator_requirement_id="other"),
            "matching keys must be unique",
        )

    def test_denominator_must_name_another_requirement(self) -> None:
        self._assert_invalid_requirements(
            [_requirement(), _requirement(requirement_id="second", key="other.key", comparison="matched_ratio", matching_keys=[{"scope": "span", "key": "k"}], denominator_requirement_id="missing")],
            "unknown denominator_requirement_id",
        )

    def test_matched_ratio_requires_matching_keys(self) -> None:
        self._assert_invalid_requirements(
            [_requirement(), _requirement(requirement_id="second", key="other.key", comparison="matched_ratio", denominator_requirement_id="op")],
            "requires matching_keys for the matched_ratio comparison",
        )

    def test_matched_ratio_requires_a_denominator(self) -> None:
        self._assert_invalid_requirements(
            [_requirement(), _requirement(requirement_id="second", key="other.key", comparison="matched_ratio", matching_keys=[{"scope": "span", "key": "k"}])],
            "requires denominator_requirement_id for the matched_ratio comparison",
        )

    def test_matching_keys_are_rejected_outside_matched_ratio(self) -> None:
        self._assert_invalid_requirement(_requirement(comparison="count", matching_keys=[{"scope": "span", "key": "k"}]), "must not declare matching_keys")

    def test_denominator_is_rejected_outside_matched_ratio(self) -> None:
        self._assert_invalid_requirements(
            [_requirement(), _requirement(requirement_id="second", key="other.key", comparison="count", denominator_requirement_id="op")],
            "must not declare denominator_requirement_id",
        )

    def test_denominator_cannot_be_the_requirement_itself(self) -> None:
        self._assert_invalid_requirements(
            [
                _requirement(requirement_id="first", key="a.key"),
                _requirement(
                    requirement_id="second",
                    key="b.key",
                    comparison="matched_ratio",
                    matching_keys=[{"scope": "span", "key": "k"}],
                    denominator_requirement_id="second",
                ),
            ],
            "must not name itself as its denominator",
        )

    def test_denominator_cycles_are_rejected(self) -> None:
        self._assert_invalid_requirements(
            [
                _requirement(
                    requirement_id="first",
                    key="a.key",
                    comparison="matched_ratio",
                    matching_keys=[{"scope": "span", "key": "k"}],
                    denominator_requirement_id="second",
                ),
                _requirement(
                    requirement_id="second",
                    key="b.key",
                    comparison="matched_ratio",
                    matching_keys=[{"scope": "span", "key": "k"}],
                    denominator_requirement_id="first",
                ),
            ],
            "creates a denominator cycle",
        )

    def test_retention_keys_cannot_contain_canary_values(self) -> None:
        for requirement in (_requirement(key=f"prefix.{CANARY}"), _requirement(requirement_id=CANARY)):
            with self.subTest(requirement=requirement):
                with self.assertRaises(ContractError) as raised:
                    parse_contract(_contract(retention=_retention([requirement])))
                self.assertNotIn(CANARY, str(raised.exception))

    def test_matching_keys_cannot_contain_canary_values(self) -> None:
        requirement = _requirement(
            requirement_id="second",
            key="other.key",
            comparison="matched_ratio",
            matching_keys=[{"scope": "span", "key": CANARY}],
            denominator_requirement_id="op",
        )
        with self.assertRaises(ContractError) as raised:
            parse_contract(_contract(retention=_retention([_requirement(), requirement])))
        self.assertNotIn(CANARY, str(raised.exception))


class RetentionCheckTests(unittest.TestCase):
    def _check(self, requirements: list[dict], trace: dict) -> dict:
        contract = parse_contract(_contract(retention=_retention(requirements)))
        validate_trace(trace)
        return check_trace(contract, trace)

    def test_tc010_fires_when_minimum_count_is_not_met(self) -> None:
        trace = _trace((_span(attributes=(_attribute("other.key"),)),))
        report = self._check([_requirement()], trace)
        self.assertEqual(report["status"], "regression")
        self.assertEqual(report["summary"]["retention_failures"], 1)
        self.assertEqual(
            report["violations"],
            [{"code": "TC010", "message": "retention requirement was not met", "path": "", "key": "op", "scope": "span"}],
        )

    def test_tc010_does_not_fire_when_minimum_count_is_met(self) -> None:
        trace = _trace((_span(attributes=(_attribute("gen_ai.operation.name", "chat"),)),))
        report = self._check([_requirement()], trace)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["violations"], [])

    def test_tc010_counts_every_matching_item(self) -> None:
        spans = tuple(_span(attributes=(_attribute("gen_ai.operation.name", "chat"),)) for _ in range(2))
        met = self._check([_requirement(minimum_count=2)], _trace(spans))
        self.assertEqual(met["status"], "pass")
        unmet = self._check([_requirement(minimum_count=3)], _trace(spans))
        self.assertEqual([item["code"] for item in unmet["violations"]], ["TC010"])

    def test_tc010_uses_the_declared_scope(self) -> None:
        trace = _trace((_span(attributes=(_attribute("gen_ai.operation.name", "chat"),)),), resource_attributes=())
        report = self._check([_requirement(scope="resource", key="service.name")], trace)
        self.assertEqual(report["violations"][0]["scope"], "resource")

    def test_tc011_fires_for_a_value_kind_mismatch(self) -> None:
        trace = _trace((_span(attributes=(_attribute("gen_ai.operation.name", "7", "intValue"),)),))
        report = self._check([_requirement(value_types=["stringValue"])], trace)
        self.assertEqual([item["code"] for item in report["violations"]], ["TC011"])
        self.assertEqual(report["violations"][0]["key"], "op")
        self.assertEqual(report["violations"][0]["path"], "")
        self.assertEqual(report["status"], "regression")

    def test_tc011_does_not_fire_when_the_declared_kinds_include_the_observed_kind(self) -> None:
        trace = _trace((_span(attributes=(_attribute("gen_ai.operation.name", "7", "intValue"),)),))
        report = self._check([_requirement(value_types=["stringValue", "intValue"])], trace)
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["status"], "pass")

    def test_tc011_does_not_fire_when_no_attribute_matches(self) -> None:
        trace = _trace((_span(attributes=(_attribute("other.key"),)),))
        report = self._check([_requirement(value_types=["stringValue"])], trace)
        self.assertEqual([item["code"] for item in report["violations"]], ["TC010"])

    def test_tc011_is_not_emitted_without_declared_value_types(self) -> None:
        trace = _trace((_span(attributes=(_attribute("gen_ai.operation.name", "7", "intValue"),)),))
        report = self._check([_requirement()], trace)
        self.assertEqual(report["violations"], [])

    def test_event_and_link_scopes_are_checked(self) -> None:
        span = {"name": "s", "attributes": [], "events": [{"name": "e", "attributes": [_attribute("event.key")]}]}
        trace = _trace((span,))
        report = self._check([_requirement(scope="event", key="event.key")], trace)
        self.assertEqual(report["violations"], [])
        report = self._check([_requirement(scope="link", key="event.key")], trace)
        self.assertEqual([item["code"] for item in report["violations"]], ["TC010"])


class RetentionComparisonTests(unittest.TestCase):
    def _diff(self, requirements: list[dict], baseline: dict, candidate: dict) -> dict:
        contract = parse_contract(_contract(retention=_retention(requirements)))
        validate_trace(baseline)
        validate_trace(candidate)
        return diff_traces(contract, baseline, candidate)

    def _spans(self, count: int, models: int) -> tuple[dict, ...]:
        spans = []
        for index in range(count):
            attributes = [_attribute("gen_ai.operation.name", "chat")]
            if index < models:
                attributes.append(_attribute("gen_ai.request.model", "synthetic-model"))
            spans.append(_span(attributes=tuple(attributes)))
        return tuple(spans)

    def _service_trace(self, service: str, count: int, models: int) -> dict:
        return _trace(self._spans(count, models), resource_attributes=(_attribute("service.name", service),))

    def test_presence_mode_compares_only_against_minimum_count(self) -> None:
        baseline = self._service_trace("alpha", 3, 0)
        candidate = self._service_trace("alpha", 1, 0)
        report = self._diff([_requirement(comparison="presence")], baseline, candidate)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["violations"], [])

    def test_presence_mode_still_reports_an_unmet_requirement(self) -> None:
        baseline = self._service_trace("alpha", 1, 0)
        candidate = _trace((_span(attributes=(_attribute("other.key"),)),), resource_attributes=(_attribute("service.name", "alpha"),))
        report = self._diff([_requirement(comparison="presence")], baseline, candidate)
        self.assertEqual(report["status"], "regression")
        self.assertEqual([item["code"] for item in report["violations"]], ["TC010"])

    def test_tc012_fires_only_on_a_strict_decrease(self) -> None:
        requirements = [_requirement(comparison="count")]
        baseline = self._service_trace("alpha", 3, 0)
        candidate = self._service_trace("alpha", 1, 0)
        report = self._diff(requirements, baseline, candidate)
        self.assertEqual([item["code"] for item in report["violations"]], ["TC012"])
        self.assertEqual(report["violations"][0]["detail"], "baseline_count=3 candidate_count=1")
        self.assertEqual(report["summary"]["retention_regressions"], 1)

    def test_tc012_does_not_fire_on_an_equal_count(self) -> None:
        requirements = [_requirement(comparison="count")]
        report = self._diff(requirements, self._service_trace("alpha", 2, 0), self._service_trace("alpha", 2, 0))
        self.assertEqual(report["status"], "pass")

    def test_tc012_does_not_fire_on_an_increased_count(self) -> None:
        requirements = [_requirement(comparison="count")]
        report = self._diff(requirements, self._service_trace("alpha", 2, 0), self._service_trace("alpha", 5, 0))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["violations"], [])

    def test_tc013_fires_on_a_genuine_ratio_regression(self) -> None:
        baseline = self._service_trace("alpha", 4, 4)
        candidate = self._service_trace("alpha", 4, 1)
        report = self._diff(_ratio_requirements(), baseline, candidate)
        self.assertEqual([item["code"] for item in report["violations"]], ["TC013"])
        self.assertEqual(report["violations"][0]["detail"], "baseline_count=4 baseline_total=4 candidate_count=1 candidate_total=4")
        self.assertEqual(report["status"], "regression")

    def test_tc013_does_not_fire_on_an_equal_ratio(self) -> None:
        baseline = self._service_trace("alpha", 4, 2)
        candidate = self._service_trace("alpha", 4, 2)
        report = self._diff(_ratio_requirements(), baseline, candidate)
        self.assertEqual(report["status"], "pass")

    def test_tc014_fires_when_an_identity_is_present_in_only_one_population(self) -> None:
        baseline = self._service_trace("alpha", 2, 2)
        candidate = self._service_trace("beta", 2, 2)
        report = self._diff(_ratio_requirements(), baseline, candidate)
        self.assertEqual(report["status"], "unresolved")
        self.assertEqual(sorted(item["detail"] for item in report["violations"]), ["identity-absent-baseline", "identity-absent-candidate"])
        self.assertEqual(report["summary"]["unresolved_comparisons"], 2)

    def test_tc014_fires_when_the_declared_denominator_is_zero(self) -> None:
        def split(service: str) -> dict:
            return _trace(
                (_span(attributes=(_attribute("gen_ai.request.model", "synthetic-model"),)),),
                resource_attributes=(_attribute("service.name", service),),
            )

        baseline = {
            "resourceSpans": [
                split("alpha")["resourceSpans"][0],
                _trace((_span(attributes=(_attribute("gen_ai.operation.name", "chat"),)),), resource_attributes=(_attribute("service.name", "beta"),))["resourceSpans"][0],
            ]
        }
        report = self._diff(_ratio_requirements(), baseline, baseline)
        self.assertEqual(report["status"], "unresolved")
        self.assertEqual([item["detail"] for item in report["violations"]], ["denominator-undefined"])

    def test_tc014_fires_when_identity_cannot_be_established(self) -> None:
        baseline = self._service_trace("alpha", 2, 2)
        candidate = _trace(self._spans(2, 2))
        report = self._diff(_ratio_requirements(), baseline, candidate)
        self.assertEqual(report["status"], "unresolved")
        self.assertIn("identity-unestablished", [item["detail"] for item in report["violations"]])

    def test_an_unresolved_comparison_is_never_a_pass(self) -> None:
        baseline = self._service_trace("alpha", 2, 2)
        candidate = self._service_trace("beta", 2, 2)
        report = self._diff(_ratio_requirements(), baseline, candidate)
        self.assertNotEqual(report["status"], "pass")
        self.assertEqual(report["status"], "unresolved")


class RetentionCliTests(unittest.TestCase):
    def _run(self, command: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(command)
        return status, output.getvalue(), error.getvalue()

    def _write(self, directory: Path, name: str, data: dict) -> Path:
        path = directory / name
        path.write_text(canonical_json(data), encoding="utf-8")
        return path

    def _service_trace(self, service: str, count: int, models: int) -> dict:
        spans = []
        for index in range(count):
            attributes = [_attribute("gen_ai.operation.name", "chat")]
            if index < models:
                attributes.append(_attribute("gen_ai.request.model", "synthetic-model"))
            spans.append(_span(attributes=tuple(attributes)))
        return _trace(tuple(spans), resource_attributes=(_attribute("service.name", service),))

    def test_unresolved_matched_ratio_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._write(root, "contract.json", _contract(retention=_retention(_ratio_requirements())))
            baseline = self._write(root, "baseline.json", self._service_trace("alpha", 2, 2))
            candidate = self._write(root, "candidate.json", self._service_trace("beta", 2, 2))
            status, output, error = self._run(["diff", "--contract", str(contract), "--baseline", str(baseline), "--candidate", str(candidate)])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertIn("TC014", output)
        self.assertEqual(error, "")

    def test_zero_denominator_exits_two(self) -> None:
        def unnamed(service: str) -> dict:
            return _trace((_span(attributes=(_attribute("gen_ai.request.model", "synthetic-model"),)),), resource_attributes=(_attribute("service.name", service),))

        trace = {
            "resourceSpans": [
                unnamed("alpha")["resourceSpans"][0],
                _trace((_span(attributes=(_attribute("gen_ai.operation.name", "chat"),)),), resource_attributes=(_attribute("service.name", "beta"),))["resourceSpans"][0],
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._write(root, "contract.json", _contract(retention=_retention(_ratio_requirements())))
            baseline = self._write(root, "baseline.json", trace)
            candidate = self._write(root, "candidate.json", trace)
            status, output, error = self._run(["diff", "--contract", str(contract), "--baseline", str(baseline), "--candidate", str(candidate)])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertIn("TC014", output)

    def test_retention_regression_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._write(root, "contract.json", _contract(retention=_retention([_requirement(comparison="count")])))
            baseline = self._write(root, "baseline.json", self._service_trace("alpha", 3, 0))
            candidate = self._write(root, "candidate.json", self._service_trace("alpha", 1, 0))
            status, output, error = self._run(["diff", "--contract", str(contract), "--baseline", str(baseline), "--candidate", str(candidate)])
        self.assertEqual(status, EXIT_REGRESSION)
        self.assertIn("TC012", output)

    def test_satisfied_retention_contract_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = self._write(root, "contract.json", _contract(retention=_retention([_requirement()])))
            trace = self._write(root, "trace.json", self._service_trace("alpha", 1, 0))
            status, output, error = self._run(["check", "--contract", str(contract), "--input", str(trace)])
        self.assertEqual(status, EXIT_PASS)
        self.assertIn("PASS", output)

    def test_canary_in_a_retention_key_fails_closed_through_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write(root, "contract.json", _contract(retention=_retention([_requirement(key=f"prefix.{CANARY}")])))
            status, output, error = self._run(["validate", str(path)])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertNotIn(CANARY, output + error)

    def test_structural_canary_collision_still_fails_closed(self) -> None:
        marker = "tracecanary/v2"
        data = _contract(retention=_retention([_requirement()]))
        data["canaries"] = [{"label": "safe", "category": "test", "value": marker}]
        contract = parse_contract(data)
        trace = _trace((_span(attributes=(_attribute("gen_ai.operation.name", "chat"),)),))
        validate_trace(trace)
        with self.assertRaises(UnsafeReportError):
            check_trace(contract, trace)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = self._write(root, "contract.json", data)
            trace_path = self._write(root, "trace.json", trace)
            status, output, error = self._run(["check", "--contract", str(contract_path), "--input", str(trace_path)])
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")


class RetentionLeakageTests(unittest.TestCase):
    def _rendered(self, report: dict) -> str:
        return render_json(report) + render_human(report)

    def test_canary_in_attribute_key_span_name_and_identity_value_is_not_rendered(self) -> None:
        contract = parse_contract(_contract(retention=_retention(_ratio_requirements())))
        trace = {
            "resourceSpans": [
                {
                    "resource": {"attributes": [_attribute("service.name", CANARY)]},
                    "scopeSpans": [
                        {
                            "scope": {"name": "test.instrumentation"},
                            "spans": [{"name": CANARY, "attributes": [_attribute(CANARY, "benign"), _attribute("gen_ai.operation.name", "chat")]}],
                        }
                    ],
                }
            ]
        }
        validate_trace(trace)
        report = check_trace(contract, trace)
        self.assertEqual(report["status"], "regression")
        self.assertIn("TC001", [item["code"] for item in report["violations"]])
        self.assertNotIn(CANARY, self._rendered(report))

    def test_canary_in_a_matching_key_value_is_not_rendered_by_a_diff(self) -> None:
        def build(service: str, models: int) -> dict:
            attributes = [_attribute("gen_ai.operation.name", "chat")]
            if models:
                attributes.append(_attribute("gen_ai.request.model", "synthetic-model"))
            return _trace((_span(attributes=tuple(attributes)),), resource_attributes=(_attribute("service.name", service),))

        contract = parse_contract(_contract(retention=_retention(_ratio_requirements())))
        baseline = build(CANARY, 1)
        candidate = build(CANARY, 0)
        validate_trace(baseline)
        validate_trace(candidate)
        report = diff_traces(contract, baseline, candidate)
        self.assertEqual(report["status"], "unresolved")
        self.assertNotIn(CANARY, self._rendered(report))

    def test_identity_values_are_never_rendered(self) -> None:
        def build(service: str, models: int) -> dict:
            attributes = [_attribute("gen_ai.operation.name", "chat")]
            if models:
                attributes.append(_attribute("gen_ai.request.model", "synthetic-model"))
            return _trace((_span(attributes=tuple(attributes)),), resource_attributes=(_attribute("service.name", service),))

        contract = parse_contract(_contract(retention=_retention(_ratio_requirements())))
        baseline = build("alpha-service", 1)
        candidate = build("alpha-service", 0)
        validate_trace(baseline)
        validate_trace(candidate)
        report = diff_traces(contract, baseline, candidate)
        self.assertEqual([item["code"] for item in report["violations"]], ["TC010", "TC013"])
        self.assertNotIn("alpha-service", self._rendered(report))

    def test_retention_findings_never_carry_attribute_paths(self) -> None:
        contract = parse_contract(_contract(retention=_retention([_requirement(value_types=["stringValue"])])))
        trace = _trace((_span(attributes=(_attribute("gen_ai.operation.name", "7", "intValue"),)),))
        validate_trace(trace)
        report = check_trace(contract, trace)
        self.assertEqual([item["path"] for item in report["violations"]], [""])
        self.assertNotIn("resourceSpans", self._rendered(report))


class RetentionDeterminismTests(unittest.TestCase):
    def test_reordered_equivalent_traces_produce_identical_check_reports(self) -> None:
        contract = parse_contract(_contract(retention=_retention([_requirement(minimum_count=2, value_types=["stringValue"])])))
        first = {
            "resourceSpans": [
                {
                    "resource": {"attributes": [_attribute("service.name", "alpha"), _attribute("deployment.environment.name", "test")]},
                    "scopeSpans": [
                        {"scope": {"name": "one"}, "spans": [_span(attributes=(_attribute("gen_ai.operation.name", "chat"),))]},
                        {"scope": {"name": "two"}, "spans": [_span(attributes=(_attribute("gen_ai.operation.name", "7", "intValue"),))]},
                    ],
                }
            ]
        }
        second = {
            "resourceSpans": [
                {
                    "resource": {"attributes": [_attribute("deployment.environment.name", "test"), _attribute("service.name", "alpha")]},
                    "scopeSpans": [
                        {"scope": {"name": "two"}, "spans": [_span(attributes=(_attribute("gen_ai.operation.name", "7", "intValue"),))]},
                        {"scope": {"name": "one"}, "spans": [_span(attributes=(_attribute("gen_ai.operation.name", "chat"),))]},
                    ],
                }
            ]
        }
        validate_trace(first)
        validate_trace(second)
        self.assertEqual(check_trace(contract, first), check_trace(contract, second))

    def test_reordered_candidate_produces_an_identical_diff_report(self) -> None:
        def build(names: tuple[str, ...]) -> dict:
            return _trace(tuple(_span(attributes=(_attribute("gen_ai.operation.name", name),)) for name in names))

        contract = parse_contract(_contract(retention=_retention([_requirement(comparison="count")])))
        baseline = build(("a", "b", "c"))
        candidate = build(("a", "b"))
        reordered = build(("b", "a"))
        validate_trace(baseline)
        validate_trace(candidate)
        validate_trace(reordered)
        self.assertEqual(diff_traces(contract, baseline, candidate), diff_traces(contract, baseline, reordered))


def validate_and_load(path: Path, max_bytes: int, max_depth: int) -> dict:
    from tracecanary.canonical import load_json

    payload = load_json(path, max_bytes=max_bytes, max_depth=max_depth)
    validate_trace(payload)
    return payload


if __name__ == "__main__":
    unittest.main()
