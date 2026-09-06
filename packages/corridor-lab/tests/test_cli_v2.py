"""End-to-end CLI coverage for the v2 fee and workload commands."""

import sys
import unittest
from pathlib import Path

import fee_helpers as fh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from corridor_lab.cli import main  # noqa: E402

EXAMPLE = ROOT / "examples" / "fictional-tiered-workload"
SCENARIO = str(EXAMPLE / "scenario.json")


class CliFeeWorkloadTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_validate_accepts_the_v2_example(self):
        code, out, _ = self._run(["validate", SCENARIO])
        self.assertEqual(code, 0)
        self.assertEqual(out, "valid\n")

    def test_workload_markdown_matches_the_recorded_example(self):
        code, out, _ = self._run(["workload", SCENARIO, "--format", "markdown"])
        self.assertEqual(code, 0)
        self.assertEqual(out, (EXAMPLE / "expected" / "workload.md").read_text(encoding="utf-8"))

    def test_workload_csv_matches_the_recorded_example(self):
        code, out, _ = self._run(["workload", SCENARIO, "--format", "csv"])
        self.assertEqual(code, 0)
        self.assertEqual(out, (EXAMPLE / "expected" / "workload.csv").read_text(encoding="utf-8"))

    def test_break_even_matches_the_recorded_example(self):
        code, out, _ = self._run(
            ["break-even", SCENARIO, "--left", "tiered-marginal", "--right", "flat-fee", "--format", "markdown"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, (EXAMPLE / "expected" / "break-even.md").read_text(encoding="utf-8"))

    def test_workload_selection_is_honoured(self):
        code, out, _ = self._run(["workload", SCENARIO, "--workloads", "peak", "--format", "json"])
        self.assertEqual(code, 0)
        self.assertIn('"workload_id":"peak"', out)
        self.assertNotIn('"workload_id":"low"', out)

    def test_unknown_workload_id_fails_with_actionable_text(self):
        code, _, err = self._run(["workload", SCENARIO, "--workloads", "ghost"])
        self.assertEqual(code, 2)
        self.assertIn("unknown workload id(s): ghost", err)

    def test_output_suffix_selects_the_format(self, ):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "workload.csv"
            code, _, err = self._run(["workload", SCENARIO, "--output", str(target)])
            self.assertEqual(code, 0, err)
            self.assertIn("workload_id,route_id", target.read_text(encoding="utf-8"))

    def test_evaluate_still_reports_fee_components(self):
        code, out, _ = self._run(["evaluate", SCENARIO, "--format", "json"])
        self.assertEqual(code, 0)
        self.assertIn('"explicit_fee_transaction_send":"6.25"', out)
        self.assertIn('"explicit_fee_period_amortized_send":"4.00"', out)
        self.assertIn('"fee_basis":"marginal"', out)

    def test_compare_reports_the_declared_fee_schedule(self):
        code, out, _ = self._run(["evaluate", SCENARIO, "--format", "json"])
        self.assertEqual(code, 0)
        self.assertIn('"fee_schedule":{"basis":"marginal"', out)
        self.assertIn('"amortization_over":"scenario_volume"', out)

    def test_sensitivity_still_works_on_a_v2_route(self):
        code, out, err = self._run(
            ["sensitivity", SCENARIO, "--parameter", "fx_spread_bps", "--values", "10,50", "--format", "csv"]
        )
        self.assertEqual(code, 0, err)
        self.assertIn("tiered-marginal", out)

    def test_flat_fee_sensitivity_is_rejected_on_a_tiered_route(self):
        code, _, err = self._run(["sensitivity", SCENARIO, "--parameter", "fixed_fee_send", "--values", "1,2"])
        self.assertEqual(code, 2)
        self.assertIn("not an active assumption", err)

    def test_multi_leg_example_matches_the_recorded_output(self):
        example = ROOT / "examples" / "fictional-multi-leg"
        code, out, _ = self._run(["evaluate", str(example / "scenario.json"), "--format", "markdown"])
        self.assertEqual(code, 0)
        self.assertEqual(out, (example / "expected" / "evaluate.md").read_text(encoding="utf-8"))

    def test_multi_leg_example_json_matches_the_recorded_output(self):
        example = ROOT / "examples" / "fictional-multi-leg"
        code, out, _ = self._run(["evaluate", str(example / "scenario.json"), "--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(out, (example / "expected" / "evaluate.json").read_text(encoding="utf-8"))

    def test_multi_leg_declared_inputs_omit_scalar_fee_fields(self):
        example = ROOT / "examples" / "fictional-multi-leg"
        code, out, _ = self._run(["evaluate", str(example / "scenario.json"), "--format", "json"])
        self.assertEqual(code, 0)
        self.assertIn('"legs":[{"delay_hours":"1","fixed_fee_send":"1"', out)
        self.assertIn('"terminal_leg":"offshore"', out)
        self.assertIn('"fee_basis":"composed"', out)

    def test_missing_scenario_reports_exit_two(self):
        code, _, err = self._run(["workload", str(EXAMPLE / "nope.json")])
        self.assertEqual(code, 2)
        self.assertIn("error:", err)


    def test_funding_markdown_matches_the_recorded_example(self):
        funding_example = ROOT / "examples" / "fictional-funding"
        code, out, _ = self._run(
            ["funding", str(funding_example / "scenario.json"), "--delays", "0,1", "--format", "markdown"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, (funding_example / "expected" / "funding.md").read_text(encoding="utf-8"))

    def test_funding_csv_matches_the_recorded_example(self):
        funding_example = ROOT / "examples" / "fictional-funding"
        code, out, _ = self._run(
            ["funding", str(funding_example / "scenario.json"), "--delays", "0,1", "--format", "csv"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, (funding_example / "expected" / "funding.csv").read_text(encoding="utf-8"))

    def test_funding_defaults_to_the_declared_delay(self):
        funding_example = ROOT / "examples" / "fictional-funding"
        code, out, _ = self._run(["funding", str(funding_example / "scenario.json"), "--format", "json"])
        self.assertEqual(code, 0)
        self.assertIn('"delays":["0"]', out)

    def test_funding_on_a_scenario_without_a_schedule_is_actionable(self):
        code, _, err = self._run(["funding", SCENARIO])
        self.assertEqual(code, 2)
        self.assertIn("declares no funding schedule", err)

    def test_funding_rejects_non_numeric_delays(self):
        funding_example = ROOT / "examples" / "fictional-funding"
        code, _, err = self._run(["funding", str(funding_example / "scenario.json"), "--delays", "0,soon"])
        self.assertEqual(code, 2)
        self.assertIn("whole numbers of periods", err)


class ExampleAssetTests(unittest.TestCase):
    def test_every_expected_asset_is_referenced_by_the_readme(self):
        readme = (EXAMPLE / "README.md").read_text(encoding="utf-8")
        for name in ("workload.md", "workload.csv", "break-even.md"):
            self.assertIn(name, readme)

    def test_example_scenario_declares_workloads_and_a_tiered_route(self):
        import json

        data = json.loads((EXAMPLE / "scenario.json").read_text(encoding="utf-8"))
        self.assertEqual(data["contract_version"], "corridor-lab.scenario/v2")
        self.assertEqual(len(data["workload_scenarios"]), 3)
        self.assertIn("fee_schedule", data["routes"][0])
        self.assertNotIn("fee_schedule", data["routes"][1])


if __name__ == "__main__":
    unittest.main()

