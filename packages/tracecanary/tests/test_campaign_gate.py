"""campaign compare --fail-on-regression: an exit-code gate for CI."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from support import run_cli, write_fixture, write_json
from tracecanary.campaign import compare_summaries, render_comparison_human
from tracecanary.fixture import bundle
from tracecanary.report import render_json


def summary(status: str = "pass", **phases: tuple[str, dict]) -> dict:
    document = {
        "summary_version": "tracecanary.campaign-summary/v1",
        "contract_version": "tracecanary/v1",
        "campaign_status": status,
        "phases": {
            "contract": {"status": "pass", "finding_counts": {}},
            "candidates": {"status": "pass", "finding_counts": {}},
        },
        "candidate_count": 1,
        "compatibility": {
            "required_fields": [{"scope": "resource", "key": "service.name"}],
            "coverage": {"minimum_ratio": None, "population_scope": None, "population_minimum": None,
                         "batch_minimum_ratio": None},
        },
    }
    for name, (phase_status, counts) in phases.items():
        document["phases"][name] = {"status": phase_status, "finding_counts": counts}
    return document


class GateVerdictTests(unittest.TestCase):
    def gate(self, before: dict, after: dict) -> dict:
        return compare_summaries(before, after, gate=True)["gate"]

    def test_identical_summaries_pass(self):
        self.assertEqual(self.gate(summary(), summary()), {"status": "pass", "reasons": []})

    def test_a_new_code_in_a_phase_is_a_regression(self):
        after = summary("regression", candidates=("regression", {"TC001": 2}))
        self.assertEqual(self.gate(summary(), after), {"status": "regression", "reasons": [
            "campaign: pass -> regression", "candidates: pass -> regression", "candidates: new TC001 x2"]})

    def test_a_higher_count_for_a_persistent_code_is_a_regression(self):
        before = summary("regression", candidates=("regression", {"TC001": 1}))
        after = summary("regression", candidates=("regression", {"TC001": 3}))
        self.assertEqual(self.gate(before, after), {"status": "regression", "reasons": ["candidates: TC001 1 -> 3"]})

    def test_only_resolved_or_lower_counts_pass(self):
        before = summary("regression", candidates=("regression", {"TC001": 3, "TC002": 1}))
        after = summary("regression", candidates=("regression", {"TC001": 1}))
        self.assertEqual(self.gate(before, after), {"status": "pass", "reasons": []})
        self.assertEqual(self.gate(before, summary())["status"], "pass")

    def test_a_phase_that_stopped_running_is_a_regression(self):
        before = summary(batch=("pass", {}))
        self.assertEqual(self.gate(before, summary()), {"status": "regression", "reasons": ["batch: pass -> absent"]})
        skipped = summary(batch=("skipped", {}))
        self.assertEqual(self.gate(before, skipped)["reasons"], ["batch: pass -> skipped"])

    def test_a_phase_new_in_the_candidate_is_judged_by_its_own_result(self):
        self.assertEqual(self.gate(summary(), summary(batch=("pass", {}))), {"status": "pass", "reasons": []})
        self.assertEqual(self.gate(summary(control=("skipped", {})), summary(control=("pass", {})))["status"], "pass")
        after = summary("regression", batch=("regression", {"TC013": 1}))
        self.assertEqual(self.gate(summary(), after)["reasons"],
                         ["campaign: pass -> regression", "batch: absent -> regression", "batch: new TC013 x1"])

    def test_an_unresolved_candidate_is_unresolved_even_after_an_unresolved_baseline(self):
        unresolved = summary("unresolved", candidates=("unresolved", {}))
        self.assertEqual(self.gate(summary(), unresolved)["status"], "unresolved")
        self.assertEqual(self.gate(unresolved, copy.deepcopy(unresolved)), {"status": "unresolved", "reasons": []})
        self.assertEqual(self.gate(unresolved, summary())["status"], "pass")

    def test_without_the_gate_the_comparison_is_unchanged(self):
        before, after = summary(), summary("regression", candidates=("regression", {"TC001": 1}))
        plain = compare_summaries(before, after)
        self.assertNotIn("gate", plain)
        gated = compare_summaries(before, after, gate=True)
        self.assertEqual({key: value for key, value in gated.items() if key != "gate"}, plain)
        self.assertNotIn("Gate:", render_comparison_human(plain))
        self.assertTrue(render_comparison_human(gated).endswith(
            "Gate: REGRESSION\n  - campaign: pass -> regression\n  - candidates: pass -> regression\n"
            "  - candidates: new TC001 x1\n"))


def _saved_summary(root: Path, candidate: str, name: str) -> Path:
    project = root / name
    sources = root / f"{name}-sources"
    contract = write_fixture(sources / "contract.json", "contract.json")
    baseline = write_fixture(sources / "baseline.json", "safe-export.json")
    chosen = write_fixture(sources / "candidate.json", candidate)
    project.mkdir()
    run_cli("project", "create", "--directory", project, "--project-id", name, "--contract", contract,
            "--baseline", baseline, "--candidate", chosen)
    target = root / f"{name}.json"
    run_cli("campaign", "run", project, "--save-summary", target)
    return target


class GateCliTests(unittest.TestCase):
    def test_exit_codes_follow_the_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            safe = _saved_summary(root, "safe-export.json", "safe")
            leak = _saved_summary(root, "leaked-prompt.json", "leak")
            unresolved = write_json(root / "unresolved.json", dict(json.loads(safe.read_text(encoding="utf-8")),
                                                                   campaign_status="unresolved"))
            for before, after, expected in ((safe, safe, 0), (safe, leak, 1), (leak, safe, 0),
                                            (safe, unresolved, 2), (unresolved, unresolved, 2)):
                with self.subTest(before=before.name, after=after.name):
                    code, stdout, _ = run_cli("campaign", "compare", before, after, "--fail-on-regression")
                    self.assertEqual(code, expected)
                    self.assertIn(f"Gate: {('PASS', 'REGRESSION', 'UNRESOLVED')[expected]}", stdout)
                    code, stdout, _ = run_cli("campaign", "compare", before, after, "--fail-on-regression",
                                              "--format", "json")
                    self.assertEqual(json.loads(stdout)["gate"]["status"], ("pass", "regression", "unresolved")[expected])

    def test_without_the_flag_output_and_exit_are_as_before(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            safe = _saved_summary(root, "safe-export.json", "safe")
            leak = _saved_summary(root, "leaked-prompt.json", "leak")
            for fmt in ("human", "json"):
                code, stdout, _ = run_cli("campaign", "compare", safe, leak, "--format", fmt)
                self.assertEqual(code, 0)
                comparison = compare_summaries(json.loads(safe.read_text(encoding="utf-8")),
                                               json.loads(leak.read_text(encoding="utf-8")))
                expected = render_json(comparison) if fmt == "json" else render_comparison_human(comparison)
                self.assertEqual(stdout, expected)
                self.assertNotIn("Gate:", stdout)
                self.assertNotIn('"gate"', stdout)

    def test_incompatible_or_malformed_summaries_stay_unresolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            safe = json.loads(_saved_summary(root, "safe-export.json", "safe").read_text(encoding="utf-8"))
            other = write_json(root / "other.json", dict(safe, contract_version="tracecanary/v999"))
            broken = write_json(root / "broken.json", dict(safe, phases=[]))
            for after in (other, broken):
                code, stdout, _ = run_cli("campaign", "compare", root / "safe.json", after, "--fail-on-regression")
                self.assertEqual((code, stdout), (2, ""))

    def test_gate_reasons_carry_no_canary_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            safe = _saved_summary(root, "safe-export.json", "safe")
            leak = _saved_summary(root, "leaked-prompt.json", "leak")
            _, stdout, _ = run_cli("campaign", "compare", safe, leak, "--fail-on-regression", "--format", "json")
            values = [canary["value"] for canary in bundle()["contract.json"]["canaries"]]
            self.assertTrue(json.loads(stdout)["gate"]["reasons"])
            self.assertFalse(any(value in stdout for value in values))


if __name__ == "__main__":
    unittest.main()
