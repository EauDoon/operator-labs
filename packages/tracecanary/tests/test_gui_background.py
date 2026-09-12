import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.fixture import bundle
from tracecanary.gui import BackgroundBatch, TraceCanaryWindow
from tracecanary.gui_controller import GuiResult


def _write_bundle(root: Path) -> None:
    for name, data in bundle().items():
        (root / name).write_text(json.dumps(data), encoding="utf-8", newline="\n")


class BackgroundBatchTests(unittest.TestCase):
    def test_finished_transitions_and_result_passes_through(self):
        holder = {}

        def operation():
            holder["started"] = True
            time.sleep(0.05)
            return GuiResult("pass", 0, "ok", "{}")

        job = BackgroundBatch(operation)
        self.assertFalse(job.finished())
        job.start()
        self.assertTrue(holder.get("started", False))
        deadline = time.monotonic() + 5
        while not job.finished() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(job.finished())
        self.assertEqual(job.result.status, "pass")
        self.assertIsNone(job.error)

    def test_worker_exception_becomes_error_without_touching_widgets(self):
        job = BackgroundBatch(lambda: (_ for _ in ()).throw(RuntimeError("bounded failure")))
        job.start()
        deadline = time.monotonic() + 5
        while not job.finished() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(job.finished())
        self.assertIsNone(job.result)
        self.assertEqual(job.error, "bounded failure")


def _display_available() -> bool:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


@unittest.skipUnless(_display_available(), "no interactive display is available for Tk window tests")
class BatchWindowBackgroundTests(unittest.TestCase):
    def test_batch_runs_in_background_and_applies_result_on_the_main_thread(self):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        filedialog.askopenfilename = lambda *a, **k: ""
        filedialog.askdirectory = lambda *a, **k: ""
        filedialog.asksaveasfilename = lambda *a, **k: ""
        messagebox.showerror = lambda *a, **k: None

        with tempfile.TemporaryDirectory() as temporary:
            root_path = Path(temporary)
            _write_bundle(root_path)
            root = tk.Tk()
            window = TraceCanaryWindow(tk, ttk, filedialog, messagebox)
            window._contract.set(str(root_path / "contract.json"))
            window._batch_dir.set(str(root_path))
            window._include_paths.set(True)
            window._batch()
            self.assertIsNotNone(window._batch_job)
            self.assertEqual(str(window._batch_button.cget("state")), "disabled")
            deadline = time.monotonic() + 30
            while window._status.get() != "Status: UNRESOLVED (exit 2)" and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            self.assertEqual(window._status.get(), "Status: UNRESOLVED (exit 2)")
            self.assertIsNone(window._batch_job)
            self.assertEqual(str(window._batch_button.cget("state")), "normal")
            report = json.loads(window._result.json)
            self.assertEqual({item["status"] for item in report["items"]}, {"pass", "regression", "unresolved"})
            self.assertTrue(all(item.get("path", "").endswith(".json") for item in report["items"]))
            root.destroy()


if __name__ == "__main__":
    unittest.main()
