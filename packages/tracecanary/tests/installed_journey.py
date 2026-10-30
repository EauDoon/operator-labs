"""Run with an installed wheel: python -I tests/installed_journey.py."""
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import tracecanary
from tracecanary.fixture import bundle
from tracecanary.gui_controller import TraceCanaryController


def check_installed_version():
    """The distribution metadata and the installed console script agree with __version__."""
    assert importlib.metadata.version("tracecanary") == tracecanary.__version__
    script = Path(sys.executable).parent / ("tracecanary.exe" if os.name == "nt" else "tracecanary")
    assert script.is_file(), script
    result = subprocess.run([str(script), "--version"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"tracecanary {tracecanary.__version__}", result.stdout


def main():
    assert Path(tracecanary.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    check_installed_version()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fixtures = root / "fixtures"
        fixtures.mkdir()
        files = bundle()
        protected = [item["value"] for item in files["contract.json"]["canaries"]]
        for name, payload in files.items():
            (fixtures / name).write_text(json.dumps(payload), encoding="utf-8")

        def run(*args, expected=0):
            result = subprocess.run([sys.executable, "-I", "-m", "tracecanary", *map(str, args)],
                                    cwd=root, capture_output=True, text=True, timeout=30)
            assert result.returncode == expected, result.stdout + result.stderr
            assert all(value not in result.stdout + result.stderr for value in protected)
            return result.stdout

        summaries = []
        for index, (candidate, status) in enumerate((("safe-export.json", 0), ("leaked-prompt.json", 1), ("invalid-export.json", 2))):
            project = root / f"project-{index}"
            project.mkdir()
            run("project", "create", "--directory", project, "--project-id", f"fictional-{index}",
                "--contract", fixtures / "contract.json", "--baseline", fixtures / "safe-export.json",
                "--candidate", fixtures / candidate)
            summary = root / f"summary-{index}.json"
            run("campaign", "run", project, "--save-summary", summary, expected=status)
            original = summary.read_text(encoding="utf-8")
            assert all(value not in original for value in protected)
            moved = root / f"moved-{index}"
            project.rename(moved)
            run("project", "validate", moved)
            run("project", "open", moved)
            run("campaign", "run", moved, "--save-summary", summary, expected=status)
            assert summary.read_text(encoding="utf-8") == original
            summaries.append(summary)
        comparison = json.loads(run("campaign", "compare", *summaries[:2], "--format", "json"))
        assert comparison["campaign_status_change"] == ["pass", "regression"]
        assert "Gate: REGRESSION" in run("campaign", "compare", *summaries[:2], "--fail-on-regression", expected=1)
        run("campaign", "compare", summaries[0], summaries[0], "--fail-on-regression")
        run("campaign", "compare", summaries[0], summaries[2], "--fail-on-regression", expected=2)
        for summary in summaries[:2]:
            original = summary.read_bytes()
            run("campaign", "compare", *summaries[:2], "--output", summary, expected=2)
            assert summary.read_bytes() == original
        batch = root / "batch"
        batch.mkdir()
        (batch / "safe.json").write_bytes((fixtures / "safe-export.json").read_bytes())
        run("campaign", "run", root / "moved-0", "--input-dir", batch,
            "--save-summary", batch / "summary.json", expected=2)
        assert not (batch / "summary.json").exists()
        human = root / "campaign.txt"
        cli_evidence = root / "cli-evidence.json"
        confirmation = run("campaign", "run", root / "moved-1", "--format", "human", "--output", human,
                           "--save-evidence", cli_evidence, expected=1)
        assert confirmation == f"Value-free evidence saved to {cli_evidence}\n", confirmation
        assert human.read_text(encoding="utf-8").startswith("TraceCanary campaign: REGRESSION")
        assert json.loads(cli_evidence.read_text(encoding="utf-8"))["evidence_version"] == "tracecanary.evidence/v1"
        assert all(value not in cli_evidence.read_text(encoding="utf-8") for value in protected)
        run("campaign", "run", root / "moved-1", "--save-evidence", root / "moved-1" / "evidence.json", expected=2)
        assert not (root / "moved-1" / "evidence.json").exists()
        controller = TraceCanaryController()
        campaign = controller.run_campaign_selections(contract_path=fixtures / "contract.json",
            input_path=fixtures / "leaked-prompt.json", baseline_path=fixtures / "safe-export.json", batch_path=None)
        evidence = root / "evidence.json"
        assert controller.save_campaign_evidence(evidence, campaign).status == "pass"
        assert all(value not in evidence.read_text(encoding="utf-8") for value in protected)
        contract = fixtures / "contract.json"
        original = contract.read_bytes()
        assert controller.save_campaign_evidence(contract, campaign).status == "unresolved"
        assert contract.read_bytes() == original
        (root / "moved-0" / "inputs" / "safe-export.json").write_text("{}", encoding="utf-8")
        run("project", "validate", root / "moved-0", expected=2)
    print("INSTALLED_TRACECANARY_JOURNEY_OK")


if __name__ == "__main__":
    main()
