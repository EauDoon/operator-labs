"""After Open Project, the desktop campaign runs what `campaign run PROJECT` runs."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from support import run_cli, write_fixture
from tracecanary.gui_controller import ProjectPaths, TraceCanaryController


def _project(root: Path, *extra: str) -> Path:
    sources = root / "sources"
    contract = write_fixture(sources / "contract.json", "contract.json")
    safe = write_fixture(sources / "safe.json", "safe-export.json")
    candidate = write_fixture(sources / "candidate.json", "missing-operational-fields.json")
    write_fixture(sources / "exports" / "safe.json", "safe-export.json")
    write_fixture(sources / "exports" / "sparse.json", "sparse-retention.json")
    project = root / "project"
    project.mkdir()
    code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-desktop",
                              "--contract", contract, "--input", safe, "--candidate", candidate,
                              "--batch-dir", sources / "exports", *extra)
    assert code == 0, stderr
    return project


def _shape(campaign: dict) -> dict:
    """What must agree between the desktop and the CLI; candidate labels legitimately differ."""
    return {
        "status": campaign["status"],
        "coverage": campaign["coverage"],
        "phases": {name: (phase["status"], phase.get("mode"), phase.get("statuses")) for name, phase in campaign["phases"].items()},
    }


class ProjectCampaignControllerTests(unittest.TestCase):
    def test_project_paths_keep_older_call_sites_working(self):
        paths = ProjectPaths(Path("c.json"), None, None, None, None, ("", "", None))
        self.assertIsNone(paths.batch_minimum_ratio)

    def test_open_project_reports_the_saved_batch_ratio(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = _project(Path(temporary), "--batch-minimum-ratio", "1")
            result = TraceCanaryController().open_project(project)
            self.assertEqual(result.project_paths.batch_minimum_ratio, "1")
            self.assertEqual(result.project_paths.coverage, ("", "", None))

    def test_the_batch_ratio_reaches_the_campaign_and_matches_the_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = _project(Path(temporary), "--batch-minimum-ratio", "1")
            paths = TraceCanaryController().open_project(project).project_paths
            result = TraceCanaryController().run_campaign_selections(
                contract_path=paths.contract,
                input_path=paths.input,
                baseline_path=None,
                candidate_path=paths.candidate,
                batch_path=paths.batch_dir,
                batch_minimum_ratio=paths.batch_minimum_ratio,
            )
            code, stdout, _ = run_cli("campaign", "run", project)
            self.assertEqual(result.exit_code, code)
            self.assertEqual(_shape(json.loads(result.json)), _shape(json.loads(stdout)))
            self.assertEqual(json.loads(result.json)["coverage"]["batch_minimum_ratio"], "1")


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
class ProjectCampaignWindowTests(unittest.TestCase):
    def _run_window_campaign(self, project: Path) -> tuple[dict, dict]:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        from tracecanary.gui import TraceCanaryWindow

        filedialog.askopenfilename = lambda *a, **k: str(project / "tracecanary.project.json")
        filedialog.askdirectory = lambda *a, **k: ""
        filedialog.asksaveasfilename = lambda *a, **k: ""
        messagebox.showerror = lambda *a, **k: None
        root = tk.Tk()
        try:
            window = TraceCanaryWindow(tk, ttk, filedialog, messagebox)
            window._open_project()
            entries = {
                "minimum_ratio": window._minimum_ratio.get(),
                "batch_ratio": window._batch_ratio.get(),
                "population_minimum": window._population_minimum.get(),
            }
            window._campaign()
            deadline = time.monotonic() + 30
            while window._batch_job is not None and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            self.assertIsNone(window._batch_job)
            self.assertEqual(window._result.mode, "campaign")
            return json.loads(window._result.json), entries
        finally:
            root.destroy()

    def test_a_project_without_saved_thresholds_runs_without_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = _project(Path(temporary), "--batch-minimum-ratio", "1")
            desktop, entries = self._run_window_campaign(project)
            self.assertEqual(entries, {"minimum_ratio": "", "batch_ratio": "1", "population_minimum": ""})
            _, stdout, _ = run_cli("campaign", "run", project)
            self.assertEqual(_shape(desktop), _shape(json.loads(stdout)))
            self.assertNotIn("population_gate", desktop["phases"])
            self.assertEqual(desktop["phases"]["candidates"]["mode"], "standalone-check")

    def test_a_project_with_saved_thresholds_runs_with_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = _project(Path(temporary), "--minimum-ratio", "0.5", "--population-scope", "resource",
                               "--population-minimum", "1")
            desktop, entries = self._run_window_campaign(project)
            self.assertEqual(entries, {"minimum_ratio": "0.5", "batch_ratio": "", "population_minimum": "1"})
            _, stdout, _ = run_cli("campaign", "run", project)
            self.assertEqual(_shape(desktop), _shape(json.loads(stdout)))


if __name__ == "__main__":
    unittest.main()
