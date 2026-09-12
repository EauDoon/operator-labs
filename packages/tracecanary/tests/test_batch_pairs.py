"""Bounded baseline/candidate batch pairing."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary import batch_pairs
from tracecanary.batch_pairs import BATCH_DIFF_VERSION, PAIRING_MODES, batch_diff
from tracecanary.canonical import InputError, canonical_json
from tracecanary.cli import EXIT_PASS, EXIT_REGRESSION, EXIT_UNRESOLVED, main
from tracecanary.contract import load_contract
from tracecanary.report import render_junit, render_sarif


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "v1"
CONTRACT = FIXTURES / "contract.json"
CANARIES = tuple(canary.value for canary in load_contract(CONTRACT).canaries)


class _Dirs:
    """Two temporary pairing directories that clean themselves up."""

    def __init__(self, case: unittest.TestCase) -> None:
        self._root = Path(tempfile.mkdtemp())
        case.addCleanup(self._cleanup)
        self.baseline = self._root / "baseline"
        self.candidate = self._root / "candidate"
        self.baseline.mkdir()
        self.candidate.mkdir()

    def _cleanup(self) -> None:
        for path in sorted(self._root.rglob("*"), reverse=True):
            try:
                path.unlink() if path.is_file() else path.rmdir()
            except OSError:  # pragma: no cover - best effort cleanup
                pass
        self._root.rmdir()

    def write(self, side: str, name: str, source: str | None) -> None:
        target = getattr(self, side) / name
        if source is None:
            target.write_text("{not json", encoding="utf-8")
            return
        target.write_bytes((FIXTURES / source).read_bytes())


class PairingHappyPathTests(unittest.TestCase):
    def test_passing_batch_diff(self) -> None:
        dirs = _Dirs(self)
        for name in ("a.json", "b.json"):
            dirs.write("baseline", name, "safe-export.json")
            dirs.write("candidate", name, "safe-export.json")
        report = batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["batch_version"], BATCH_DIFF_VERSION)
        self.assertEqual(report["pairing"], "filename")
        self.assertEqual([item["id"] for item in report["items"]], ["pair-0001", "pair-0002"])
        self.assertNotIn("path", report["items"][0])

    def test_regression_batch_diff(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "missing-operational-fields.json")
        report = batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate)
        self.assertEqual(report["status"], "regression")
        self.assertEqual(report["items"][0]["status"], "regression")

    def test_pairs_are_processed_in_a_deterministic_order(self) -> None:
        dirs = _Dirs(self)
        names = ["c.json", "a.json", "b.json"]
        for name in names:
            dirs.write("baseline", name, "safe-export.json")
            dirs.write("candidate", name, "safe-export.json")
        first = canonical_json(batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate))
        second = canonical_json(batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate))
        self.assertEqual(first, second)
        report = batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate)
        self.assertEqual([item["id"] for item in report["items"]], ["pair-0001", "pair-0002", "pair-0003"])

    def test_order_pairing_pairs_positionally(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "z-baseline.json", "safe-export.json")
        dirs.write("candidate", "a-candidate.json", "safe-export.json")
        report = batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate, pairing="order", include_paths=True)
        self.assertEqual(report["status"], "pass")
        item = report["items"][0]
        self.assertEqual(item["baseline_name"], "z-baseline.json")
        self.assertEqual(item["candidate_name"], "a-candidate.json")

    def test_recursive_discovery_and_relative_names(self) -> None:
        dirs = _Dirs(self)
        (dirs.baseline / "nested").mkdir()
        (dirs.candidate / "nested").mkdir()
        dirs.write("baseline", "nested/inner.json", "safe-export.json")
        dirs.write("candidate", "nested/inner.json", "safe-export.json")
        report = batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate, recursive=True, include_paths=True)
        self.assertEqual(report["items"][0]["candidate_name"], "nested/inner.json")

    def test_include_paths_never_echoes_a_host_path(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "safe-export.json")
        report = batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate, include_paths=True)
        text = canonical_json(report)
        self.assertIn("a.json", text)
        self.assertNotIn(str(dirs._root), text)
        self.assertNotIn(str(ROOT), text)


class PairingFailureTests(unittest.TestCase):
    """A pair that cannot be compared must never produce an apparent pass."""

    def test_missing_candidate_is_unresolved(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("baseline", "b.json", "safe-export.json")
        dirs.write("candidate", "a.json", "safe-export.json")
        with self.assertRaises(InputError) as caught:
            batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate)
        self.assertIn("candidate", str(caught.exception))
        self.assertIn("missing", str(caught.exception))

    def test_missing_baseline_is_unresolved(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "safe-export.json")
        dirs.write("candidate", "b.json", "safe-export.json")
        with self.assertRaises(InputError) as caught:
            batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate)
        self.assertIn("baseline", str(caught.exception))
        self.assertIn("missing", str(caught.exception))

    def test_count_mismatch_under_order_pairing_is_unresolved(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("baseline", "b.json", "safe-export.json")
        dirs.write("candidate", "a.json", "safe-export.json")
        with self.assertRaises(InputError) as caught:
            batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate, pairing="order")
        self.assertIn("same number of files", str(caught.exception))

    def test_case_only_name_collision_is_ambiguous(self) -> None:
        """Two names that differ only by case cannot be paired by name.

        The collision is constructed directly because a case-insensitive
        filesystem cannot hold both files at once.
        """
        path = FIXTURES / "safe-export.json"
        with self.assertRaises(InputError) as caught:
            batch_pairs._by_name([("a.json", path), ("A.json", path)], "baseline")
        self.assertIn("ambiguous", str(caught.exception))
        self.assertIn("differ only by case", str(caught.exception))

    def test_repeated_relative_name_is_ambiguous(self) -> None:
        path = FIXTURES / "safe-export.json"
        with self.assertRaises(InputError) as caught:
            batch_pairs._by_name([("a.json", path), ("a.json", path)], "candidate")
        self.assertIn("ambiguous", str(caught.exception))

    def test_invalid_candidate_is_unresolved(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", None)
        report = batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate)
        self.assertEqual(report["status"], "unresolved")
        self.assertEqual(report["items"][0]["status"], "unresolved")
        self.assertEqual(report["items"][0]["report"]["violations"][0]["code"], "TC006")

    def test_invalid_baseline_is_unresolved(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", None)
        dirs.write("candidate", "a.json", "safe-export.json")
        self.assertEqual(batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate)["status"], "unresolved")

    def test_baseline_that_fails_the_contract_is_unresolved(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "missing-operational-fields.json")
        dirs.write("candidate", "a.json", "safe-export.json")
        report = batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate)
        self.assertEqual(report["status"], "unresolved")
        self.assertEqual(report["items"][0]["report"]["violations"][0]["code"], "TC900")

    def test_unresolved_pair_outranks_a_regression(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "missing-operational-fields.json")
        dirs.write("baseline", "b.json", "safe-export.json")
        dirs.write("candidate", "b.json", None)
        self.assertEqual(batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate)["status"], "unresolved")

    def test_empty_and_missing_directories_are_unresolved(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "safe-export.json")
        with self.assertRaises(InputError):
            batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.baseline / "nope")
        with self.assertRaises(InputError):
            batch_diff(load_contract(CONTRACT), dirs.baseline, dirs._root / "empty-candidate")

    def test_pair_count_is_bounded_by_the_contract(self) -> None:
        dirs = _Dirs(self)
        with tempfile.TemporaryDirectory() as directory:
            contract_path = Path(directory) / "contract.json"
            data = json.loads(CONTRACT.read_text(encoding="utf-8"))
            data["limits"]["max_batch_files"] = 1
            contract_path.write_text(canonical_json(data), encoding="utf-8")
            contract = load_contract(contract_path)
            dirs.write("baseline", "a.json", "safe-export.json")
            dirs.write("baseline", "b.json", "safe-export.json")
            dirs.write("candidate", "a.json", "safe-export.json")
            dirs.write("candidate", "b.json", "safe-export.json")
            with self.assertRaises(InputError) as caught:
                batch_diff(contract, dirs.baseline, dirs.candidate)
            self.assertIn("1-file limit", str(caught.exception))

    def test_unknown_pairing_mode_is_rejected(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "safe-export.json")
        with self.assertRaises(InputError):
            batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate, pairing="guess")


class RendererTests(unittest.TestCase):
    def _report(self, *, include_paths: bool = False) -> dict:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "missing-operational-fields.json")
        return batch_diff(load_contract(CONTRACT), dirs.baseline, dirs.candidate, include_paths=include_paths)

    def test_sarif_renders_without_values_or_host_paths(self) -> None:
        text = render_sarif(self._report())
        for canary in CANARIES:
            self.assertNotIn(canary, text)
        self.assertNotIn(str(ROOT), text)
        self.assertIn("pair-0001", text)
        self.assertIn('"version":"2.1.0"', text)

    def test_junit_renders_without_values_or_host_paths(self) -> None:
        text = render_junit(self._report())
        for canary in CANARIES:
            self.assertNotIn(canary, text)
        self.assertNotIn(str(ROOT), text)
        self.assertIn('name="pair-0001"', text)

    def test_renderers_use_the_relative_name_when_paths_are_included(self) -> None:
        sarif = render_sarif(self._report(include_paths=True))
        self.assertIn('"uri":"a.json"', sarif)
        self.assertNotIn(str(ROOT), sarif)

    def test_human_renderer_names_the_pairing_mode(self) -> None:
        report = self._report()
        text = batch_pairs.render_batch_human(report, redacted_values=CANARIES)
        self.assertIn("batch-diff", text)
        self.assertIn("pairing=filename", text)


class CliBatchDiffTests(unittest.TestCase):
    def _run(self, *extra: str) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(list(extra))
        return status, output.getvalue(), error.getvalue()

    def test_cli_passing_batch_diff(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "safe-export.json")
        status, output, error = self._run(
            "batch-diff",
            "--contract",
            str(CONTRACT),
            "--baseline-dir",
            str(dirs.baseline),
            "--candidate-dir",
            str(dirs.candidate),
            "--format",
            "human",
        )
        self.assertEqual(status, EXIT_PASS)
        self.assertEqual(error, "")
        self.assertIn("TraceCanary batch-diff: PASS", output)
        for canary in CANARIES:
            self.assertNotIn(canary, output)

    def test_cli_missing_candidate_is_exit_two(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "b.json", "safe-export.json")
        status, output, error = self._run(
            "batch-diff",
            "--contract",
            str(CONTRACT),
            "--baseline-dir",
            str(dirs.baseline),
            "--candidate-dir",
            str(dirs.candidate),
        )
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertIn("candidate", error)
        self.assertIn("missing", error)

    def test_cli_regression_is_exit_one(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "missing-operational-fields.json")
        status, output, error = self._run(
            "batch-diff",
            "--contract",
            str(CONTRACT),
            "--baseline-dir",
            str(dirs.baseline),
            "--candidate-dir",
            str(dirs.candidate),
            "--format",
            "json",
        )
        self.assertEqual(status, EXIT_REGRESSION)
        self.assertEqual(json.loads(output)["status"], "regression")

    def test_cli_sarif_and_junit_formats(self) -> None:
        dirs = _Dirs(self)
        dirs.write("baseline", "a.json", "safe-export.json")
        dirs.write("candidate", "a.json", "missing-operational-fields.json")
        for output_format in ("sarif", "junit"):
            with self.subTest(format=output_format):
                status, output, error = self._run(
                    "batch-diff",
                    "--contract",
                    str(CONTRACT),
                    "--baseline-dir",
                    str(dirs.baseline),
                    "--candidate-dir",
                    str(dirs.candidate),
                    "--format",
                    output_format,
                )
                self.assertEqual(status, EXIT_REGRESSION)
                self.assertTrue(output)
                for canary in CANARIES:
                    self.assertNotIn(canary, output)

    def test_cli_help_documents_both_pairing_modes(self) -> None:
        status, output, error = self._run("batch-diff", "--help")
        self.assertEqual(status, EXIT_PASS)
        for mode in PAIRING_MODES:
            self.assertIn(mode, output)

    def test_canary_value_in_a_file_name_fails_closed(self) -> None:
        dirs = _Dirs(self)
        name = f"{CANARIES[0]}.json"
        dirs.write("baseline", name, "safe-export.json")
        dirs.write("candidate", name, "safe-export.json")
        status, output, error = self._run(
            "batch-diff",
            "--contract",
            str(CONTRACT),
            "--baseline-dir",
            str(dirs.baseline),
            "--candidate-dir",
            str(dirs.candidate),
            "--include-paths",
        )
        self.assertEqual(status, EXIT_UNRESOLVED)
        self.assertEqual(output, "")
        self.assertEqual(error, "")


if __name__ == "__main__":
    unittest.main()
