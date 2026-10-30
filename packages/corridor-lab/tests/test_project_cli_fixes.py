"""Regression tests for project CLI defects fixed in the 0.4.0 release."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from corridor_lab.cli import main as cli_main
from corridor_lab.projects import PROJECT_MANIFEST_NAME
from helpers import route, scenario


def run_cli(*args: object) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli_main([str(arg) for arg in args])
    return code, stdout.getvalue(), stderr.getvalue()


def create_project(root: Path, scenario_value: object, *, variants: dict | None = None) -> Path:
    project = root / "project"
    inputs = project / "inputs"
    inputs.mkdir(parents=True)
    scenario_path = inputs / "scenario.json"
    scenario_path.write_text(json.dumps(scenario_value), encoding="utf-8", newline="\n")
    code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-fixes",
                              "--scenario", scenario_path)
    assert code == 0, stderr
    if variants:
        manifest_path = project / PROJECT_MANIFEST_NAME
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document["variants"] = variants
        manifest_path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    return project


DEADLINE_VARIANT = {"fast": {"base": "scenario", "changes": {"transaction": {"deadline_hours": "1"}}}}


class InvalidProjectScenarioTests(unittest.TestCase):
    def test_variant_commands_exit_2_with_the_validator_message(self):
        incomplete = scenario(routes=[route()])
        del incomplete["contract_version"]
        for label, value in (("list", [1, 2]), ("missing-fields", incomplete)):
            with self.subTest(scenario=label), tempfile.TemporaryDirectory() as temporary:
                project = create_project(Path(temporary), value, variants=DEADLINE_VARIANT)
                manifest_path = project / PROJECT_MANIFEST_NAME
                before = manifest_path.read_bytes()
                for command in (
                    ("project", "show-variant", project, "--variant", "fast"),
                    ("project", "compare-variants", project),
                    ("project", "add-variant", project, "--variant", "slow", "--changes", "transaction.deadline_hours=9"),
                ):
                    with self.subTest(command=command[1]):
                        code, stdout, stderr = run_cli(*command)
                        self.assertEqual(code, 2)
                        self.assertTrue(stderr.startswith("error:"), stderr)
                        self.assertIn("scenario", stderr)
                        self.assertNotIn("Traceback", stderr)
                        self.assertEqual(stdout, "")
                self.assertEqual(manifest_path.read_bytes(), before)


# (CLI --changes text, controller changes, saved?)
CHANGE_TABLE = (
    ("transaction.send_amount=-5", {"transaction": {"send_amount": "-5"}}, False),
    ("route.no-such-route.fixed_fee_send=1", {"routes": {"no-such-route": {"fixed_fee_send": "1"}}}, False),
    ("route.fictional-route.percent_fee_bps=20000", {"routes": {"fictional-route": {"percent_fee_bps": "20000"}}}, False),
    ("transaction.deadline_hours=2", {"transaction": {"deadline_hours": "2"}}, True),
    ("route.fictional-route.fixed_fee_send=2", {"routes": {"fictional-route": {"fixed_fee_send": "2"}}}, True),
)


class AddVariantValidationTests(unittest.TestCase):
    def test_cli_and_desktop_give_the_same_verdict_for_each_change_set(self):
        from corridor_lab.gui_controller import CorridorGuiController

        for text, changes, saved in CHANGE_TABLE:
            with self.subTest(changes=text), tempfile.TemporaryDirectory() as temporary:
                project = create_project(Path(temporary), scenario(routes=[route()]))
                manifest_path = project / PROJECT_MANIFEST_NAME
                before = manifest_path.read_bytes()
                code, stdout, stderr = run_cli("project", "add-variant", project, "--variant", "case", "--changes", text)
                self.assertEqual(code, 0 if saved else 2, stderr)
                if saved:
                    self.assertEqual(stdout, "variant saved: case\n")
                    self.assertEqual(run_cli("project", "compare-variants", project)[0], 0)
                else:
                    self.assertEqual(manifest_path.read_bytes(), before)
                    self.assertNotIn("Traceback", stderr)
                controller = CorridorGuiController()
                self.assertIsNone(controller.load_scenario_file(project / "inputs" / "scenario.json").error)
                verdict = controller.add_variant("case", changes)
                self.assertEqual(verdict.error is None, saved, verdict.error)

    def test_a_chain_over_a_base_that_cannot_materialize_is_refused(self):
        broken = {"broken": {"base": "scenario", "changes": {"routes": {"no-such-route": {"fixed_fee_send": "1"}}}}}
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary), scenario(routes=[route()]), variants=broken)
            manifest_path = project / PROJECT_MANIFEST_NAME
            before = manifest_path.read_bytes()
            code, _, stderr = run_cli("project", "add-variant", project, "--variant", "child", "--base", "broken",
                                      "--changes", "transaction.deadline_hours=2")
            self.assertEqual(code, 2)
            self.assertIn("no route no-such-route", stderr)
            self.assertEqual(manifest_path.read_bytes(), before)


def snapshot(directory: Path) -> dict[str, bytes | None]:
    """Every path under ``directory`` with file bytes, so a rollback can be compared exactly."""
    return {
        path.relative_to(directory).as_posix(): (path.read_bytes() if path.is_file() else None)
        for path in sorted(directory.rglob("*"))
    }


class FailedCreateRollbackTests(unittest.TestCase):
    def _sources(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        other = root / "other"
        source.mkdir()
        other.mkdir()
        (source / "s.json").write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8", newline="\n")
        (other / "s.json").write_text(json.dumps(scenario(routes=[route("fictional-other")])), encoding="utf-8", newline="\n")
        (source / "routes").mkdir()
        (source / "routes" / "r.json").write_text(json.dumps(route("fictional-saved")), encoding="utf-8", newline="\n")
        return source, other

    def test_every_failed_create_leaves_the_directory_as_it_was_and_a_retry_works(self):
        long_description = "x" * 201
        cases = (
            ("bad id", ("--project-id", "bad id!")),
            ("duplicate experiments", ("--experiment", "one:deadline-target:probability=0.5",
                                       "--experiment", "one:deadline-target:probability=0.6")),
            ("long description", ("--description", long_description)),
            ("colliding names", ("--baseline", "OTHER")),
            ("bad variant name", ("--variant", "bad name!=SCENARIO")),
        )
        for label, extra in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, other = self._sources(root)
                project = root / "project"
                (project / "inputs").mkdir(parents=True)
                (project / "inputs" / "notes.txt").write_text("kept", encoding="utf-8")
                before = snapshot(project)
                arguments = [str(other / "s.json") if item == "OTHER" else item.replace("SCENARIO", str(source / "s.json"))
                             for item in extra]
                base = ["project", "create", "--directory", project, "--scenario", source / "s.json",
                        "--routes", source / "routes"]
                if "--project-id" not in arguments:
                    base += ["--project-id", "fictional-retry"]
                code, _, stderr = run_cli(*base, *arguments)
                self.assertEqual(code, 2, stderr)
                self.assertNotIn("Traceback", stderr)
                self.assertEqual(snapshot(project), before)
                code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-retry",
                                          "--scenario", source / "s.json", "--routes", source / "routes")
                self.assertEqual(code, 0, stderr)
                self.assertEqual(run_cli("project", "validate", project)[0], 0)
                self.assertEqual((project / "inputs" / "notes.txt").read_text(encoding="utf-8"), "kept")

    def test_a_failed_create_removes_an_inputs_folder_it_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, _ = self._sources(root)
            project = root / "project"
            project.mkdir()
            code, _, _ = run_cli("project", "create", "--directory", project, "--project-id", "bad id!",
                                 "--scenario", source / "s.json", "--routes", source / "routes")
            self.assertEqual(code, 2)
            self.assertEqual(snapshot(project), {})

    def test_inputs_already_inside_the_project_are_never_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            (project / "inputs").mkdir(parents=True)
            (project / "inputs" / "s.json").write_text(json.dumps(scenario(routes=[route()])), encoding="utf-8", newline="\n")
            before = snapshot(project)
            code, _, _ = run_cli("project", "create", "--directory", project, "--project-id", "bad id!",
                                 "--scenario", project / "inputs" / "s.json")
            self.assertEqual(code, 2)
            self.assertEqual(snapshot(project), before)

    def test_a_failed_desktop_save_project_rolls_back_too(self):
        from corridor_lab.gui_controller import CorridorGuiController

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, other = self._sources(root)
            project = root / "project"
            project.mkdir()
            controller = CorridorGuiController()
            self.assertIsNone(controller.load_scenario_file(source / "s.json").error)
            self.assertIsNone(controller.load_routes_path(source / "routes").error)
            result = controller.save_project(project, "bad id!")
            self.assertIsNotNone(result.error)
            self.assertEqual(snapshot(project), {})
            controller.baseline_file = other / "s.json"
            result = controller.save_project(project, "fictional-desktop")
            self.assertIsNotNone(result.error)
            self.assertEqual(snapshot(project), {})
            controller.baseline_file = None
            self.assertIsNone(controller.save_project(project, "fictional-desktop").error)
            self.assertEqual(run_cli("project", "validate", project)[0], 0)


class ShowVariantFormatTests(unittest.TestCase):
    def test_output_suffix_chooses_the_format_unless_format_is_explicit(self):
        import os
        from unittest import mock

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create_project(root, scenario(routes=[route()]), variants=DEADLINE_VARIANT)
            show = ("project", "show-variant", project, "--variant", "fast")
            with mock.patch.dict(os.environ, {"CORRIDOR_LAB_FORMAT": "json"}):
                cases = (
                    ("tight.json", (), "json"),
                    ("tight.JSON", (), "json"),
                    ("tight.md", (), "markdown"),
                    ("tight.markdown", (), "markdown"),
                    ("tight.txt", (), "markdown"),
                    ("tight.csv", (), "markdown"),
                    ("forced.json", ("--format", "markdown"), "markdown"),
                    ("forced.md", ("--format", "json"), "json"),
                )
                for name, extra, expected in cases:
                    with self.subTest(output=name, extra=extra):
                        target = root / name
                        code, _, stderr = run_cli(*show, "--output", target, *extra)
                        self.assertEqual(code, 0, stderr)
                        text = target.read_text(encoding="utf-8")
                        if expected == "json":
                            self.assertEqual(json.loads(text)["analysis"], "variant-assumption-diff")
                        else:
                            self.assertTrue(text.startswith("# Corridor Lab report"), text[:40])
                code, stdout, _ = run_cli(*show)
                self.assertEqual(code, 0)
                self.assertTrue(stdout.startswith("# Corridor Lab report"))


if __name__ == "__main__":
    unittest.main()
