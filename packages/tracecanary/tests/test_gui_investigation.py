import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.fixture import bundle
from tracecanary.gui_controller import TraceCanaryController


class TraceCanaryControllerInvestigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.inputs = cls.root / "inputs"
        cls.inputs.mkdir()
        cls.paths: dict[str, Path] = {}
        for name, data in bundle().items():
            path = cls.inputs / name
            path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
            cls.paths[name] = path
        cls.reports = cls.root / "reports"
        cls.reports.mkdir()
        cls.controller = TraceCanaryController()

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def cli_json(self, *args: str) -> tuple[dict, int]:
        from tracecanary.cli import main

        output = self.reports / "cli-report.json"
        if output.exists():
            output.unlink()
        exit_code = main([*args, "--format", "json", "--output", str(output)])
        return json.loads(output.read_text(encoding="utf-8")), exit_code

    def test_inspect_agrees_with_cli(self):
        result = self.controller.inspect(self.paths["contract.json"])
        self.assertEqual(result.status, "pass")
        expected, _ = self.cli_json("inspect-contract", str(self.paths["contract.json"]))
        self.assertEqual(json.loads(result.json), expected)

    def test_control_pass_is_not_a_privacy_pass(self):
        contract = self.paths["contract.json"]
        positive = self.paths["positive-control.json"]
        control = self.controller.control_check(contract, positive)
        self.assertEqual(control.status, "pass")
        self.assertEqual(control.mode, "control-check")
        expected, exit_code = self.cli_json("control-check", "--contract", str(contract), "--input", str(positive))
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(control.json), expected)
        ordinary = self.controller.check(contract, positive)
        self.assertEqual(ordinary.status, "regression")
        self.assertEqual(ordinary.exit_code, 1)
        self.assertIn("not that privacy checks passed", control.human)

    def test_control_check_with_missing_canary_is_unresolved(self):
        control = self.controller.control_check(self.paths["contract.json"], self.paths["leaked-prompt.json"])
        self.assertEqual(control.status, "unresolved")
        self.assertEqual(control.exit_code, 2)

    def test_population_gate_agrees_with_cli_and_preserves_privacy(self):
        contract = self.paths["contract.json"]
        safe = self.paths["safe-export.json"]
        result = self.controller.population_gate(contract, safe, "span", "1")
        self.assertEqual(result.status, "pass")
        expected, _ = self.cli_json("population-gate", "--contract", str(contract), "--input", str(safe), "--scope", "span", "--minimum", "1")
        self.assertEqual(json.loads(result.json), expected)
        regression = self.controller.population_gate(contract, safe, "link", "5")
        self.assertEqual(regression.status, "regression")
        self.assertEqual(regression.exit_code, 1)
        invalid = self.controller.population_gate(contract, safe, "span", "2000000")
        self.assertEqual(invalid.status, "unresolved")
        non_integer = self.controller.population_gate(contract, safe, "span", "two")
        self.assertEqual(non_integer.status, "unresolved")

    def test_dropped_telemetry_agrees_with_cli(self):
        contract = self.paths["contract.json"]
        safe = self.paths["safe-export.json"]
        for require_zero in (False, True):
            with self.subTest(require_zero=require_zero):
                result = self.controller.dropped_telemetry(contract, safe, require_zero)
                self.assertEqual(result.status, "pass")
                flag = ["--require-zero"] if require_zero else []
                expected, _ = self.cli_json("dropped-telemetry", "--contract", str(contract), "--input", str(safe), *flag)
                self.assertEqual(json.loads(result.json), expected)

    def test_retention_matrix_agrees_with_cli_and_stays_value_free(self):
        contract = self.paths["contract.json"]
        result = self.controller.retention_matrix(contract, self.paths["sparse-retention.json"])
        self.assertEqual(result.status, "pass")
        expected, _ = self.cli_json("retention-matrix", "--contract", str(contract), "--input", str(self.paths["sparse-retention.json"]))
        self.assertEqual(json.loads(result.json), expected)
        matrix = json.loads(result.json)["retention_matrix"]
        self.assertEqual(matrix["entity_requirement_checks"], 5)
        span_fields = [field for field in matrix["fields"] if field["scope"] == "span"]
        self.assertTrue(span_fields and len(span_fields[0]["missing_paths"]) == 1)
        for field in matrix["fields"]:
            for pointer in field["missing_paths"]:
                self.assertTrue(pointer.startswith("/resourceSpans/"))
        self.assertNotIn("gen_ai.operation.name", result.json)
        self.assertNotIn("TCANARY", result.json)

    def test_coverage_gate_thresholds_and_unresolved_populations(self):
        contract = self.paths["contract.json"]
        sparse = self.controller.coverage_gate(contract, self.paths["sparse-retention.json"], "0.95")
        self.assertEqual(sparse.status, "regression")
        self.assertEqual(json.loads(sparse.json)["coverage_gate"]["minimum_ratio"], "0.95")
        tolerant = self.controller.coverage_gate(contract, self.paths["sparse-retention.json"], "0.5")
        self.assertEqual(tolerant.status, "pass")
        safe = self.controller.coverage_gate(contract, self.paths["safe-export.json"], "1.0")
        self.assertEqual(safe.status, "pass")
        empty = self.controller.coverage_gate(contract, self.paths["missing-operational-fields.json"], "0")
        self.assertEqual(empty.status, "unresolved")
        malformed = self.controller.coverage_gate(contract, self.paths["safe-export.json"], "0.1234567")
        self.assertEqual(malformed.status, "unresolved")

    def test_coverage_diff_agrees_with_cli_and_flags_decrease(self):
        contract = self.paths["contract.json"]
        result = self.controller.coverage_diff(contract, self.paths["safe-export.json"], self.paths["sparse-retention.json"])
        self.assertEqual(result.status, "regression")
        expected, _ = self.cli_json("coverage-diff", "--contract", str(contract), "--baseline", str(self.paths["safe-export.json"]), "--candidate", str(self.paths["sparse-retention.json"]))
        self.assertEqual(json.loads(result.json), expected)
        decreased = json.loads(result.json)["coverage_diff"]["fields"]
        self.assertTrue(any(field["rate_delta"] and field["rate_delta"].startswith("-") for field in decreased))
        invalid = self.controller.coverage_diff(contract, self.paths["leaked-prompt.json"], self.paths["safe-export.json"])
        self.assertEqual(invalid.status, "unresolved")

    def test_batch_mixed_outcomes_with_unresolved_precedence(self):
        contract = self.paths["contract.json"]
        result = self.controller.batch(contract, self.inputs, recursive=False, include_paths=True)
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.input_dir, self.inputs)
        report = json.loads(result.json)
        found = {item["status"] for item in report["items"]}
        self.assertEqual(found, {"pass", "regression", "unresolved"})
        self.assertTrue(all(item.get("path", "").endswith(".json") for item in report["items"]))

    def test_batch_agrees_with_cli_for_baseline_mode(self):
        contract = self.paths["contract.json"]
        result = self.controller.batch(contract, self.inputs, recursive=False, include_paths=False, baseline_path=self.paths["safe-export.json"])
        expected, _ = self.cli_json(
            "batch",
            "--contract",
            str(contract),
            "--input-dir",
            str(self.inputs),
            "--baseline",
            str(self.paths["safe-export.json"]),
        )
        self.assertEqual(json.loads(result.json), expected)

    def test_coverage_batch_aggregate_accounting(self):
        contract = self.paths["contract.json"]
        result = self.controller.coverage_batch(contract, self.inputs, recursive=False, include_paths=False, minimum_ratio="0.95")
        self.assertEqual(result.status, "unresolved")
        report = json.loads(result.json)
        summary = report["coverage_summary"]
        self.assertEqual(summary["minimum_ratio_per_file"], "0.95")
        self.assertGreater(summary["unresolved_items"], 0)
        self.assertGreater(summary["validated_items"], 0)
        for field in summary["required_fields"]:
            self.assertIn("present", field)
            self.assertIn("entities", field)

    def test_starter_bundle_supports_every_acceptance_case(self):
        with tempfile.TemporaryDirectory() as destination:
            result = self.controller.create_starter_files(destination)
            self.assertIsNotNone(result.starter_paths)
            self.assertEqual(result.status, "pass")
            starter = Path(destination)
            names = {path.name for path in starter.iterdir()}
            self.assertEqual(
                names,
                {
                    "contract.json",
                    "safe-export.json",
                    "positive-control.json",
                    "leaked-prompt.json",
                    "leaked-tool-arguments.json",
                    "leaked-tool-result.json",
                    "leaked-user-identifier.json",
                    "missing-operational-fields.json",
                    "forbidden-path.json",
                    "sparse-retention.json",
                    "invalid-export.json",
                },
            )
            contract = str(starter / "contract.json")
            safe = self.controller.check(contract, str(starter / "safe-export.json"))
            self.assertEqual((safe.status, safe.exit_code), ("pass", 0))
            leak = self.controller.check(contract, str(starter / "leaked-prompt.json"))
            self.assertEqual((leak.status, leak.exit_code), ("regression", 1))
            retention = self.controller.check(contract, str(starter / "missing-operational-fields.json"))
            self.assertEqual((retention.status, retention.exit_code), ("regression", 1))
            threshold = self.controller.coverage_gate(contract, str(starter / "sparse-retention.json"), "0.95")
            self.assertEqual((threshold.status, threshold.exit_code), ("regression", 1))
            unresolved = self.controller.check(contract, str(starter / "invalid-export.json"))
            self.assertEqual((unresolved.status, unresolved.exit_code), ("unresolved", 2))
            control = self.controller.control_check(contract, str(starter / "positive-control.json"))
            self.assertEqual((control.status, control.exit_code), ("pass", 0))

    def test_guidance_reports_cli_level_diagnostics_value_free(self):
        result = self.controller.batch(self.paths["contract.json"], "does-not-exist")
        self.assertEqual(result.status, "unresolved")
        self.assertIn("must be a directory", result.human)
        self.assertNotIn("TCANARY", result.human)
        self.assertNotIn("TCANARY", result.json)


if __name__ == "__main__":
    unittest.main()
