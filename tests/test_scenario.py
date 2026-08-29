import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import InvalidOperation
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from helpers import route, scenario
from corridor_lab.canonical import InputError, MAX_INPUT_BYTES, load_json, parse_json_text
from corridor_lab.cli import build_parser, main
from corridor_lab.scenario import ScenarioError, parse_scenario, parse_scenario_text


class ScenarioTests(unittest.TestCase):
    def test_batch_rejects_empty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["batch", temporary])
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("contains no JSON scenario files", stderr.getvalue())

    def test_valid_minimal_scenario(self):
        parsed = parse_scenario(scenario())
        self.assertEqual(parsed.transaction.send_amount, 100)
        self.assertEqual(parsed.routes, ())

    def test_unknown_field_fails_closed(self):
        data = scenario()
        data["unexpected"] = True
        with self.assertRaises(ScenarioError):
            parse_scenario(data)

    def test_unsupported_precision_fails_closed(self):
        data = scenario()
        data["transaction"]["send_precision"] = 7
        with self.assertRaises(ScenarioError):
            parse_scenario(data)

    def test_objective_requires_guardrail(self):
        data = scenario(objective={"metric": "maximize_expected_recipient_amount", "guardrails": {}})
        with self.assertRaises(ScenarioError):
            parse_scenario(data)

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"x": 1, "x": 2}', encoding="utf-8")
            with self.assertRaises(ScenarioError):
                load_json(path)

    def test_excessive_decimal_magnitude_and_scale_are_rejected(self):
        too_large = scenario()
        too_large["transaction"]["send_amount"] = "9999999999999999999"
        with self.assertRaises(ScenarioError):
            parse_scenario(too_large)
        too_precise = scenario()
        too_precise["transaction"]["send_amount"] = "1.1234567890123"
        with self.assertRaises(ScenarioError):
            parse_scenario(too_precise)

    def test_cli_maps_decimal_exception_to_exit_two(self):
        stderr = StringIO()
        with patch("corridor_lab.cli.load_scenario", side_effect=InvalidOperation):
            with redirect_stderr(stderr):
                result = main(["validate", "fictional.json"])
        self.assertEqual(result, 2)
        self.assertIn("error:", stderr.getvalue())

    def test_cli_format_choices_match_documented_commands(self):
        parser = build_parser()
        tabular = ("json", "csv", "markdown")
        frontier = ("json", "markdown")
        cases = (
            ("evaluate", [], tabular),
            ("compare", ["--routes", "routes"], tabular),
            ("sensitivity", ["--parameter", "fx_spread_bps", "--values", "10"], tabular),
            (
                "stress-grid",
                ["--parameter-a", "fx_rate", "--values-a", "1.7", "--parameter-b", "fx_spread_bps", "--values-b", "25"],
                tabular,
            ),
            ("pareto", [], frontier),
            ("batch", [], frontier),
        )
        for command, extra, allowed in cases:
            for output_format in ("json", "csv", "markdown"):
                argv = [command, "input", *extra, "--format", output_format]
                if output_format in allowed:
                    self.assertEqual(parser.parse_args(argv).format, output_format)
                    continue
                stderr = StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                    parser.parse_args(argv)
                self.assertEqual(caught.exception.code, 2)

    def test_cli_evaluate_requires_embedded_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(scenario()), encoding="utf-8")
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["evaluate", str(path)])
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("evaluate requires routes embedded in the scenario", stderr.getvalue())

    def test_cli_compare_rejects_missing_routes_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(scenario()), encoding="utf-8")
            missing = Path(temporary) / "missing-routes"
            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                result = main(["compare", str(path), "--routes", str(missing)])
        self.assertEqual(result, 2)
        self.assertIn("--routes is not a file or directory", stderr.getvalue())

    def test_cli_compare_rejects_empty_route_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(scenario()), encoding="utf-8")
            folder = Path(temporary) / "routes"
            folder.mkdir()
            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                result = main(["compare", str(path), "--routes", str(folder)])
        self.assertEqual(result, 2)
        self.assertIn("contains no JSON files", stderr.getvalue())

    def test_cli_sensitivity_rejects_blank_value_slots(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                result = main(["sensitivity", str(path), "--parameter", "fx_spread_bps", "--values", "10,,50"])
        self.assertEqual(result, 2)
        self.assertIn("--values must be a comma-separated list of decimals", stderr.getvalue())

    def test_cli_stress_grid_names_the_invalid_values_flag(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                result = main(
                    [
                        "stress-grid",
                        str(path),
                        "--parameter-a",
                        "fx_rate",
                        "--values-a",
                        "1.7,",
                        "--parameter-b",
                        "fx_spread_bps",
                        "--values-b",
                        "25,50",
                    ]
                )
        self.assertEqual(result, 2)
        self.assertIn("error: --values-a must be a comma-separated list of decimals", stderr.getvalue())

    def test_cli_rejects_empty_scenario_and_batch_paths(self):
        cases = (
            (["validate", ""], "scenario must not be empty"),
            (["validate", "   "], "scenario must not be empty"),
            (["batch", ""], "input_dir must not be empty"),
            (["batch", " \t"], "input_dir must not be empty"),
        )
        for argv, message in cases:
            with self.subTest(argv=argv):
                stderr = StringIO()
                with redirect_stdout(StringIO()), redirect_stderr(stderr):
                    result = main(argv)
                self.assertEqual(result, 2)
                self.assertIn(message, stderr.getvalue())

    def test_cli_rejects_empty_routes_output_and_parameter(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            cases = (
                (["compare", str(path), "--routes", ""], "--routes must not be empty"),
                (["evaluate", str(path), "--output", "   "], "--output must not be empty"),
                (["sensitivity", str(path), "--parameter", "", "--values", "10"], "--parameter must not be empty"),
                (
                    [
                        "stress-grid",
                        str(path),
                        "--parameter-a",
                        "  ",
                        "--values-a",
                        "1.7",
                        "--parameter-b",
                        "fx_spread_bps",
                        "--values-b",
                        "25",
                    ],
                    "--parameter-a must not be empty",
                ),
            )
            for argv, message in cases:
                with self.subTest(message=message):
                    stderr = StringIO()
                    with redirect_stdout(StringIO()), redirect_stderr(stderr):
                        result = main(argv)
                    self.assertEqual(result, 2)
                    self.assertIn(message, stderr.getvalue())

    def test_cli_strips_sensitivity_parameter_whitespace(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(
                    ["sensitivity", str(path), "--parameter", " fx_spread_bps ", "--values", "10,25"]
                )
        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("corridor-lab.sensitivity/v1", stdout.getvalue())

    def test_cli_help_documents_parameters_formats_and_value_flags(self):
        cases = (
            (
                ["sensitivity", "--help"],
                ("one of fx_rate, fixed_fee_send, percent_fee_bps, fx_spread_bps", "comma-separated decimal values"),
            ),
            (
                ["stress-grid", "--help"],
                ("--values-a", "comma-separated decimal values", "json, csv, or markdown"),
            ),
            (
                ["batch", "--help"],
                ("include JSON files in subdirectories", "csv is not supported", "write the report to this UTF-8 path"),
            ),
            (
                ["pareto", "--help"],
                ("path to a fictional scenario JSON file", "csv is not supported"),
            ),
        )
        for argv, needles in cases:
            with self.subTest(argv=argv):
                stdout = StringIO()
                with redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
                    main(argv)
                self.assertEqual(caught.exception.code, 0)
                text = " ".join(stdout.getvalue().split())
                for needle in needles:
                    self.assertIn(needle, text)

    def test_schema_embedded_routes_reference_route_contract(self):
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "scenario.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["routes"]["items"]["$ref"], "route.schema.json")

    def test_in_memory_json_text_uses_file_validation_boundaries(self):
        valid = json.dumps(scenario())
        self.assertEqual(parse_scenario_text(valid).scenario_id, "fictional-test-scenario")
        numeric = scenario()
        numeric["transaction"]["send_amount"] = 100.5
        self.assertEqual(str(parse_scenario_text(json.dumps(numeric)).transaction.send_amount), "100.5")
        with self.assertRaises(ScenarioError):
            parse_json_text('{"fictional": true, "fictional": true}')
        with self.assertRaises(ScenarioError):
            parse_json_text(" " * 1_000_001)
        with self.assertRaises(ScenarioError):
            parse_json_text("[" * 65 + "0" + "]" * 65)

    def test_file_input_is_rejected_at_the_bounded_read_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oversized.json"
            path.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
            with self.assertRaisesRegex(InputError, "input exceeds"):
                load_json(path)
