"""project refresh accepts deliberately edited inputs only after validating them."""

import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from corridor_lab.cli import main as cli_main
from corridor_lab.projects import PROJECT_MANIFEST_NAME, load_project, refresh_project
from helpers import make_directory_link, remove_directory_link, route, scenario


def run_cli(*args: object) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli_main([str(arg) for arg in args])
    return code, stdout.getvalue(), stderr.getvalue()


def write_json(path: Path, value: object, *, indent: int | None = None) -> None:
    path.write_text(json.dumps(value, indent=indent), encoding="utf-8", newline="\n")


def make_project(root: Path, *, embedded_routes: bool = True) -> Path:
    project = root / "project"
    inputs = project / "inputs"
    (inputs / "routes").mkdir(parents=True)
    embedded = [route("fictional-a"), route("fictional-b")] if embedded_routes else None
    write_json(inputs / "scenario.json", scenario(routes=embedded))
    write_json(inputs / "routes" / "c.json", route("fictional-c"))
    write_json(inputs / "baseline.json", scenario(routes=[route("fictional-a")]))
    write_json(inputs / "alt.json", scenario(routes=[route("fictional-a")]))
    code, _, stderr = run_cli("project", "create", "--directory", project, "--project-id", "fictional-refresh",
                              "--scenario", inputs / "scenario.json", "--routes", inputs / "routes",
                              "--baseline", inputs / "baseline.json", "--variant", f"alt={inputs / 'alt.json'}",
                              "--experiment", "dl:deadline-target:probability=0.5")
    assert code == 0, stderr
    route_id = "fictional-a" if embedded_routes else "fictional-c"
    code, _, stderr = run_cli("project", "add-variant", project, "--variant", "cheap",
                              "--changes", f"route.{route_id}.fixed_fee_send=0.5")
    assert code == 0, stderr
    return project


def manifest_without_digests(project: Path) -> dict:
    document = json.loads((project / PROJECT_MANIFEST_NAME).read_text(encoding="utf-8"))
    for key in ("scenario", "routes", "baseline"):
        if key in document:
            document[key].pop("sha256")
    for ref in document.get("variants", {}).values():
        ref.pop("sha256", None)
    return document


class RefreshCliTests(unittest.TestCase):
    def test_an_edited_input_is_refused_until_refreshed(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            scenario_path = project / "inputs" / "scenario.json"
            before = manifest_without_digests(project)
            write_json(scenario_path, json.loads(scenario_path.read_text(encoding="utf-8")), indent=2)
            code, _, stderr = run_cli("project", "validate", project)
            self.assertEqual(code, 2)
            self.assertIn("changed since the project was saved", stderr)
            code, stdout, stderr = run_cli("project", "refresh", project, "--input", "scenario")
            self.assertEqual(code, 0, stderr)
            self.assertRegex(stdout, r"^scenario: inputs/scenario\.json refreshed \([0-9a-f]{12} -> [0-9a-f]{12}\)\n")
            self.assertIn("manifest updated:", stdout)
            self.assertEqual(run_cli("project", "validate", project)[0], 0)
            self.assertEqual(manifest_without_digests(project), before)
            self.assertEqual(run_cli("project", "run", project)[0], 0)

    def test_an_unchanged_input_reports_unchanged_and_keeps_the_manifest_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            manifest_path = project / PROJECT_MANIFEST_NAME
            before = manifest_path.read_bytes()
            code, stdout, stderr = run_cli("project", "refresh", project, "--input", "scenario", "--input", "routes")
            self.assertEqual(code, 0, stderr)
            self.assertEqual(stdout, "scenario: inputs/scenario.json unchanged\nroutes: inputs/routes unchanged\n")
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_an_input_that_fails_its_validator_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            manifest_path = project / PROJECT_MANIFEST_NAME
            before = manifest_path.read_bytes()
            broken = scenario(routes=[route("fictional-a")])
            broken["fictional"] = False
            write_json(project / "inputs" / "scenario.json", broken)
            code, stdout, stderr = run_cli("project", "refresh", project, "--input", "scenario")
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn("scenario: inputs/scenario.json does not validate", stderr)
            self.assertIn("manifest left unchanged", stderr)
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_an_unnamed_modified_input_blocks_the_refresh_and_is_named(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            manifest_path = project / PROJECT_MANIFEST_NAME
            before = manifest_path.read_bytes()
            for name in ("scenario.json", "baseline.json"):
                path = project / "inputs" / name
                write_json(path, json.loads(path.read_text(encoding="utf-8")), indent=2)
            code, _, stderr = run_cli("project", "refresh", project, "--input", "scenario")
            self.assertEqual(code, 2)
            self.assertIn("baseline: inputs/baseline.json changed since the project was saved", stderr)
            self.assertNotIn("scenario:", stderr)
            self.assertEqual(manifest_path.read_bytes(), before)
            code, _, stderr = run_cli("project", "refresh", project, "--input", "scenario", "--input", "baseline")
            self.assertEqual(code, 0, stderr)
            self.assertEqual(run_cli("project", "validate", project)[0], 0)

    def test_unknown_undeclared_and_repeated_labels_exit_2(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            manifest_path = project / PROJECT_MANIFEST_NAME
            before = manifest_path.read_bytes()
            for labels, message in (
                (("contract",), "unknown refresh input label"),
                (("variant:",), "unknown refresh input label"),
                (("variant:missing",), "declares no such input"),
                (("variant:cheap",), "derived variant"),
                (("scenario", "scenario"), "repeated"),
            ):
                with self.subTest(labels=labels):
                    arguments = [part for label in labels for part in ("--input", label)]
                    code, _, stderr = run_cli("project", "refresh", project, *arguments)
                    self.assertEqual(code, 2)
                    self.assertIn(message, stderr)
                    self.assertEqual(manifest_path.read_bytes(), before)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "bare"
            project.mkdir()
            write_json(project / "s.json", scenario(routes=[route()]))
            self.assertEqual(run_cli("project", "create", "--directory", project, "--project-id", "bare",
                                     "--scenario", project / "s.json")[0], 0)
            for label in ("routes", "baseline"):
                code, _, stderr = run_cli("project", "refresh", project, "--input", label)
                self.assertEqual(code, 2)
                self.assertIn(f"{label}: the project manifest declares no such input", stderr)

    def test_a_file_variant_and_a_missing_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            alt = project / "inputs" / "alt.json"
            write_json(alt, scenario(routes=[route("fictional-z")]))
            code, stdout, stderr = run_cli("project", "refresh", project, "--input", "variant:alt")
            self.assertEqual(code, 0, stderr)
            self.assertIn("variant:alt: inputs/alt.json refreshed", stdout)
            alt.unlink()
            before = (project / PROJECT_MANIFEST_NAME).read_bytes()
            code, _, stderr = run_cli("project", "refresh", project, "--input", "variant:alt")
            self.assertEqual(code, 2)
            self.assertIn("variant:alt: missing input inputs/alt.json", stderr)
            self.assertEqual((project / PROJECT_MANIFEST_NAME).read_bytes(), before)

    def test_a_scenario_edit_that_breaks_a_derived_variant_refreshes_with_a_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            # The cheap variant changes fictional-a; drop that route.
            write_json(project / "inputs" / "scenario.json", scenario(routes=[route("fictional-b")]))
            code, stdout, stderr = run_cli("project", "refresh", project, "--input", "scenario")
            self.assertEqual(code, 0, stderr)
            self.assertIn("refreshed", stdout)
            self.assertIn("warning: variant cheap no longer applies to the refreshed scenario", stderr)
            self.assertEqual(run_cli("project", "validate", project)[0], 0)

    def test_a_routes_refresh_rechecks_the_merged_scenario(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary), embedded_routes=False)
            manifest_path = project / PROJECT_MANIFEST_NAME
            before = manifest_path.read_bytes()
            write_json(project / "inputs" / "routes" / "d.json", route("fictional-c"))
            code, _, stderr = run_cli("project", "refresh", project, "--input", "routes")
            self.assertEqual(code, 2)
            self.assertIn("duplicate route_id", stderr)
            self.assertEqual(manifest_path.read_bytes(), before)
            write_json(project / "inputs" / "routes" / "d.json", route("fictional-d"))
            code, stdout, stderr = run_cli("project", "refresh", project, "--input", "routes")
            self.assertEqual(code, 0, stderr)
            self.assertIn("routes: inputs/routes refreshed", stdout)
            code, stdout, _ = run_cli("project", "compare-variants", project, "--format", "json")
            self.assertEqual(code, 0)
            self.assertEqual({row["route_id"] for row in json.loads(stdout)["rows"]}, {"fictional-c", "fictional-d"})

    def test_a_named_input_reached_through_a_directory_link_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = make_project(root)
            outside = root / "outside"
            shutil.move(str(project / "inputs"), str(outside))
            if not make_directory_link(project / "inputs", outside):
                self.skipTest("this account can create neither directory symlinks nor junctions")
            try:
                before = (project / PROJECT_MANIFEST_NAME).read_bytes()
                code, _, stderr = run_cli("project", "refresh", project, "--input", "scenario")
                self.assertEqual(code, 2)
                self.assertIn("scenario: inputs/scenario.json resolves outside the project directory", stderr)
                self.assertEqual((project / PROJECT_MANIFEST_NAME).read_bytes(), before)
            finally:
                remove_directory_link(project / "inputs")

    def test_library_result_lists_outcomes_and_never_touches_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            scenario_path = project / "inputs" / "scenario.json"
            write_json(scenario_path, json.loads(scenario_path.read_text(encoding="utf-8")), indent=4)
            edited = scenario_path.read_bytes()
            result = refresh_project(project, ["scenario"])
            self.assertEqual(result.problems, ())
            self.assertTrue(result.written)
            self.assertEqual([outcome.label for outcome in result.outcomes], ["scenario"])
            self.assertTrue(result.outcomes[0].changed)
            self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", result.outcomes[0].new_sha256))
            self.assertEqual(scenario_path.read_bytes(), edited)
            self.assertEqual(load_project(project).problems, ())


if __name__ == "__main__":
    unittest.main()
