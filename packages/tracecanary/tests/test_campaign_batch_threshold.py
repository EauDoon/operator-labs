"""Campaign summaries record, and comparisons check, the batch per-file threshold."""

import json
import tempfile
import unittest
from pathlib import Path

from support import run_cli, write_fixture
from tracecanary.campaign import compare_summaries
from tracecanary.canonical import InputError


def _project(root: Path, name: str, *extra: str) -> Path:
    sources = root / f"{name}-sources"
    contract = write_fixture(sources / "contract.json", "contract.json")
    write_fixture(sources / "exports" / "a.json", "safe-export.json")
    project = root / name
    project.mkdir()
    code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", f"fictional-{name}",
                              "--contract", contract, "--batch-dir", sources / "exports", *extra)
    assert code == 0, stderr
    return project


def _summary(root: Path, project: Path, name: str) -> Path:
    target = root / f"{name}-summary.json"
    code, _, stderr = run_cli("campaign", "run", project, "--save-summary", target)
    assert code == 0, stderr
    return target


class BatchThresholdTests(unittest.TestCase):
    def test_the_campaign_and_its_summary_record_the_batch_threshold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _project(root, "strict", "--batch-minimum-ratio", "1")
            code, stdout, _ = run_cli("campaign", "run", project)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout)["coverage"]["batch_minimum_ratio"], "1")
            summary = json.loads(_summary(root, project, "strict").read_text(encoding="utf-8"))
            self.assertEqual(summary["compatibility"]["coverage"]["batch_minimum_ratio"], "1")

    def test_no_batch_phase_records_null(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = write_fixture(root / "contract.json", "contract.json")
            project = root / "plain"
            project.mkdir()
            run_cli("project", "create", "--directory", project, "--project-id", "plain", "--contract", contract)
            code, stdout, _ = run_cli("campaign", "run", project)
            self.assertEqual(code, 0)
            self.assertIsNone(json.loads(stdout)["coverage"]["batch_minimum_ratio"])

    def test_summaries_with_different_batch_thresholds_are_unsupported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lenient = _summary(root, _project(root, "lenient", "--batch-minimum-ratio", "0"), "lenient")
            strict = _summary(root, _project(root, "strict", "--batch-minimum-ratio", "1"), "strict")
            again = _summary(root, _project(root, "again", "--batch-minimum-ratio", "1"), "again")
            code, stdout, stderr = run_cli("campaign", "compare", lenient, strict)
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn("batch per-file threshold", stderr)
            code, stdout, _ = run_cli("campaign", "compare", strict, again)
            self.assertEqual(code, 0)
            self.assertIn("pass -> pass", stdout)

    def test_a_summary_from_0_3_0_stays_comparable_without_a_batch_threshold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            without = json.loads(_summary(root, _project(root, "without"), "without").read_text(encoding="utf-8"))
            with_threshold = json.loads(
                _summary(root, _project(root, "with", "--batch-minimum-ratio", "0.5"), "with").read_text(encoding="utf-8")
            )
            old = json.loads(json.dumps(without))
            del old["compatibility"]["coverage"]["batch_minimum_ratio"]
            comparison = compare_summaries(old, without)
            self.assertEqual(comparison["campaign_status_change"], ["pass", "pass"])
            # The comparison reports the baseline's own coverage identity.
            self.assertNotIn("batch_minimum_ratio", comparison["compatibility"]["coverage"])
            self.assertEqual(compare_summaries(without, old)["campaign_status_change"], ["pass", "pass"])
            with self.assertRaisesRegex(InputError, "batch per-file threshold"):
                compare_summaries(old, with_threshold)


if __name__ == "__main__":
    unittest.main()
