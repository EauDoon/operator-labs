import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from corridor_lab.cli import main


class CliWorkflowTests(unittest.TestCase):
    def test_compare_named_routes(self):
        case = Path(__file__).resolve().parents[1] / "examples/fictional-corridor"
        args = ["compare", str(case / "scenario.json"), "--routes", str(case / "routes"), "--format", "json"]
        first = "fictional-linked-instant"
        second = "fictional-tokenized-deposit"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args + ["--route-id", second, "--route-id", first]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual([row["route_id"] for row in result["routes"]], [first, second])
        self.assertEqual(len(result["break_even_volumes"]), 1)
        for bad in (["--route-id", "absent"], ["--route-id", first, "--route-id", first]):
            with self.subTest(bad=bad), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args + bad), 2)

    def test_declared_inspection_commands_export_all_formats(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            root = Path(directory)
            source = root / "scenario.json"
            self.assertEqual(main(["init", "--output", str(source)]), 0)
            before = source.read_bytes()
            for command, extra in (("cost-ledger", []), ("deadline-target", ["--probability", "0.95"]),
                                   ("resolution-quantiles", ["--probabilities", "0.5,1"]),
                                   ("loss-profile", []), ("feasible-amount", [])):
                for fmt in ("json", "csv", "markdown"):
                    with self.subTest(command=command, format=fmt):
                        output = root / "report.txt"
                        self.assertEqual(main([command, str(source), *extra, "--format", fmt, "--output", str(output)]), 0)
                        self.assertIn("route_id", output.read_text(encoding="utf-8"))
                self.assertEqual(main([command, str(source), *extra, "--output", str(source)]), 2)
            self.assertEqual(source.read_bytes(), before)

    def test_starter_sweep_diff_and_preserved_sources(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            root = Path(directory)
            source = root / "source.json"
            self.assertEqual(main(["init", "--output", str(source)]), 0)
            before = source.read_bytes()
            sweep = root / "sweep.csv"
            self.assertEqual(main(["transaction-sweep", str(source), "--parameter", "deadline_hours", "--values", "1,2,8", "--output", str(sweep)]), 0)
            self.assertIn("deadline_hours", sweep.read_text())
            report = root / "diff.json"
            self.assertEqual(main(["diff", str(source), "--baseline", str(source), "--output", str(report)]), 0)
            self.assertTrue(all(row["delta"] == "0" for row in json.loads(report.read_text())["rows"]))
            self.assertEqual(main(["diff", str(source), "--baseline", str(source), "--output", str(source)]), 2)
            self.assertEqual(main(["batch", str(root), "--output", str(root / "batch.json")]), 2)
            self.assertEqual(source.read_bytes(), before)


class ReportFormatEnvironmentTests(unittest.TestCase):
    def test_format_environment_does_not_break_project_commands_without_reports(self):
        from unittest.mock import patch

        from helpers import route, scenario

        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err, patch.dict("os.environ", {"CORRIDOR_LAB_FORMAT": "yaml"}):
            root = Path(directory)
            source = root / "scenario.json"
            source.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            project = root / "project"
            project.mkdir()
            self.assertEqual(main(["project", "create", "--directory", str(project), "--project-id", "fictional",
                                   "--scenario", str(source)]), 0)
            self.assertEqual(main(["project", "validate", str(project)]), 0)
            self.assertEqual(main(["project", "open", str(project)]), 0)
            self.assertEqual(err.getvalue(), "")
            # A command that does emit a report still rejects the unsupported default.
            self.assertEqual(main(["evaluate", str(source)]), 2)
            self.assertIn("CORRIDOR_LAB_FORMAT=yaml is not supported", err.getvalue())
