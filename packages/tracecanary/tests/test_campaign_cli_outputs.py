"""campaign run writes reports and evidence from the CLI: --format, --output, --save-evidence."""

import json
import tempfile
import unittest
from pathlib import Path

from support import run_cli, snapshot, write_fixture, write_json
import tracecanary
from tracecanary.campaign import campaign_evidence, render_campaign_human
from tracecanary.fixture import bundle
from tracecanary.gui_controller import GuiResult, TraceCanaryController
from tracecanary.report import render_json


def _project(root: Path, contract: dict | None = None) -> Path:
    project = root / "project"
    inputs = project / "inputs"
    if contract is None:
        write_fixture(inputs / "contract.json", "contract.json")
    else:
        write_json(inputs / "contract.json", contract)
    write_fixture(inputs / "safe.json", "safe-export.json")
    write_fixture(inputs / "candidate.json", "missing-operational-fields.json")
    write_fixture(inputs / "exports" / "a.json", "safe-export.json")
    code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-outputs",
                              "--contract", inputs / "contract.json", "--baseline", inputs / "safe.json",
                              "--candidate", inputs / "candidate.json", "--batch-dir", inputs / "exports")
    assert code == 0, stderr
    return project


def _library_human(project: Path) -> str:
    """The human rendering of the same campaign, built straight from the library."""
    from tracecanary.batching import _load_trace
    from tracecanary.campaign import run_campaign
    from tracecanary.contract import load_contract

    inputs = project / "inputs"
    contract = load_contract(inputs / "contract.json")
    campaign = run_campaign(
        contract,
        baseline_payload=_load_trace(inputs / "safe.json", contract),
        candidates=[("inputs/candidate.json", inputs / "candidate.json")],
        batch=inputs / "exports",
    )
    return render_campaign_human(campaign)


def _contract_with_canary(value: str) -> dict:
    contract = json.loads(json.dumps(bundle()["contract.json"]))
    contract["canaries"].append({"label": "extra-wording-canary", "category": "prompt", "value": value})
    return contract


class CampaignOutputTests(unittest.TestCase):
    def test_default_output_is_the_campaign_json_with_one_additive_coverage_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = _project(Path(temporary))
            code, stdout, stderr = run_cli("campaign", "run", project)
            self.assertEqual(code, 1, stderr)
            campaign = json.loads(stdout)
            self.assertEqual(stdout, render_json(campaign))
            self.assertEqual(set(campaign), {"campaign_version", "contract_version", "status", "phases", "summary",
                                             "required_fields", "coverage"})
            self.assertEqual(set(campaign["coverage"]), {"minimum_ratio", "population_scope", "population_minimum",
                                                         "batch_minimum_ratio"})

    def test_human_format_uses_the_shared_renderer(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = _project(Path(temporary))
            code, stdout, stderr = run_cli("campaign", "run", project, "--format", "human")
            self.assertEqual(code, 1, stderr)
            self.assertEqual(stdout, _library_human(project))
            self.assertTrue(stdout.startswith("TraceCanary campaign: REGRESSION"))

    def test_output_writes_the_report_and_keeps_stdout_for_confirmations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _project(root)
            _, json_text, _ = run_cli("campaign", "run", project)
            report = root / "campaign.json"
            summary = root / "summary.json"
            evidence = root / "evidence.json"
            code, stdout, stderr = run_cli("campaign", "run", project, "--output", report,
                                           "--save-summary", summary, "--save-evidence", evidence)
            self.assertEqual(code, 1, stderr)
            self.assertEqual(stdout, f"Value-free campaign summary saved to {summary}\n"
                                     f"Value-free evidence saved to {evidence}\n")
            self.assertEqual(report.read_text(encoding="utf-8"), json_text)
            human = root / "campaign.txt"
            self.assertEqual(run_cli("campaign", "run", project, "--format", "human", "--output", human)[1], "")
            self.assertEqual(human.read_text(encoding="utf-8"), _library_human(project))
            document = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(document["evidence_version"], "tracecanary.evidence/v1")
            self.assertEqual(document["summary"], json.loads(summary.read_text(encoding="utf-8")))

    def test_refused_destinations_print_and_write_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _project(root)
            control = write_fixture(root / "control.json", "safe-export.json")
            inputs = project / "inputs"
            batch_dir = root / "batch"
            write_fixture(batch_dir / "b.json", "safe-export.json")
            cases = (
                ("output inside the project", ("--output", project / "report.json")),
                ("output is the contract", ("--output", inputs / "contract.json")),
                ("output is the candidate", ("--output", inputs / "candidate.json")),
                ("output is the control", ("--control", control, "--output", control)),
                ("output inside the batch", ("--input-dir", batch_dir, "--output", batch_dir / "report.json")),
                ("output equals summary", ("--output", root / "same.json", "--save-summary", root / "same.json")),
                ("output equals evidence", ("--output", root / "same.json", "--save-evidence", root / "same.json")),
                ("summary equals evidence", ("--save-summary", root / "same.json", "--save-evidence", root / "same.json")),
                ("summary is the contract", ("--save-summary", inputs / "contract.json")),
                ("evidence inside the project", ("--save-evidence", inputs / "evidence.json")),
            )
            for label, extra in cases:
                with self.subTest(case=label):
                    before_project = snapshot(project)
                    before_root = sorted(path.name for path in root.iterdir())
                    control_bytes = control.read_bytes()
                    code, stdout, stderr = run_cli("campaign", "run", project, *extra)
                    self.assertEqual(code, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn("TraceCanary: UNRESOLVED:", stderr)
                    self.assertEqual(snapshot(project), before_project)
                    self.assertEqual(sorted(path.name for path in root.iterdir()), before_root)
                    self.assertEqual(control.read_bytes(), control_bytes)
                    self.assertFalse((batch_dir / "report.json").exists())

    def test_evidence_matches_the_desktop_document_and_its_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _project(root)
            evidence = root / "evidence.json"
            _, stdout, _ = run_cli("campaign", "run", project, "--save-evidence", evidence)
            json_text, confirmation, _ = stdout.rsplit("\n", 2)
            json_text += "\n"
            self.assertEqual(confirmation, f"Value-free evidence saved to {evidence}")
            campaign = json.loads(json_text)
            desktop_path = root / "desktop.json"
            result = GuiResult("regression", 1, render_campaign_human(campaign), render_json(campaign),
                               inputs=(project / "inputs" / "contract.json",), mode="campaign")
            saved = TraceCanaryController().save_campaign_evidence(desktop_path, result)
            self.assertEqual(saved.exit_code, 0, saved.human)
            self.assertEqual(evidence.read_bytes(), desktop_path.read_bytes())
            # The 0.3.0 desktop document, field for field.
            golden = {
                "evidence_version": "tracecanary.evidence/v1",
                "tool": {"name": "tracecanary", "version": tracecanary.__version__},
                "summary": json.loads(evidence.read_text(encoding="utf-8"))["summary"],
                "meaning": (
                    "Deterministic value-free evidence for a synthetic regression campaign. "
                    "Canary values, contracts, and trace inputs are not bundled; hashes of "
                    "protected values are not treated as anonymization. Detection is bounded "
                    "by the declared contract and does not claim absence of all sensitive data."
                ),
            }
            self.assertEqual(desktop_path.read_text(encoding="utf-8"), render_json(golden))
            self.assertEqual(campaign_evidence(campaign), golden)

    def test_a_canary_in_any_requested_wording_withholds_every_output(self):
        cases = (
            # Only the human rendering carries this sentence.
            ("Canary values never appear", ("--format", "human")),
            # Only the evidence document carries this word.
            ("anonymization", ("--save-evidence", "EVIDENCE")),
            # The summary and the evidence carry the summary version; the campaign JSON does not.
            ("campaign-summary", ("--save-summary", "SUMMARY")),
        )
        for value, extra in cases:
            with self.subTest(canary=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                project = _project(root, _contract_with_canary(value))
                arguments = [str(root / "out.json") if item in ("EVIDENCE", "SUMMARY") else item for item in extra]
                report = root / "report.json"
                code, stdout, stderr = run_cli("campaign", "run", project, *arguments, "--output", report)
                self.assertEqual(code, 2)
                self.assertEqual((stdout, stderr), ("", ""))
                self.assertFalse(report.exists())
                self.assertFalse((root / "out.json").exists())
                code, stdout, _ = run_cli("campaign", "run", project, *arguments)
                self.assertEqual((code, stdout), (2, ""))


if __name__ == "__main__":
    unittest.main()
