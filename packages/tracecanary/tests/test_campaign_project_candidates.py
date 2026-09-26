"""Saved project candidates must participate in CLI campaigns and summaries."""

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


class SavedCandidateCampaignTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixtures = self.root / "fixtures"
        self.fixtures.mkdir()
        self.files = bundle()
        for name, payload in self.files.items():
            (self.fixtures / name).write_text(json.dumps(payload), encoding="utf-8")

    def invoke(self, *args):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([str(arg) for arg in args])
        for canary in self.files["contract.json"]["canaries"]:
            self.assertNotIn(canary["value"], stdout.getvalue() + stderr.getvalue())
        return code, stdout.getvalue(), stderr.getvalue()

    def project(self, name, candidate, *, baseline="safe-export.json", input_name=None):
        project = self.root / name
        project.mkdir()
        args = ["project", "create", "--directory", project, "--project-id", name,
                "--contract", self.fixtures / "contract.json",
                "--baseline", self.fixtures / baseline,
                "--candidate", self.fixtures / candidate]
        if input_name is not None:
            args.extend(["--input", self.fixtures / input_name])
        self.assertEqual(self.invoke(*args)[0], 0)
        self.assertEqual(self.invoke("project", "validate", project)[0], 0)
        return project

    def test_saved_candidate_controls_status_and_saved_summary(self):
        cases = (
            ("safe-export.json", 0, "pass", {}),
            ("leaked-prompt.json", 1, "regression", {"TC001": 1, "TC002": 1}),
            ("missing-operational-fields.json", 1, "regression", {"TC004": 1, "TC005": 1}),
            ("invalid-export.json", 2, "unresolved", {}),
        )
        summaries = []
        for index, (candidate, expected_code, status, findings) in enumerate(cases):
            with self.subTest(candidate=candidate):
                project = self.project(f"case-{index}", candidate)
                summary_path = self.root / f"summary-{index}.json"
                code, stdout, stderr = self.invoke(
                    "campaign", "run", project,
                    "--control", self.fixtures / "positive-control.json",
                    "--save-summary", summary_path,
                )
                self.assertEqual(code, expected_code)
                self.assertEqual(stderr, "")
                report = json.JSONDecoder().raw_decode(stdout)[0]
                self.assertEqual(report["status"], status)
                self.assertEqual(report["phases"]["baseline"]["status"], "pass")
                self.assertEqual(report["phases"]["control"]["status"], "pass")
                candidates = report["phases"]["candidates"]
                self.assertEqual(candidates["mode"], "baseline-diff")
                self.assertEqual(candidates["count"], 1)
                self.assertEqual(candidates["items"][0]["status"], status)
                self.assertEqual(candidates["finding_counts"], findings)
                summary_text = summary_path.read_text(encoding="utf-8")
                for canary in self.files["contract.json"]["canaries"]:
                    self.assertNotIn(canary["value"], summary_text)
                summary = json.loads(summary_text)
                self.assertEqual(summary["candidate_count"], 1)
                self.assertEqual(summary["campaign_status"], status)
                self.assertEqual(summary["phases"]["candidates"]["finding_counts"], findings)
                summaries.append(summary_path)

        code, stdout, stderr = self.invoke("campaign", "compare", *summaries[:2], "--format", "json")
        self.assertEqual(code, 0)  # Comparison success, not a privacy pass.
        self.assertEqual(stderr, "")
        comparison = json.loads(stdout)
        self.assertEqual(comparison["campaign_status_change"], ["pass", "regression"])
        self.assertEqual(comparison["phases"]["candidates"]["new_findings"], {"TC001": 1, "TC002": 1})

    def test_additional_candidate_and_saved_input_do_not_hide_saved_candidate(self):
        project = self.project("mixed", "leaked-prompt.json", input_name="safe-export.json")
        code, stdout, _ = self.invoke("campaign", "run", project,
                                     "--candidate", self.fixtures / "missing-operational-fields.json")
        self.assertEqual(code, 1)
        candidates = json.loads(stdout)["phases"]["candidates"]
        self.assertEqual(candidates["count"], 3)
        by_name = {Path(item["label"]).name: item for item in candidates["items"]}
        self.assertEqual(by_name["safe-export.json"]["status"], "pass")
        self.assertEqual(by_name["leaked-prompt.json"]["finding_counts"], {"TC001": 1, "TC002": 1})
        self.assertEqual(by_name["missing-operational-fields.json"]["finding_counts"], {"TC004": 1, "TC005": 1})

    def test_failing_baseline_keeps_saved_candidate_campaign_unresolved(self):
        project = self.project("bad-baseline", "safe-export.json", baseline="leaked-prompt.json")
        code, stdout, _ = self.invoke("campaign", "run", project)
        self.assertEqual(code, 2)
        report = json.loads(stdout)
        self.assertEqual(report["phases"]["baseline"]["status"], "unresolved")
        self.assertEqual(report["phases"]["candidates"]["mode"], "standalone-check")
        self.assertEqual(report["phases"]["candidates"]["count"], 1)
        self.assertEqual(report["phases"]["candidates"]["items"][0]["status"], "pass")

    def test_changed_saved_candidate_is_rejected_before_summary_export(self):
        project = self.project("changed", "leaked-prompt.json")
        (project / "inputs" / "leaked-prompt.json").write_text(
            json.dumps(self.files["safe-export.json"]), encoding="utf-8")
        summary_path = self.root / "changed-summary.json"
        code, stdout, stderr = self.invoke("campaign", "run", project, "--save-summary", summary_path)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("UNRESOLVED", stderr)
        self.assertFalse(summary_path.exists())


if __name__ == "__main__":
    unittest.main()
