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


if __name__ == "__main__":
    unittest.main()
