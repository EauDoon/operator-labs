"""Bounded, in-memory run history."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import InputError, canonical_json, load_json
from tracecanary.checker import check_trace
from tracecanary.contract import load_contract
from tracecanary.history import DEFAULT_HISTORY_BOUND, HISTORY_VERSION, RunHistory, RunRecord
from tracecanary.otlp import validate_trace
from tracecanary.report import UnsafeReportError, Violation, build_report, render_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"
CANARY = "TCANARY_PROMPT_71f0e04f"

_TIMESTAMP_KEYS = ("timestamp", "time", "created", "modified", "date", "clock", "elapsed", "now", "utc", "epoch")


def _report(name: str = "leaked-prompt.json") -> dict:
    contract = load_contract(FIXTURES / "contract.json")
    payload = load_json(FIXTURES / name, max_bytes=contract.max_input_bytes, max_depth=contract.max_nesting)
    validate_trace(payload)
    return check_trace(contract, payload)


def _append(
    history: RunHistory,
    mode: str = "check",
    *,
    report: dict | None = None,
    group: str | None = None,
    values: tuple[str, ...] = (CANARY,),
) -> RunRecord:
    document = report if report is not None else _report()
    return history.append(
        mode=mode,
        contract_version=str(document["contract_version"]),
        status=str(document["status"]),
        summary=dict(document["summary"]),
        report=document,
        group=group,
        redacted_values=values,
    )


class RunRecordTests(unittest.TestCase):
    def test_sequence_is_insertion_ordered_and_starts_at_one(self) -> None:
        history = RunHistory()
        first = _append(history, "validate")
        second = _append(history, "check")
        third = _append(history, "diff")
        self.assertEqual((first.sequence, second.sequence, third.sequence), (1, 2, 3))
        self.assertEqual([item.sequence for item in history.records()], [1, 2, 3])

    def test_records_are_immutable(self) -> None:
        history = RunHistory()
        record = _append(history)
        with self.assertRaises(Exception):
            record.sequence = 99  # type: ignore[misc]

    def test_record_carries_the_declared_group(self) -> None:
        history = RunHistory()
        record = _append(history, group="nightly")
        self.assertEqual(record.group, "nightly")
        self.assertIsNone(_append(history).group)

    def test_latest_returns_the_newest_record(self) -> None:
        history = RunHistory()
        self.assertIsNone(history.latest())
        first = _append(history, "validate")
        second = _append(history, "check")
        self.assertIs(history.latest(), second)
        self.assertIsNot(history.latest(), first)


class BoundTests(unittest.TestCase):
    def test_default_bound_is_64(self) -> None:
        self.assertEqual(RunHistory().bound, DEFAULT_HISTORY_BOUND)
        self.assertEqual(DEFAULT_HISTORY_BOUND, 64)

    def test_bound_is_enforced(self) -> None:
        history = RunHistory(2)
        _append(history)
        _append(history)
        self.assertTrue(history.is_full())
        with self.assertRaises(InputError):
            _append(history)
        self.assertEqual(len(history.records()), 2)

    def test_clear_reopens_the_bound(self) -> None:
        history = RunHistory(1)
        _append(history)
        history.clear()
        self.assertEqual(history.records(), ())
        self.assertEqual(_append(history).sequence, 1)

    def test_invalid_bound_is_rejected(self) -> None:
        for bound in (0, -1):
            with self.subTest(bound=bound):
                with self.assertRaises(InputError):
                    RunHistory(bound)

    def test_invalid_input_is_rejected(self) -> None:
        history = RunHistory()
        with self.assertRaises(InputError):
            history.append(mode="", contract_version="x", status="pass", summary={}, report={})
        with self.assertRaises(InputError):
            history.append(mode="check", contract_version="x", status="maybe", summary={}, report={})
        with self.assertRaises(InputError):
            history.append(mode="check", contract_version="x", status="pass", summary=[], report={})
        with self.assertRaises(InputError):
            history.append(mode="check", contract_version="x", status="pass", summary={}, report="nope")
        with self.assertRaises(InputError):
            history.append(mode="check", contract_version="x", status="pass", summary={}, report={}, group="   ")


class ClearTests(unittest.TestCase):
    def test_clear_empties_records_and_values(self) -> None:
        history = RunHistory()
        _append(history)
        _append(history)
        self.assertEqual(len(history.records()), 2)
        self.assertEqual(history.redacted_values(), (CANARY,))
        history.clear()
        self.assertEqual(history.records(), ())
        self.assertEqual(history.redacted_values(), ())
        self.assertIsNone(history.latest())


class ExportTests(unittest.TestCase):
    def test_export_is_byte_stable_across_two_calls(self) -> None:
        history = RunHistory()
        _append(history, "validate")
        _append(history, "check")
        self.assertEqual(history.export(), history.export())

    def test_export_shape(self) -> None:
        history = RunHistory()
        _append(history, "check")
        payload = json.loads(history.export())
        self.assertEqual(payload["history_version"], HISTORY_VERSION)
        self.assertEqual(payload["bound"], DEFAULT_HISTORY_BOUND)
        self.assertEqual(payload["count"], 1)
        run = payload["runs"][0]
        self.assertEqual(set(run), {"sequence", "mode", "contract_version", "status", "summary", "report"})
        self.assertEqual(run["sequence"], 1)
        self.assertEqual(run["mode"], "check")

    def test_export_omits_the_group_when_absent_and_includes_it_when_declared(self) -> None:
        history = RunHistory()
        _append(history, "check")
        _append(history, "diff", group="nightly")
        runs = json.loads(history.export())["runs"]
        self.assertNotIn("group", runs[0])
        self.assertEqual(runs[1]["group"], "nightly")

    def test_export_contains_no_canary_value(self) -> None:
        history = RunHistory()
        _append(history, "check")
        _append(history, "diff")
        export = history.export()
        self.assertNotIn(CANARY, export)
        self.assertNotIn("TCANARY_", export)

    def test_export_fails_closed_when_a_record_would_leak(self) -> None:
        marker = "TCANARY_HISTORY_LEAK_31ab"
        history = RunHistory()
        history.append(
            mode="check",
            contract_version="tracecanary/v1",
            status="pass",
            summary={"total": 1},
            report={
                "contract_version": "tracecanary/v1",
                "mode": "check",
                "status": "pass",
                "summary": {"total": 1},
                "violations": [{"code": "TC001", "path": "", "message": marker}],
            },
            redacted_values=(marker,),
        )
        with self.assertRaises(UnsafeReportError):
            history.export()

    def test_export_rejects_a_canary_value_in_a_finding_key(self) -> None:
        marker = "TCANARY_HISTORY_KEY_4d21"
        history = RunHistory()
        history.append(
            mode="check",
            contract_version="tracecanary/v1",
            status="regression",
            summary={"total": 1},
            report={
                "contract_version": "tracecanary/v1",
                "mode": "check",
                "status": "regression",
                "summary": {"total": 1},
                "violations": [{"code": "TC002", "path": "", "message": "forbidden", "key": f"attr.{marker}", "scope": "span"}],
            },
            redacted_values=(marker,),
        )
        with self.assertRaises(UnsafeReportError):
            history.export()

    def test_export_rejects_a_canary_value_in_a_group_label(self) -> None:
        marker = "TCANARY_HISTORY_GROUP_77cd"
        history = RunHistory()
        _append(history, group=marker, values=(marker,))
        with self.assertRaises(UnsafeReportError):
            history.export()

    def test_extra_values_can_be_supplied_at_export_time(self) -> None:
        marker = "TCANARY_EXTRA_9e01"
        history = RunHistory()
        report = build_report("tracecanary/v1", "pass", [Violation("TC001", "", marker)], mode="check")
        history.append(mode="check", contract_version="tracecanary/v1", status="pass", summary=dict(report["summary"]), report=report)
        with self.assertRaises(UnsafeReportError):
            history.export(redacted_values=(marker,))
        self.assertIn(marker, history.export())

    def test_export_of_an_empty_history_is_valid(self) -> None:
        payload = json.loads(RunHistory().export())
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["runs"], [])


class NoTimestampTests(unittest.TestCase):
    def test_no_timestamp_key_appears_anywhere(self) -> None:
        history = RunHistory()
        _append(history, "check")
        _append(history, "diff")
        export = history.export().lower()
        for key in _TIMESTAMP_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, export)

    def test_no_clock_shaped_text_appears(self) -> None:
        history = RunHistory()
        _append(history)
        export = history.export()
        self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", export))
        self.assertIsNone(re.search(r"\d{2}:\d{2}:\d{2}", export))

    def test_two_identical_runs_export_identically(self) -> None:
        first = RunHistory()
        second = RunHistory()
        for history in (first, second):
            _append(history, "validate")
            _append(history, "check")
        self.assertEqual(first.export(), second.export())


class HistoryIndependenceTests(unittest.TestCase):
    def test_export_does_not_mutate_the_records(self) -> None:
        history = RunHistory()
        record = _append(history)
        before = canonical_json(record.report)
        history.export()
        self.assertEqual(canonical_json(record.report), before)

    def test_a_pass_run_can_be_recorded_and_rendered(self) -> None:
        history = RunHistory()
        report = build_report("tracecanary/v1", "pass", [], mode="check")
        record = history.append(
            mode="check",
            contract_version="tracecanary/v1",
            status="pass",
            summary=dict(report["summary"]),
            report=report,
        )
        self.assertEqual(record.status, "pass")
        exported = json.loads(history.export())["runs"][0]["report"]
        self.assertEqual(canonical_json(exported), render_json(report))


if __name__ == "__main__":
    unittest.main()
