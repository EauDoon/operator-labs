"""Run with an installed wheel: python -I tests/installed_journey.py."""
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import corridor_lab


def check_installed_version():
    """The distribution metadata and the installed console script agree with __version__."""
    assert importlib.metadata.version("corridor-lab") == corridor_lab.__version__
    script = Path(sys.executable).parent / ("corridorlab.exe" if os.name == "nt" else "corridorlab")
    assert script.is_file(), script
    result = subprocess.run([str(script), "--version"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"corridorlab {corridor_lab.__version__}", result.stdout


def main():
    assert Path(corridor_lab.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    check_installed_version()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        def run(*args, expected=0):
            result = subprocess.run([sys.executable, "-I", "-m", "corridor_lab", *map(str, args)],
                                    cwd=root, capture_output=True, text=True, timeout=30)
            assert result.returncode == expected, result.stdout + result.stderr
            return result.stdout

        project = root / "project"
        project.mkdir()
        scenario = project / "scenario.json"
        run("init", "--output", scenario)
        run("project", "create", "--directory", project, "--project-id", "fictional-installed",
            "--scenario", scenario, "--experiment", "deadlines:transaction-sweep:parameter=deadline_hours;values=1,24")
        run("project", "add-variant", project, "--variant", "fast", "--changes", "transaction.deadline_hours=1")
        run("project", "add-variant", project, "--variant", "busy", "--base", "fast",
            "--changes", "transaction.volume_per_period=100")
        before = run("project", "run-variants", project, "--experiment", "deadlines", "--format", "json")
        moved = root / "moved"
        project.rename(moved)
        run("project", "validate", moved)
        run("project", "open", moved)
        assert run("project", "run-variants", moved, "--experiment", "deadlines", "--format", "json") == before
        scenario = moved / "scenario.json"
        original = scenario.read_bytes()
        evidence = root / "evidence.json"
        run("evaluate", scenario, "--evidence", evidence)
        assert json.loads(evidence.read_text(encoding="utf-8"))["tool"]["version"] == corridor_lab.__version__
        saved_evidence = evidence.read_bytes()
        run("evaluate", scenario, "--output", evidence, "--evidence", evidence, expected=2)
        assert evidence.read_bytes() == saved_evidence
        run("evaluate", scenario, "--output", scenario, expected=2)
        assert scenario.read_bytes() == original
        scenario.write_bytes(original + b"\n")
        run("project", "validate", moved, expected=2)
        assert "refreshed" in run("project", "refresh", moved, "--input", "scenario")
        run("project", "validate", moved)
        check_saved_routes_journey(root, run)
    print("INSTALLED_CORRIDOR_JOURNEY_OK")


def check_saved_routes_journey(root, run):
    """A project whose routes sit beside the scenario, as in examples/fictional-corridor."""
    layout = root / "layout"
    (layout / "routes").mkdir(parents=True)
    starter = root / "starter.json"
    run("init", "--output", starter)
    document = json.loads(starter.read_text(encoding="utf-8"))
    for item in document.pop("routes"):
        (layout / "routes" / f"{item['route_id']}.json").write_text(json.dumps(item), encoding="utf-8")
    scenario = layout / "scenario.json"
    scenario.write_text(json.dumps(document), encoding="utf-8")
    run("project", "create", "--directory", layout, "--project-id", "fictional-layout", "--scenario", scenario,
        "--routes", layout / "routes", "--experiment", "target:deadline-target:probability=0.5")
    evidence = root / "layout-evidence.json"
    report = json.loads(run("project", "run", layout, "--format", "json", "--evidence", evidence))
    assert report["status"] == "pass", report
    recorded = json.loads(evidence.read_text(encoding="utf-8"))
    assert recorded["inputs"]["routes"] == "routes", recorded["inputs"]
    assert [item["label"] for item in recorded["inputs"]["project_inputs"]] == ["routes", "scenario"]
    run("project", "compare-variants", layout, "--format", "json")
    run("project", "run", layout, "--evidence", layout / "inside.json", expected=2)
    assert not (layout / "inside.json").exists()


if __name__ == "__main__":
    main()
