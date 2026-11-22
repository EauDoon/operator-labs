"""Local project creation with overlapping saves and ordinary filesystem changes."""

import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from corridor_lab.canonical import InputError
from corridor_lab.gui_controller import CorridorGuiController
from corridor_lab.projects import (
    PROJECT_MANIFEST_NAME,
    build_manifest,
    load_project,
    prepare_project_directory,
    write_project,
)
from helpers import route, scenario
from test_project_cli_fixes import run_cli, snapshot


class AtomicProjectCreateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.inputs = self.project / "inputs"
        self.manifest = self.project / PROJECT_MANIFEST_NAME
        self.first = self.source("first.json", "first")
        self.second = self.source("second.json", "second")

    def source(self, name, label):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(scenario(routes=[route(f"fictional-{label}")])), encoding="utf-8")
        return path

    def create(self, *extra):
        return run_cli("project", "create", "--directory", self.project, "--project-id", "first",
                       "--scenario", self.first, *extra)

    def test_simultaneous_cli_and_desktop_saves_commit_one_complete_project(self):
        self.inputs.mkdir()
        controller = CorridorGuiController()
        self.assertIsNone(controller.load_scenario_file(self.second).error)
        ready = Barrier(2, timeout=10)
        fsync = os.fsync

        def sync_together(fd):
            fsync(fd)
            ready.wait()

        with patch("os.fsync", sync_together), ThreadPoolExecutor(1) as pool:
            desktop = pool.submit(controller.save_project, self.project, "second")
            code, _, error = self.create()
            desktop_error = desktop.result().error
        self.assertEqual(sorted([code, 2 if desktop_error else 0]), [0, 2])
        self.assertIn("project manifest already exists", error or desktop_error)
        winner = self.first if code == 0 else self.second
        loaded = load_project(self.project)
        self.assertTrue(loaded.ok, loaded.problems)
        self.assertEqual(loaded.manifest.project_id, winner.stem)
        self.assertEqual(snapshot(self.project), {
            PROJECT_MANIFEST_NAME: self.manifest.read_bytes(), "inputs": None,
            f"inputs/{winner.name}": winner.read_bytes(),
        })

    def test_simultaneous_input_copies_with_same_basename_preserve_winners_bytes(self):
        self.inputs.mkdir()
        other = self.source("other/first.json", "other")
        target = self.inputs / self.first.name
        start = Barrier(2, timeout=10)
        checked = Barrier(2, timeout=10)
        exists = Path.exists

        def simultaneous_observation(path):
            observed = exists(path)
            if path == target and not observed:
                # Both callers may legitimately observe an unused name before either opens it.
                checked.wait()
            return observed

        def copy(source):
            start.wait()
            try:
                prepare_project_directory(self.project, source)
            except InputError as exc:
                return str(exc)
            return None

        with patch.object(Path, "exists", simultaneous_observation), ThreadPoolExecutor(2) as pool:
            first, second = pool.map(copy, [self.first, other])
        self.assertEqual([first, second].count(None), 1)
        self.assertIn("project input already exists", first or second)
        self.assertEqual(target.read_bytes(), (self.first if first is None else other).read_bytes())

    def test_simultaneous_input_preparation_can_share_a_new_inputs_directory(self):
        ready = Barrier(2, timeout=10)
        mkdir = Path.mkdir

        def mkdir_together(path, *args, **kwargs):
            if path == self.inputs:
                ready.wait()
            return mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", mkdir_together), ThreadPoolExecutor(2) as pool:
            copies = list(pool.map(lambda source: prepare_project_directory(self.project, source),
                                   [self.first, self.second]))
        for result, source in zip(copies, [self.first, self.second]):
            self.assertEqual(result["scenario"].read_bytes(), source.read_bytes())

    def test_route_file_added_to_new_route_folder_survives_a_collision(self):
        routes = self.root / "routes"
        routes.mkdir()
        (routes / "route.json").write_text(json.dumps(route("fictional-saved")), encoding="utf-8")
        target = self.inputs / "routes" / "route.json"
        other = json.dumps(route("fictional-other")).encode()
        iterdir = Path.iterdir

        def add_route(path):
            if path == routes:
                target.write_bytes(other)
            return iterdir(path)

        with patch.object(Path, "iterdir", add_route):
            code, _, error = self.create("--routes", routes)
        self.assertEqual(code, 2, error)
        self.assertEqual(snapshot(self.project), {"inputs": None, "inputs/routes": None,
                                                  "inputs/routes/route.json": other})

    def test_rollback_preserves_a_replacement_saved_by_an_editor(self):
        target = self.inputs / self.first.name
        replacement = self.second.read_bytes()

        def fail_after_edit(_fd):
            self.second.replace(target)
            raise OSError("simulated sync failure")

        with patch("os.fsync", fail_after_edit):
            code, _, error = self.create()
        self.assertEqual(code, 2, error)
        self.assertEqual(snapshot(self.project), {"inputs": None, "inputs/first.json": replacement})

    def test_rollback_preserves_edits_written_in_place_to_a_copied_input(self):
        target = self.inputs / self.first.name
        edited = self.first.read_bytes() + b"\n"

        def fail_after_edit(_fd):
            target.write_bytes(edited)
            raise OSError("simulated sync failure")

        with patch("os.fsync", fail_after_edit):
            code, _, error = self.create()
        self.assertEqual(code, 2, error)
        self.assertEqual(snapshot(self.project), {"inputs": None, "inputs/first.json": edited})

    def test_existing_manifest_and_notes_survive_a_failed_second_create(self):
        self.manifest.write_bytes(b"existing project bytes\n")
        (self.project / "notes.txt").write_text("keep", encoding="utf-8")
        before = snapshot(self.project)
        code, _, error = self.create()
        self.assertEqual(code, 2)
        self.assertIn("project manifest already exists", error)
        self.assertEqual(snapshot(self.project), before)

    def test_failed_manifest_sync_leaves_no_partial_project_and_retry_succeeds(self):
        def fail_sync(_fd):
            self.assertFalse(self.manifest.exists())
            raise OSError("simulated sync failure")

        with patch("os.fsync", fail_sync):
            code, _, error = self.create()
        self.assertEqual(code, 2)
        self.assertIn("simulated sync failure", error)
        self.assertEqual(snapshot(self.project), {})
        self.assertEqual(self.create()[0], 0)
        self.assertTrue(load_project(self.project).ok)

    def test_explicit_update_keeps_old_manifest_readable_until_publication(self):
        self.assertEqual(self.create()[0], 0)
        before = self.manifest.read_bytes()
        updated = build_manifest(self.project, project_id="updated", scenario=self.inputs / self.first.name)
        fsync = os.fsync

        def observe(fd):
            self.assertEqual(self.manifest.read_bytes(), before)
            fsync(fd)

        with patch("os.fsync", observe):
            write_project(self.manifest, updated, replace=True)
        self.assertEqual(load_project(self.project).manifest.project_id, "updated")

    def test_inside_inputs_stay_in_place_and_repeated_external_sources_are_copied_once(self):
        baseline = self.project / "existing.json"
        baseline.write_bytes(self.second.read_bytes())
        code, _, error = self.create("--baseline", baseline, "--variant", f"again={self.first}")
        self.assertEqual(code, 0, error)
        loaded = load_project(self.project)
        self.assertTrue(loaded.ok, loaded.problems)
        self.assertEqual(loaded.resolved["scenario"], loaded.resolved["variant again"])
        self.assertEqual(loaded.resolved["baseline"], baseline)
        self.assertEqual(list(self.inputs.iterdir()), [self.inputs / self.first.name])
        if os.name == "posix":
            self.assertEqual(loaded.resolved["scenario"].stat().st_mode, baseline.stat().st_mode)


if __name__ == "__main__":
    unittest.main()
