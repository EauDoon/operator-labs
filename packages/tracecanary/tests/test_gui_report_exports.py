import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.fixture import bundle
from tracecanary.gui import save_gui_report
from tracecanary.gui_controller import GuiResult, TraceCanaryController


def _gui_result(result: GuiResult) -> GuiResult:
    return result


class GuiReportExportProtectionTests(unittest.TestCase):
    """GUI report exports reuse CLI protection and never replace inputs."""

    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory()
        root = Path(cls._temporary.name)
        cls.paths: dict[str, Path] = {}
        for name, data in bundle().items():
            path = root / name
            path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
            cls.paths[name] = path

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def _controller(self) -> TraceCanaryController:
        return TraceCanaryController()

    def test_save_rejects_replacing_contract_input(self):
        controller = self._controller()
        result = _gui_result(controller.check(self.paths["contract.json"], self.paths["safe-export.json"]))
        self.assertEqual(result.status, "pass")
        before = self.paths["contract.json"].read_bytes()
        with self.assertRaisesRegex(Exception, "must not replace an input"):
            save_gui_report(self.paths["contract.json"], result, "json")
        self.assertEqual(self.paths["contract.json"].read_bytes(), before)

    def test_save_rejects_replacing_trace_input(self):
        controller = self._controller()
        result = _gui_result(controller.check(self.paths["contract.json"], self.paths["safe-export.json"]))
        before = self.paths["safe-export.json"].read_bytes()
        with self.assertRaisesRegex(Exception, "must not replace an input"):
            save_gui_report(self.paths["safe-export.json"], result, "human")
        self.assertEqual(self.paths["safe-export.json"].read_bytes(), before)

    def test_save_rejects_symlink_and_hard_link_collisions(self):
        controller = self._controller()
        result = _gui_result(controller.check(self.paths["contract.json"], self.paths["safe-export.json"]))
        before = self.paths["safe-export.json"].read_bytes()
        symlink = self.paths["safe-export.json"].parent / "symlink-report.txt"
        hardlink = self.paths["safe-export.json"].parent / "hardlink-report.txt"
        os.symlink(self.paths["safe-export.json"].name, symlink)
        os.link(self.paths["safe-export.json"], hardlink)
        for destination in (symlink, hardlink):
            with self.subTest(destination=destination.name):
                with self.assertRaisesRegex(Exception, "must not replace an input"):
                    save_gui_report(destination, result, "human")
        self.assertEqual(self.paths["safe-export.json"].read_bytes(), before)

    def test_save_rejects_destination_inside_scanned_batch_directory(self):
        result = GuiResult(
            status="pass",
            exit_code=0,
            human="TraceCanary: PASS (0 finding(s))",
            json="{}",
            inputs=(self.paths["contract.json"],),
            input_dir=self.paths["safe-export.json"].parent,
        )
        with self.assertRaisesRegex(Exception, "outside the input directory"):
            save_gui_report(self.paths["safe-export.json"].parent / "batch-report.json", result, "json")

    def test_failed_write_cleans_up_temporary_files(self):
        controller = self._controller()
        result = _gui_result(controller.check(self.paths["contract.json"], self.paths["safe-export.json"]))
        blocker = self.paths["safe-export.json"].parent / "occupied-destination"
        blocker.mkdir()
        with self.assertRaises(OSError):
            save_gui_report(blocker, result, "json")
        leftovers = [entry.name for entry in blocker.parent.iterdir() if entry.name.startswith(".tracecanary-")]
        self.assertEqual(leftovers, [])

    def test_failed_protection_preserves_existing_report_file(self):
        controller = self._controller()
        result = _gui_result(controller.check(self.paths["contract.json"], self.paths["safe-export.json"]))
        destination = self.paths["safe-export.json"].parent / "previous-report.json"
        destination.write_text("previous report", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "must not replace an input"):
            save_gui_report(self.paths["safe-export.json"], result, "json")
        self.assertEqual(destination.read_text(encoding="utf-8"), "previous report")

    def test_successful_save_writes_rendered_report(self):
        controller = self._controller()
        result = _gui_result(controller.check(self.paths["contract.json"], self.paths["safe-export.json"]))
        destination = self.paths["safe-export.json"].parent / "saved-report.json"
        save_gui_report(destination, result, "json")
        saved = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "pass")
        self.assertNotIn("TCANARY", destination.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
