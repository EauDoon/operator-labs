import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from corridor_lab.cli import main


class CliWorkflowTests(unittest.TestCase):
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
