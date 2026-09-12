import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.campaign import (
    campaign_summary,
    compare_summaries,
    render_campaign_human,
    run_campaign,
)
from tracecanary.fixture import bundle
from tracecanary.gui_controller import TraceCanaryController


class CampaignEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.files = bundle()
        cls.contract = parse_contract = None
        from tracecanary.contract import parse_contract

        cls.contract = parse_contract(cls.files["contract.json"])
        for name, data in cls.files.items():
            (cls.root / name).write_text(json.dumps(data), encoding="utf-8", newline="\n")

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def test_campaign_phases_keep_separate_meanings(self):
        campaign = run_campaign(
            self.contract,
            control_payload=self.files["positive-control.json"],
            baseline_payload=self.files["safe-export.json"],
            candidates=[("missing.json", self.root / "missing-operational-fields.json"),
                        ("leak.json", self.root / "leaked-prompt.json")],
        )
        self.assertEqual(campaign["phases"]["control"]["status"], "pass")
        self.assertIn("not a privacy pass", campaign["phases"]["control"]["meaning"])
        self.assertEqual(campaign["phases"]["baseline"]["status"], "pass")
        self.assertEqual(campaign["phases"]["candidates"]["status"], "regression")
        items = campaign["phases"]["candidates"]["items"]
        self.assertEqual([item["status"] for item in items], ["regression", "regression"])
        codes = {item["label"]: sorted(item["finding_counts"]) for item in items}
        self.assertEqual(codes["leak.json"], ["TC001", "TC002"])
        self.assertTrue(all(code.startswith("TC") for code in campaign["summary"]["finding_counts"]))
        self.assertNotIn("TCANARY", json.dumps(campaign))

    def test_failing_baseline_is_never_used(self):
        campaign = run_campaign(
            self.contract,
            baseline_payload=self.files["leaked-prompt.json"],
            candidates=[("safe.json", self.root / "safe-export.json")],
        )
        self.assertEqual(campaign["phases"]["baseline"]["status"], "unresolved")
        self.assertIn("never used", campaign["phases"]["baseline"]["meaning"])
        items = campaign["phases"]["candidates"]["items"]
        self.assertEqual(items[0]["status"], "pass")
        self.assertEqual(campaign["phases"]["candidates"]["mode"], "standalone-check")
        self.assertEqual(campaign["status"], "unresolved")

    def test_unresolved_precedence_across_mixed_candidates(self):
        campaign = run_campaign(
            self.contract,
            candidates=[("safe.json", self.root / "safe-export.json"),
                        ("invalid.json", self.root / "invalid-export.json"),
                        ("leak.json", self.root / "leaked-prompt.json")],
        )
        statuses = {item["status"] for item in campaign["phases"]["candidates"]["items"]}
        self.assertEqual(statuses, {"pass", "regression", "unresolved"})
        self.assertEqual(campaign["status"], "unresolved")

    def test_batch_phase_uses_the_bounded_engine(self):
        campaign = run_campaign(
            self.contract,
            batch=self.root, batch_include_paths=True, batch_minimum_ratio="0.95",
        )
        batch_phase = campaign["phases"]["batch"]
        self.assertEqual(batch_phase["status"], "unresolved")
        self.assertIn("regression", batch_phase["statuses"])
        self.assertIn("coverage_summary", batch_phase)
        self.assertNotIn("TCANARY", json.dumps(campaign))

    def test_human_render_is_value_free_and_labeled(self):
        campaign = run_campaign(self.contract, control_payload=self.files["positive-control.json"])
        human = render_campaign_human(campaign)
        self.assertIn("not a privacy pass", human)
        self.assertNotIn("TCANARY", human)


class CampaignSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.files = bundle()
        from tracecanary.contract import parse_contract

        cls.contract = parse_contract(cls.files["contract.json"])
        for name, data in cls.files.items():
            (cls.root / name).write_text(json.dumps(data), encoding="utf-8", newline="\n")

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def test_summary_comparison_distinguishes_persistent_resolved_and_new(self):
        before = run_campaign(self.contract,
                              control_payload=self.files["positive-control.json"],
                              baseline_payload=self.files["safe-export.json"],
                              candidates=[("leak.json", self.root / "leaked-prompt.json"),
                                          ("missing.json", self.root / "missing-operational-fields.json")])
        after = run_campaign(self.contract,
                             control_payload=self.files["positive-control.json"],
                             baseline_payload=self.files["safe-export.json"],
                             candidates=[("missing.json", self.root / "missing-operational-fields.json")])
        comparison = compare_summaries(campaign_summary(before), campaign_summary(after))
        candidates = comparison["phases"]["candidates"]
        self.assertEqual(sorted(candidates["resolved_findings"]), ["TC001", "TC002"])
        self.assertEqual(sorted(candidates["persistent_findings"]), ["TC004", "TC005"])
        self.assertEqual(candidates["new_findings"], {})
        self.assertNotIn("TCANARY", json.dumps(comparison))

    def test_incompatible_summaries_are_unsupported(self):
        before = campaign_summary(run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")]))
        after = campaign_summary(run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")]))
        after["contract_version"] = "tracecanary/v999"
        with self.assertRaisesRegex(Exception, "same contract version"):
            compare_summaries(before, after)
        with self.assertRaisesRegex(Exception, "requires two saved"):
            compare_summaries({"summary_version": "wrong/v1"}, after)


class ControllerCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.files = bundle()
        for name, data in cls.files.items():
            (cls.root / name).write_text(json.dumps(data), encoding="utf-8", newline="\n")
        cls.controller = TraceCanaryController()

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def test_controller_campaign_agrees_with_cli(self):
        from tracecanary.cli import main

        result = self.controller.run_campaign_selections(
            contract_path=str(self.root / "contract.json"),
            input_path=str(self.root / "leaked-prompt.json"),
            baseline_path=str(self.root / "safe-export.json"),
            batch_path=None,
            control_path=str(self.root / "positive-control.json"),
            minimum_ratio=None,
            population_scope=None,
            population_minimum=None,
        )
        self.assertEqual(result.status, "regression")
        self.assertIn("not a privacy pass", result.human)
        # CLI agreement through the same selections via a minimal project
        project_root = self.root / "campaign-project"
        project_root.mkdir(exist_ok=True)
        for name in ("contract.json", "safe-export.json", "leaked-prompt.json", "positive-control.json"):
            (project_root / name).write_text((self.root / name).read_text(encoding="utf-8"), encoding="utf-8")
        summary_path = self.root / "cli-summary.json"
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = main(["project", "create", "--directory", str(project_root), "--project-id", "fictional-campaign-cli",
                         "--contract", str(project_root / "contract.json"), "--input", str(project_root / "leaked-prompt.json"),
                         "--baseline", str(project_root / "safe-export.json")])
            self.assertEqual(code, 0)
            code = main(["campaign", "run", str(project_root), "--control", str(project_root / "positive-control.json"),
                         "--save-summary", str(self.root / "cli-summary.json")])
        self.assertEqual(code, 1)
        saved = json.loads((self.root / "cli-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["campaign_status"], "regression")
        self.assertNotIn("TCANARY", (self.root / "cli-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["phases"]["candidates"]["finding_counts"], {"TC001": 1, "TC002": 1})

    def test_summary_save_refuses_inputs_and_project_directories(self):
        result = self.controller.run_campaign_selections(
            contract_path=str(self.root / "contract.json"),
            input_path=str(self.root / "safe-export.json"),
            baseline_path=None, batch_path=None, control_path=None,
            minimum_ratio=None, population_scope=None, population_minimum=None,
        )
        self.assertEqual(result.status, "pass")
        rejection = self.controller.save_campaign_summary(self.root / "contract.json", result)
        self.assertEqual(rejection.status, "unresolved")
        self.assertIn("must not replace", rejection.human)
        destination = self.root / "saved-summary.json"
        saved = self.controller.save_campaign_summary(destination, result)
        self.assertEqual(saved.status, "pass")
        saved_summary = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(saved_summary["summary_version"], "tracecanary.campaign-summary/v1")

    def test_summary_comparison_from_the_controller(self):
        first = self.controller.run_campaign_selections(
            contract_path=str(self.root / "contract.json"), input_path=str(self.root / "leaked-prompt.json"),
            baseline_path=None, batch_path=None, control_path=None,
            minimum_ratio=None, population_scope=None, population_minimum=None)
        second = self.controller.run_campaign_selections(
            contract_path=str(self.root / "contract.json"), input_path=str(self.root / "safe-export.json"),
            baseline_path=None, batch_path=None, control_path=None,
            minimum_ratio=None, population_scope=None, population_minimum=None)
        first_summary = self.root / "first.json"
        second_summary = self.root / "second.json"
        self.assertEqual(self.controller.save_campaign_summary(first_summary, first).status, "pass")
        self.assertEqual(self.controller.save_campaign_summary(second_summary, second).status, "pass")
        comparison = self.controller.compare_saved_summaries(first_summary, second_summary)
        candidates = json.loads(comparison.json)["phases"]["candidates"]
        self.assertEqual(sorted(candidates["resolved_findings"]), ["TC001", "TC002"])
        self.assertIn("no entity identity", comparison.human)


if __name__ == "__main__":
    unittest.main()
