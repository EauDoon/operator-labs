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

    def test_population_gate_does_not_abort_when_the_first_candidate_cannot_be_read(self):
        campaign = run_campaign(
            self.contract,
            candidates=[
                ("missing.json", self.root / "does-not-exist.json"),
                ("leak.json", self.root / "leaked-prompt.json"),
            ],
            population_scope="span",
            population_minimum=1,
        )
        items = campaign["phases"]["candidates"]["items"]
        self.assertEqual([item["status"] for item in items], ["unresolved", "regression"])
        self.assertEqual(campaign["phases"]["population_gate"]["status"], "unresolved")
        self.assertEqual(campaign["status"], "unresolved")
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

    def test_malformed_summaries_are_unresolved_not_a_crash(self):
        from tracecanary.canonical import InputError
        from tracecanary.cli import main

        good = campaign_summary(run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")]))
        damaged = {
            "required field": lambda summary: summary["compatibility"].update(required_fields=[1]),
            "phase": lambda summary: summary["phases"].update(candidates="regression"),
            "phases": lambda summary: summary.update(phases=["candidates"]),
            "finding count": lambda summary: summary["phases"]["candidates"].update(finding_counts={"TC001": "1"}),
            "compatibility": lambda summary: summary.update(compatibility=["required_fields"]),
            "coverage": lambda summary: summary["compatibility"].update(coverage=["minimum_ratio"]),
            "campaign status": lambda summary: summary.update(campaign_status=["regression"]),
        }
        good_path = self.root / "good-summary.json"
        good_path.write_text(json.dumps(good), encoding="utf-8")
        for name, damage in damaged.items():
            with self.subTest(damage=name):
                bad = json.loads(json.dumps(good))
                damage(bad)
                with self.assertRaisesRegex(InputError, "well-formed saved summaries"):
                    compare_summaries(good, bad)
                with self.assertRaisesRegex(InputError, "well-formed saved summaries"):
                    compare_summaries(bad, good)
                bad_path = self.root / "bad-summary.json"
                bad_path.write_text(json.dumps(bad), encoding="utf-8")
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main(["campaign", "compare", str(good_path), str(bad_path)])
                self.assertEqual(code, 2)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("UNRESOLVED", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                gui = TraceCanaryController().compare_saved_summaries(good_path, bad_path)
                self.assertEqual(gui.status, "unresolved")

    def test_comparison_records_and_checks_thresholds_and_population(self):
        first = campaign_summary(run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")],
                                              minimum_ratio="0.95", population_scope="span", population_minimum=1))
        matching = campaign_summary(run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")],
                                                 minimum_ratio="0.95", population_scope="span", population_minimum=1))
        comparison = compare_summaries(first, matching)
        self.assertIn("required_fields", comparison["compatibility"] if "compatibility" in comparison else first["compatibility"])
        changed_threshold = campaign_summary(run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")],
                                                          minimum_ratio="0.5", population_scope="span", population_minimum=1))
        with self.assertRaisesRegex(Exception, "different coverage thresholds"):
            compare_summaries(first, changed_threshold)
        changed_population = campaign_summary(run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")],
                                                           minimum_ratio="0.95", population_scope="link", population_minimum=1))
        with self.assertRaisesRegex(Exception, "different coverage thresholds"):
            compare_summaries(first, changed_population)

    def test_summary_records_required_field_identity_value_free(self):
        summary = campaign_summary(run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")]))
        identity = summary["compatibility"]["required_fields"]
        self.assertEqual([field["scope"] for field in identity], ["resource", "span", "event"])
        self.assertEqual([field["key"] for field in identity], ["service.name", "gen_ai.operation.name", "telemetry.event.class"])
        self.assertNotIn("TCANARY", json.dumps(summary))


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
                         "--save-summary", str(summary_path)])
        self.assertEqual(code, 1)
        saved = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["campaign_status"], "regression")
        self.assertNotIn("TCANARY", summary_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["phases"]["candidates"]["finding_counts"], {"TC001": 1, "TC002": 1})

    def test_controller_campaign_checks_the_selected_candidate(self):
        # The desktop Candidate selector, as Open Project fills it from a
        # project saved with only --baseline and --candidate.
        leaking = self.controller.run_campaign_selections(
            contract_path=str(self.root / "contract.json"),
            input_path=None,
            baseline_path=str(self.root / "safe-export.json"),
            candidate_path=str(self.root / "leaked-prompt.json"),
            batch_path=None,
        )
        self.assertEqual((leaking.status, leaking.exit_code), ("regression", 1))
        candidates = json.loads(leaking.json)["phases"]["candidates"]
        self.assertEqual([item["label"] for item in candidates["items"]], ["leaked-prompt.json"])
        self.assertEqual(candidates["finding_counts"], {"TC001": 1, "TC002": 1})
        self.assertIn(self.root / "leaked-prompt.json", leaking.inputs)
        both = self.controller.run_campaign_selections(
            contract_path=str(self.root / "contract.json"),
            input_path=str(self.root / "safe-export.json"),
            baseline_path=None,
            candidate_path=str(self.root / "leaked-prompt.json"),
            batch_path=None,
        )
        self.assertEqual(both.status, "regression")
        self.assertEqual(json.loads(both.json)["phases"]["candidates"]["count"], 2)

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


class CampaignPopulationGateTests(unittest.TestCase):
    """The population gate covers every input once and never re-counts privacy findings."""

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

    def test_privacy_findings_are_counted_once_with_a_gate(self):
        plain = run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")])
        gated = run_campaign(self.contract, candidates=[("leak.json", self.root / "leaked-prompt.json")],
                             population_scope="span", population_minimum=1)
        self.assertEqual(plain["summary"]["finding_counts"], {"TC001": 1, "TC002": 1})
        self.assertEqual(gated["summary"]["finding_counts"], {"TC001": 1, "TC002": 1})
        gate = gated["phases"]["population_gate"]
        # A leaking candidate with an adequate population passes the population requirement.
        self.assertEqual(gate["status"], "pass")
        self.assertEqual(gate["finding_counts"], {})
        self.assertEqual(gate["violations"], [])
        self.assertEqual(gated["status"], "regression")
        summary = campaign_summary(gated)
        self.assertEqual(summary["phases"]["population_gate"]["finding_counts"], {})
        self.assertEqual(summary["phases"]["candidates"]["finding_counts"], {"TC001": 1, "TC002": 1})

    def test_a_small_population_yields_tc013_exactly_once(self):
        campaign = run_campaign(self.contract, candidates=[("safe.json", self.root / "safe-export.json")],
                                population_scope="span", population_minimum=2)
        gate = campaign["phases"]["population_gate"]
        self.assertEqual(gate["status"], "regression")
        self.assertEqual(gate["finding_counts"], {"TC013": 1})
        self.assertEqual([item["code"] for item in gate["violations"]], ["TC013"])
        self.assertEqual(campaign["summary"]["finding_counts"], {"TC013": 1})
        self.assertEqual(campaign["phases"]["candidates"]["status"], "pass")
        self.assertEqual(campaign["status"], "regression")

    def test_every_named_candidate_is_gated(self):
        campaign = run_campaign(
            self.contract,
            candidates=[("two-spans.json", self.root / "sparse-retention.json"),
                        ("one-span.json", self.root / "safe-export.json")],
            population_scope="span",
            population_minimum=2,
        )
        items = campaign["phases"]["population_gate"]["items"]
        self.assertEqual([(item["id"], item["label"], item["status"]) for item in items],
                         [("candidate-0001", "two-spans.json", "pass"), ("candidate-0002", "one-span.json", "regression")])
        self.assertEqual(campaign["phases"]["population_gate"]["status"], "regression")

    def test_batch_files_are_gated_in_the_batch_phase(self):
        with tempfile.TemporaryDirectory() as temporary:
            batch = Path(temporary)
            (batch / "one-span.json").write_text(json.dumps(self.files["safe-export.json"]), encoding="utf-8")
            ungated = run_campaign(self.contract, batch=batch)
            gated = run_campaign(self.contract, batch=batch, population_scope="span", population_minimum=2)
        self.assertEqual(ungated["phases"]["batch"]["statuses"], {"pass": 1})
        self.assertEqual(gated["phases"]["batch"]["statuses"], {"regression": 1})
        self.assertNotIn("population_gate", gated["phases"])

    def test_an_invalid_gate_is_refused_before_any_input_is_read(self):
        from tracecanary.canonical import InputError

        for scope, minimum in (("span", 0), ("galaxy", 1), ("span", 1_000_001)):
            with self.subTest(scope=scope, minimum=minimum), self.assertRaises(InputError):
                run_campaign(self.contract, candidates=[("missing.json", self.root / "does-not-exist.json")],
                             population_scope=scope, population_minimum=minimum)

    def test_controller_campaign_honours_the_batch_selectors(self):
        with tempfile.TemporaryDirectory() as temporary:
            batch = Path(temporary) / "batch"
            nested = batch / "nested"
            nested.mkdir(parents=True)
            (nested / "safe.json").write_text(json.dumps(self.files["safe-export.json"]), encoding="utf-8")
            controller = TraceCanaryController()
            flat = controller.run_campaign_selections(
                contract_path=self.root / "contract.json", input_path=None, baseline_path=None, batch_path=batch)
            recursive = controller.run_campaign_selections(
                contract_path=self.root / "contract.json", input_path=None, baseline_path=None, batch_path=batch,
                batch_recursive=True)
        # Without Recursive the folder holds no top-level JSON file.
        self.assertEqual(flat.status, "unresolved")
        self.assertEqual(recursive.status, "pass")
        self.assertEqual(json.loads(recursive.json)["phases"]["batch"]["item_count"], 1)

    def test_controller_rejects_a_non_numeric_population_minimum_with_guidance(self):
        controller = TraceCanaryController()
        self.assertEqual(controller.campaign_population_minimum(""), (None, None))
        self.assertEqual(controller.campaign_population_minimum(" 3 "), (3, None))
        minimum, guidance = controller.campaign_population_minimum("two")
        self.assertIsNone(minimum)
        self.assertEqual(guidance.status, "unresolved")
        self.assertEqual(json.loads(guidance.json)["violations"][0]["code"], "GUI007")


if __name__ == "__main__":
    unittest.main()
