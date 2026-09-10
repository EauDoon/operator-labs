import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tracecanary.cli import main
from tracecanary.output import write_report

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/v1"
class OutputTests(unittest.TestCase):
    def test_output_matches_stdout_and_preserves_inputs(self):
        args = ["check", "--contract", str(FIXTURES / "contract.json"), "--input", str(FIXTURES / "safe-export.json"), "--format", "json"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                self.assertEqual(main(args), 0)
            self.assertEqual(main(args + ["--output", str(path)]), 0)
            self.assertEqual(path.read_bytes(), capture.getvalue().encode())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args + ["--output", str(FIXTURES / "safe-export.json")]), 2)

    def test_failed_atomic_replace_preserves_previous_report_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text("old")
            with patch("tracecanary.output.os.replace", side_effect=OSError), self.assertRaises(OSError):
                write_report(path, "new")
            self.assertEqual(path.read_text(), "old")
            self.assertEqual(list(Path(directory).iterdir()), [path])
