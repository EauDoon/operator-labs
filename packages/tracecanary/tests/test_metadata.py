from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MetadataTests(unittest.TestCase):
    def test_gui_entrypoint_and_public_urls_are_declared(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(project["version"], "0.1.1")
        self.assertEqual(project["gui-scripts"]["tracecanary-gui"], "tracecanary.gui:main")
        self.assertEqual(
            project["urls"],
            {
                "Source": "https://github.com/EauDoon/operator-labs/tree/main/packages/tracecanary",
                "Issues": "https://github.com/EauDoon/operator-labs/issues",
                "Security": "https://github.com/EauDoon/operator-labs/blob/main/packages/tracecanary/SECURITY.md",
                "Documentation": "https://github.com/EauDoon/operator-labs/tree/main/packages/tracecanary#readme",
            },
        )
