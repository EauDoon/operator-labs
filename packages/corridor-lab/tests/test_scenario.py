import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import InvalidOperation
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from corridor_lab.canonical import (
    MAX_INPUT_BYTES,
    InputError,
    load_json,
    parse_json_text,
)
from corridor_lab.cli import (
    DEFAULT_REPORT_FORMAT,
    FRONTIER_REPORT_FORMATS,
    REPORT_FORMAT_ENV,
    TABULAR_REPORT_FORMATS,
    build_parser,
    main,
    resolve_report_format,
)
from corridor_lab.scenario import ScenarioError, parse_scenario, parse_scenario_text
from helpers import route, scenario


class ScenarioTests(unittest.TestCase):
    def test_batch_rejects_a_scenario_swapped_after_discovery(self):
        import corridor_lab.cli as cli_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inside = root / "inside.json"
            inside.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            replacement = root / "replacement.tmp"
            replacement.write_text(
                json.dumps(scenario(routes=[route(route_id="replacement")])),
                encoding="utf-8",
            )
            original_reader = cli_module._read_scanned_scenario

            def swap_before_open(*args):
                replacement.replace(inside)
                return original_reader(*args)

            stdout = StringIO()
            stderr = StringIO()
            with patch.object(
                cli_module,
                "_read_scanned_scenario",
                side_effect=swap_before_open,
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["batch", str(root), "--include-paths"])

        self.assertEqual(result, 2)
        self.assertIn('"status":"unresolved"', stdout.getvalue())
        self.assertIn("inside.json: batch input changed while being read", stderr.getvalue())

    def test_batch_rejects_empty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["batch", temporary])
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("contains no JSON scenario files", stderr.getvalue())

    def test_batch_accepts_case_insensitive_json_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.JSON"
            path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(["batch", temporary])
        self.assertEqual(result, 0)

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

    def test_non_finite_decimals_are_rejected(self):
        for payload in ("NaN", "Infinity", "-Infinity", "inf", "-inf"):
            with self.subTest(payload=payload):
                data = scenario()
                data["transaction"]["send_amount"] = payload
                with self.assertRaisesRegex(ScenarioError, "must be finite"):
                    parse_scenario(data)
        with self.assertRaisesRegex(ScenarioError, "JSON constant NaN is not permitted"):
            parse_json_text('{"send_amount": NaN}')
        with self.assertRaisesRegex(ScenarioError, "JSON constant Infinity is not permitted"):
            parse_json_text('{"send_amount": Infinity}')

    def test_cli_maps_decimal_exception_to_exit_two(self):
        stderr = StringIO()
        with patch("corridor_lab.cli.load_scenario", side_effect=InvalidOperation):
            with redirect_stderr(stderr):
                result = main(["validate", "fictional.json"])
        self.assertEqual(result, 2)
        self.assertEqual(stderr.getvalue(), "error: InvalidOperation\n")

    def test_cli_includes_chained_exception_cause(self):
        def boom(_path: object) -> None:
            try:
                raise InvalidOperation("division impossible")
            except InvalidOperation as exc:
                raise InputError("decimal calculation failed") from exc

        stderr = StringIO()
        with patch("corridor_lab.cli.load_scenario", side_effect=boom):
            with redirect_stderr(stderr):
                result = main(["validate", "fictional.json"])
        self.assertEqual(result, 2)
        self.assertEqual(stderr.getvalue(), "error: decimal calculation failed: division impossible\n")

    def test_batch_preserves_evaluation_cause_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ok.json").write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            (root / "broken.json").write_text(json.dumps(scenario()), encoding="utf-8")
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["batch", str(root), "--include-paths", "--format", "json"])
        self.assertEqual(result, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "unresolved")
        unresolved = [item for item in payload["items"] if item["status"] == "unresolved"]
        self.assertEqual(len(unresolved), 1)
        error = unresolved[0]["report"]["error"]
        self.assertIn("broken.json", error)
        self.assertIn("evaluate requires routes embedded in the scenario", error)
        self.assertNotIn("could not be evaluated", error)
        self.assertIn("error: scenario-0001: broken.json: evaluate requires routes embedded in the scenario", stderr.getvalue())

    def test_batch_names_missing_directory(self):
        missing = Path("missing-batch-dir")
        stderr = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            result = main(["batch", str(missing)])
        self.assertEqual(result, 2)
        self.assertIn(f"error: batch input_dir must be a directory: {missing}", stderr.getvalue())

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

    def test_report_format_prefers_flag_then_suffix_then_env(self):
        self.assertEqual(
            resolve_report_format("json", "report.md", TABULAR_REPORT_FORMATS, environ={REPORT_FORMAT_ENV: "csv"}),
            "json",
        )
        self.assertEqual(
            resolve_report_format(None, "Report.MD", TABULAR_REPORT_FORMATS, environ={REPORT_FORMAT_ENV: "csv"}),
            "markdown",
        )
        self.assertEqual(
            resolve_report_format(None, "report.txt", TABULAR_REPORT_FORMATS, environ={REPORT_FORMAT_ENV: " Markdown "}),
            "markdown",
        )
        self.assertEqual(
            resolve_report_format(None, None, TABULAR_REPORT_FORMATS, environ={REPORT_FORMAT_ENV: ""}),
            DEFAULT_REPORT_FORMAT,
        )
        with self.assertRaisesRegex(InputError, "--output suffix implies csv"):
            resolve_report_format(None, "frontier.csv", FRONTIER_REPORT_FORMATS)
        with self.assertRaisesRegex(InputError, f"{REPORT_FORMAT_ENV}=csv is not supported"):
            resolve_report_format(None, None, FRONTIER_REPORT_FORMATS, environ={REPORT_FORMAT_ENV: "CSV"})
        with self.assertRaisesRegex(InputError, f"{REPORT_FORMAT_ENV}=xml is not supported"):
            resolve_report_format(None, None, TABULAR_REPORT_FORMATS, environ={REPORT_FORMAT_ENV: "xml"})

    def test_cli_infers_format_from_output_suffix_and_env(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            markdown_output = Path(temporary) / "report.md"
            csv_output = Path(temporary) / "report.csv"
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                result = main(["evaluate", str(path), "--output", str(markdown_output)])
            self.assertEqual(result, 0)
            self.assertTrue(markdown_output.read_text(encoding="utf-8").startswith("# Corridor Lab report"))
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(["evaluate", str(path), "--format", "json", "--output", str(markdown_output)])
            self.assertEqual(result, 0)
            self.assertTrue(markdown_output.read_text(encoding="utf-8").startswith("{"))
            with patch.dict(os.environ, {REPORT_FORMAT_ENV: "csv"}):
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    result = main(["evaluate", str(path), "--output", str(csv_output)])
            self.assertEqual(result, 0)
            self.assertTrue(csv_output.read_text(encoding="utf-8").startswith("route_id,"))
            stdout = StringIO()
            with patch.dict(os.environ, {REPORT_FORMAT_ENV: "markdown"}):
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    result = main(["evaluate", str(path)])
            self.assertEqual(result, 0)
            self.assertTrue(stdout.getvalue().startswith("# Corridor Lab report"))
            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                result = main(["pareto", str(path), "--output", str(csv_output)])
            self.assertEqual(result, 2)
            self.assertIn("--output suffix implies csv, which is not supported", stderr.getvalue())
            stderr = StringIO()
            with patch.dict(os.environ, {REPORT_FORMAT_ENV: "yaml"}):
                with redirect_stdout(StringIO()), redirect_stderr(stderr):
                    result = main(["evaluate", str(path)])
            self.assertEqual(result, 2)
            self.assertIn("CORRIDOR_LAB_FORMAT=yaml is not supported", stderr.getvalue())

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

    def test_cli_rejects_non_finite_and_duplicate_value_lists(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8")
            cases = (
                (["sensitivity", str(path), "--parameter", "fx_spread_bps", "--values", "NaN"], "--values value must be finite"),
                (["sensitivity", str(path), "--parameter", "fx_spread_bps", "--values", "Infinity"], "--values value must be finite"),
                (["sensitivity", str(path), "--parameter", "fx_spread_bps", "--values", "10,10.0"], "--values must not contain duplicate values"),
                (
                    [
                        "stress-grid",
                        str(path),
                        "--parameter-a",
                        "fx_rate",
                        "--values-a",
                        "1.7,1.70",
                        "--parameter-b",
                        "fx_spread_bps",
                        "--values-b",
                        "25,50",
                    ],
                    "--values-a must not contain duplicate values",
                ),
            )
            for argv, message in cases:
                with self.subTest(message=message):
                    stderr = StringIO()
                    with redirect_stdout(StringIO()), redirect_stderr(stderr):
                        result = main(argv)
                    self.assertEqual(result, 2)
                    self.assertIn(message, stderr.getvalue())

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
                    [
                        "sensitivity",
                        str(path),
                        "--parameter",
                        " fx_spread_bps ",
                        "--values",
                        "10,25",
                        "--format",
                        "json",
                    ]
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
                ("--values-a", "comma-separated decimal values", "json, csv, or markdown", "CORRIDOR_LAB_FORMAT"),
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
