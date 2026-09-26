"""Campaigns must apply saved coverage settings and record the effective gate."""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.cli import main
from tracecanary.fixture import bundle


class SavedCoverageCampaignTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = bundle()
        self.fixtures = self.root / "fixtures"
        self.fixtures.mkdir()
        for name, payload in self.files.items():
            (self.fixtures / name).write_text(json.dumps(payload), encoding="utf-8")

    def invoke(self, *args):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([str(arg) for arg in args])
        self.assert_value_free(stdout.getvalue() + stderr.getvalue())
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_value_free(self, text):
        for canary in self.files["contract.json"]["canaries"]:
            self.assertNotIn(canary["value"], text)

    def project(self, name, *options):
        directory = self.root / name
        directory.mkdir()
        code, _, stderr = self.invoke(
            "project", "create", "--directory", directory, "--project-id", name,
            "--contract", self.fixtures / "contract.json", *options,
        )
        self.assertEqual(code, 0, stderr)
        return directory

    def campaign(self, project, *options):
        code, stdout, stderr = self.invoke("campaign", "run", project, *options)
        self.assertEqual(stderr, "")
        return code, json.JSONDecoder().raw_decode(stdout)[0]

    def test_saved_threshold_gates_saved_and_additional_candidates(self):
        project = self.project(
            "all-selections", "--minimum-ratio", "0.95",
            "--input", self.fixtures / "safe-export.json",
            "--candidate", self.fixtures / "sparse-retention.json",
        )
        code, report = self.campaign(project, "--candidate", self.fixtures / "sparse-retention.json")
        self.assertEqual(code, 1)
        self.assertEqual(report["coverage"]["minimum_ratio"], "0.95")
        candidates = report["phases"]["candidates"]
        self.assertEqual(candidates["mode"], "coverage-gate")
        self.assertEqual(candidates["count"], 3)
        self.assertEqual([item["status"] for item in candidates["items"]], ["regression", "pass", "regression"])
        self.assertEqual(candidates["finding_counts"], {"TC011": 2})

    def test_effective_threshold_is_saved_and_comparisons_reject_different_gates(self):
        project = self.project("summary", "--minimum-ratio", "0.95",
                               "--candidate", self.fixtures / "sparse-retention.json")
        reports = []
        summaries = []
        for label, options, expected_code, threshold in [
            ("inherited", [], 1, "0.95"),
            ("explicit", ["--minimum-ratio", "0.95"], 1, "0.95"),
            ("override", ["--minimum-ratio", "0.5"], 0, "0.5"),
        ]:
            path = self.root / (label + ".json")
            code, report = self.campaign(project, *options, "--save-summary", path)
            self.assertEqual(code, expected_code)
            summary_text = path.read_text(encoding="utf-8")
            self.assert_value_free(summary_text)
            summary = json.loads(summary_text)
            self.assertEqual(summary["compatibility"]["coverage"]["minimum_ratio"], threshold)
            self.assertEqual(summary["campaign_status"], report["status"])
            reports.append(report)
            summaries.append(path)
        self.assertEqual(reports[0], reports[1])
        self.assertEqual(summaries[0].read_bytes(), summaries[1].read_bytes())
        self.assertEqual(self.invoke("campaign", "compare", *summaries[:2])[0], 0)
        code, _, stderr = self.invoke("campaign", "compare", summaries[0], summaries[2])
        self.assertEqual(code, 2)
        self.assertIn("different coverage thresholds", stderr)

    def test_explicit_boundary_overrides_win_without_mutating_saved_settings(self):
        project = self.project("override", "--minimum-ratio", "0.95",
                               "--candidate", self.fixtures / "sparse-retention.json")
        manifest = project / "tracecanary.project.json"
        original = manifest.read_bytes()
        for threshold, expected in [("0", 0), ("0.5", 0), ("1", 1)]:
            with self.subTest(threshold=threshold):
                code, report = self.campaign(project, "--minimum-ratio", threshold)
                self.assertEqual(code, expected)
                self.assertEqual(report["coverage"]["minimum_ratio"], threshold)
        self.assertEqual(manifest.read_bytes(), original)
        self.assertEqual(self.campaign(project)[0], 1)

    def test_invalid_explicit_threshold_does_not_fall_back_to_saved_value(self):
        project = self.project("invalid-override", "--minimum-ratio", "0",
                               "--candidate", self.fixtures / "safe-export.json")
        for threshold in ["", "1.1"]:
            with self.subTest(threshold=threshold):
                code, report = self.campaign(project, "--minimum-ratio", threshold)
                self.assertEqual(code, 2)
                self.assertEqual(report["phases"]["candidates"]["status"], "unresolved")
                self.assertEqual(report["coverage"]["minimum_ratio"], threshold)

    def test_absent_threshold_preserves_standalone_and_baseline_modes(self):
        for name, baseline, mode in [
            ("standalone", [], "standalone-check"),
            ("baseline", ["--baseline", self.fixtures / "safe-export.json"], "baseline-diff"),
        ]:
            project = self.project(name, "--candidate", self.fixtures / "safe-export.json", *baseline)
            code, report = self.campaign(project)
            self.assertEqual(code, 0)
            self.assertIsNone(report["coverage"]["minimum_ratio"])
            self.assertEqual(report["phases"]["candidates"]["mode"], mode)

    def test_saved_named_and_batch_thresholds_remain_separate(self):
        batch = self.root / "batch"
        batch.mkdir()
        (batch / "sparse.json").write_bytes((self.fixtures / "sparse-retention.json").read_bytes())
        for name, named_ratio, batch_ratio, named_status, batch_status in [
            ("strict-named", "0.95", "0.5", "regression", "pass"),
            ("strict-batch", "0", "0.95", "pass", "regression"),
        ]:
            project = self.project(name, "--minimum-ratio", named_ratio,
                                   "--candidate", self.fixtures / "sparse-retention.json",
                                   "--batch-dir", batch, "--batch-minimum-ratio", batch_ratio)
            code, report = self.campaign(project)
            self.assertEqual(code, 1)
            self.assertEqual(report["phases"]["candidates"]["status"], named_status)
            self.assertEqual(report["phases"]["batch"]["status"], batch_status)
            # Preserve the existing explicit override of both phases.
            code, report = self.campaign(project, "--minimum-ratio", "0")
            self.assertEqual(code, 0)
            self.assertEqual(report["phases"]["batch"]["status"], "pass")

    def test_inherited_gate_keeps_privacy_and_unresolved_precedence(self):
        for name, candidate, baseline, expected in [
            ("leak", "leaked-prompt.json", "safe-export.json", 1),
            ("invalid", "invalid-export.json", "safe-export.json", 2),
            ("bad-baseline", "safe-export.json", "leaked-prompt.json", 2),
        ]:
            project = self.project(name, "--minimum-ratio", "0.95",
                                   "--candidate", self.fixtures / candidate,
                                   "--baseline", self.fixtures / baseline)
            code, report = self.campaign(project)
            self.assertEqual(code, expected)
            self.assertEqual(report["coverage"]["minimum_ratio"], "0.95")
            if name == "leak":
                self.assertEqual(report["phases"]["candidates"]["finding_counts"], {"TC001": 1, "TC002": 1})
            if name == "bad-baseline":
                self.assertEqual(report["phases"]["baseline"]["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
