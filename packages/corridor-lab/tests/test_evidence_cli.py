import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import corridor_lab
from corridor_lab.cli import main
from helpers import route, scenario

PACKAGE = Path(__file__).resolve().parents[1]
FIXTURE = PACKAGE / "examples" / "fictional-corridor" / "embedded-scenario.json"


class EvidenceCliTests(unittest.TestCase):
    def test_report_and_evidence_cannot_share_a_destination(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            output = Path(temporary) / "report.json"
            args = ["evaluate", str(FIXTURE), "--output", str(output), "--evidence", str(output)]
            self.assertEqual(main(args), 2)
            self.assertFalse(output.exists())
            output.write_text("previous report", encoding="utf-8")
            self.assertEqual(main(args), 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous report")

    def test_evidence_accompanies_a_report_and_explains_itself(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(temporary)
            scenario_path = root / "scenario.json"
            scenario_path.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            report = root / "report.json"
            evidence = root / "evidence.json"
            self.assertEqual(main(["evaluate", str(scenario_path), "--format", "json", "--output", str(report),
                                   "--evidence", str(evidence)]), 0)
            document = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(document["evidence_version"], "corridor-lab.evidence/v1")
            self.assertEqual(document["report"], json.loads(report.read_text(encoding="utf-8")))
            self.assertEqual(document["inputs"]["scenario"], str(scenario_path))
            self.assertIn("declared fiction", document["limitations"])
            # evidence cannot replace the scenario input
            self.assertEqual(main(["evaluate", str(scenario_path), "--evidence", str(scenario_path)]), 2)
            # report still written normally when evidence is absent
            self.assertEqual(main(["evaluate", str(scenario_path), "--output", str(root / "plain.json")]), 0)
            self.assertTrue((root / "plain.json").exists())

    def test_batch_and_robustness_evidence_export(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(temporary)
            portfolio = root / "portfolio"
            portfolio.mkdir()
            (portfolio / "one.json").write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            evidence = root / "batch-evidence.json"
            self.assertEqual(main(["batch", str(portfolio), "--evidence", str(evidence)]), 0)
            document = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(document["analysis"], "scenario batch")
            self.assertEqual(main(["batch", str(portfolio), "--evidence", str(portfolio / "inside.json")]), 2)
            self.assertFalse((portfolio / "inside.json").exists())
            first = root / "a.json"
            first.write_text(json.dumps(scenario(routes=[route("fictional-shared")])), encoding="utf-8")
            other = scenario(routes=[route("fictional-shared")])
            other["transaction"]["deadline_hours"] = "0.1"
            other["scenario_id"] = "fictional-strained"
            second = root / "b.json"
            second.write_text(json.dumps(other), encoding="utf-8")
            self.assertEqual(main(["robustness-review", str(first), str(second), "--constraint",
                                   "probability_by_deadline_at_least=0.8", "--evidence", str(root / "rb.json")]), 0)
            robust_document = json.loads((root / "rb.json").read_text(encoding="utf-8"))
            self.assertEqual(robust_document["analysis"], "robustness-review")

    def test_evidence_names_the_inputs_each_command_actually_read(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(temporary)
            portfolio = root / "portfolio"
            portfolio.mkdir()
            (portfolio / "one.json").write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            self.assertEqual(main(["batch", str(portfolio), "--evidence", str(root / "batch.json")]), 0)
            batch_inputs = json.loads((root / "batch.json").read_text(encoding="utf-8"))["inputs"]
            self.assertEqual(batch_inputs["scenario"], f"each JSON scenario in {portfolio}")
            self.assertNotIn("built-in", batch_inputs["scenario"])
            self.assertEqual(batch_inputs["routes"], "routes embedded in each scenario")
            self.assertIsNone(batch_inputs["baseline"])

            first, second = root / "a.json", root / "b.json"
            first.write_text(json.dumps(scenario(routes=[route("fictional-shared")])), encoding="utf-8")
            second.write_text(json.dumps(scenario(routes=[route("fictional-shared")])), encoding="utf-8")
            self.assertEqual(main(["robustness-review", str(first), str(second), "--constraint",
                                   "probability_by_deadline_at_least=0.5", "--evidence", str(root / "rb.json")]), 0)
            robust_inputs = json.loads((root / "rb.json").read_text(encoding="utf-8"))["inputs"]
            self.assertEqual(robust_inputs["scenario"], f"{first}; {second}")

            self.assertEqual(main(["diff", str(second), "--baseline", str(first), "--evidence", str(root / "diff.json")]), 0)
            diff_inputs = json.loads((root / "diff.json").read_text(encoding="utf-8"))["inputs"]
            self.assertEqual(diff_inputs["scenario"], str(second))
            self.assertEqual(diff_inputs["baseline"], str(first))

    def test_evidence_collision_is_refused_before_the_report_is_written(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()) as err:
            root = Path(temporary)
            victim = root / "victim.json"
            victim.write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            before = victim.read_bytes()
            output = root / "out" / "report.json"
            self.assertEqual(main(["evaluate", str(victim), "--output", str(output), "--evidence", str(victim)]), 2)
            self.assertIn("must not replace an input", err.getvalue())
            self.assertFalse(output.exists())
            self.assertFalse(output.parent.exists())
            self.assertEqual(victim.read_bytes(), before)
            portfolio = root / "portfolio"
            portfolio.mkdir()
            (portfolio / "one.json").write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8")
            batch_output = root / "batch.json"
            self.assertEqual(main(["batch", str(portfolio), "--output", str(batch_output),
                                   "--evidence", str(portfolio / "evidence.json")]), 2)
            self.assertFalse(batch_output.exists())

    def test_evidence_reports_the_package_version(self):
        # pyproject reads the same __version__ (test_metadata checks the dynamic attr).
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(temporary)
            evidence = root / "evidence.json"
            self.assertEqual(main(["evaluate", str(FIXTURE), "--evidence", str(evidence)]), 0)
            document = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(document["tool"], {"name": "corridor-lab", "version": corridor_lab.__version__})



def _run(*args: object) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main([str(arg) for arg in args])
    return code, out.getvalue(), err.getvalue()


def _evidence_project(root: Path, *, embedded: bool = True) -> Path:
    project = root / "project"
    inputs = project / "inputs"
    (inputs / "routes").mkdir(parents=True)
    scenario_path = inputs / "scenario.json"
    value = scenario(routes=[route("fictional-embedded")]) if embedded else scenario()
    scenario_path.write_text(json.dumps(value), encoding="utf-8", newline="\n")
    (inputs / "routes" / "saved.json").write_text(json.dumps(route("fictional-saved")), encoding="utf-8", newline="\n")
    (inputs / "baseline.json").write_text(json.dumps(scenario(routes=[route("fictional-embedded")])), encoding="utf-8", newline="\n")
    code, _, err = _run("project", "create", "--directory", project, "--project-id", "fictional-evidence",
                        "--scenario", scenario_path, "--routes", inputs / "routes", "--baseline", inputs / "baseline.json",
                        "--experiment", "dl:deadline-target:probability=0.5")
    assert code == 0, err
    code, _, err = _run("project", "add-variant", project, "--variant", "fast", "--changes", "transaction.deadline_hours=1")
    assert code == 0, err
    return project


PROJECT_COMMANDS = (
    ("run", ("--format", "json")),
    ("run-variants", ("--experiment", "dl", "--format", "json")),
    ("compare-variants", ("--format", "json")),
    ("show-variant", ("--variant", "fast", "--format", "json")),
)


class ProjectEvidenceTests(unittest.TestCase):
    def test_each_project_report_command_writes_evidence_with_verified_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _evidence_project(root)
            manifest = json.loads((project / "corridor-lab.project.json").read_text(encoding="utf-8"))
            expected_inputs = [
                {"label": "baseline", "path": "inputs/baseline.json", "sha256": manifest["baseline"]["sha256"], "folder": False},
                {"label": "routes", "path": "inputs/routes", "sha256": manifest["routes"]["sha256"], "folder": True},
                {"label": "scenario", "path": "inputs/scenario.json", "sha256": manifest["scenario"]["sha256"], "folder": False},
            ]
            for command, extra in PROJECT_COMMANDS:
                with self.subTest(command=command):
                    report_path = root / f"{command}.json"
                    evidence_path = root / f"{command}-evidence.json"
                    code, stdout, err = _run("project", command, project, *extra, "--output", report_path,
                                             "--evidence", evidence_path)
                    self.assertEqual(code, 0, err)
                    self.assertEqual(stdout, "")
                    document = json.loads(evidence_path.read_text(encoding="utf-8"))
                    self.assertEqual(document["report"], json.loads(report_path.read_text(encoding="utf-8")))
                    self.assertEqual(document["inputs"]["project_inputs"], expected_inputs)
                    self.assertEqual(document["inputs"]["scenario"], "inputs/scenario.json")
                    self.assertEqual(document["inputs"]["routes"], "routes embedded in the scenario")
                    self.assertEqual(document["inputs"]["project"], str(project / "corridor-lab.project.json"))
                    self.assertEqual(document["operator_notes"], f"Generated by corridorlab project {command}")
                    # Evidence also works with the report on stdout.
                    code, stdout, err = _run("project", command, project, *extra, "--evidence", root / f"{command}-2.json")
                    self.assertEqual(code, 0, err)
                    self.assertEqual(json.loads((root / f"{command}-2.json").read_text(encoding="utf-8"))["report"],
                                     json.loads(stdout))

    def test_refused_evidence_destinations_write_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _evidence_project(root)
            scenario_path = project / "inputs" / "scenario.json"
            before = scenario_path.read_bytes()
            for command, extra in PROJECT_COMMANDS:
                for label, evidence, output in (
                    ("inside the project", project / "evidence.json", root / "report.json"),
                    ("an input", scenario_path, root / "report.json"),
                    ("the output", root / "same.json", root / "same.json"),
                ):
                    with self.subTest(command=command, destination=label):
                        code, stdout, err = _run("project", command, project, *extra, "--output", output,
                                                 "--evidence", evidence)
                        self.assertEqual(code, 2)
                        self.assertEqual(stdout, "")
                        self.assertNotIn("Traceback", err)
                        self.assertFalse(output.exists())
                        self.assertFalse((project / "evidence.json").exists())
                        self.assertEqual(scenario_path.read_bytes(), before)

    def test_unresolved_run_variants_still_write_evidence_and_exit_2(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _evidence_project(root)
            manifest_path = project / "corridor-lab.project.json"
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            document["variants"]["broken"] = {"base": "scenario", "changes": {"routes": {"no-such-route": {"fixed_fee_send": "1"}}}}
            manifest_path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
            evidence = root / "evidence.json"
            code, stdout, _ = _run("project", "run-variants", project, "--experiment", "dl", "--format", "json",
                                   "--evidence", evidence)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stdout)["status"], "unresolved")
            self.assertEqual(json.loads(evidence.read_text(encoding="utf-8"))["report"]["status"], "unresolved")

    def test_saved_routes_are_named_as_the_routes_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _evidence_project(root, embedded=False)
            evidence = root / "evidence.json"
            code, _, err = _run("project", "run", project, "--format", "json", "--evidence", evidence)
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(evidence.read_text(encoding="utf-8"))["inputs"]["routes"], "inputs/routes")

    def test_desktop_export_after_open_project_includes_project_inputs(self):
        from corridor_lab.gui_controller import CorridorGuiController

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _evidence_project(root)
            controller = CorridorGuiController()
            self.assertIsNone(controller.open_project(project).error)
            self.assertIsNone(controller.run_saved_experiment("dl").error)
            evidence = root / "desktop-evidence.json"
            self.assertIsNone(controller.export_evidence(evidence).error)
            labels = [item["label"] for item in json.loads(evidence.read_text(encoding="utf-8"))["inputs"]["project_inputs"]]
            self.assertEqual(labels, ["baseline", "routes", "scenario"])

    def test_standalone_evidence_bytes_are_unchanged(self):
        from corridor_lab.comparison import evaluate_scenario
        from corridor_lab.evidence import STANDING_LIMITATIONS
        from corridor_lab.gui_controller import CorridorGuiController
        from corridor_lab.scenario import load_scenario

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence.json"
            code, _, err = _run("evaluate", FIXTURE, "--evidence", evidence)
            self.assertEqual(code, 0, err)
            report = json.loads(json.dumps(evaluate_scenario(load_scenario(FIXTURE))))
            golden = {
                "analysis": "route comparison",
                "evidence_version": "corridor-lab.evidence/v1",
                "inputs": {"baseline": None, "project": None, "routes": "routes embedded in the scenario",
                           "scenario": str(FIXTURE)},
                "limitations": STANDING_LIMITATIONS,
                "operator_notes": "Generated by corridorlab evaluate",
                "report": report,
                "tool": {"name": "corridor-lab", "version": corridor_lab.__version__},
            }
            expected = json.dumps(golden, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            self.assertEqual(evidence.read_bytes().decode("utf-8"), expected)
            controller = CorridorGuiController()
            self.assertIsNone(controller.load_scenario_file(FIXTURE).error)
            self.assertIsNone(controller.evaluate().error)
            desktop = root / "desktop.json"
            self.assertIsNone(controller.export_evidence(desktop).error)
            self.assertNotIn("project_inputs", json.loads(desktop.read_text(encoding="utf-8"))["inputs"])


if __name__ == "__main__":
    unittest.main()
