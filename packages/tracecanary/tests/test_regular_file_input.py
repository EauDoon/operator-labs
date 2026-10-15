from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.canonical import InputError, load_json


class RegularFileInputTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX named pipes")
    def test_fifo_without_writer_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            os.mkfifo(path)
            source = (
                "import sys; from pathlib import Path; "
                "from tracecanary.canonical import InputError, load_json; "
                "path = Path(sys.argv[1]);\n"
                "try:\n    load_json(path, max_bytes=1024, max_depth=10)\n"
                "except InputError as error:\n"
                "    assert 'regular file' in str(error), str(error)\n"
                "else:\n    raise AssertionError('accepted a FIFO')\n"
            )
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
            result = subprocess.run(
                [sys.executable, "-c", source, str(path)],
                capture_output=True, text=True, env=env, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_descriptor_type_is_checked_even_when_path_looks_regular(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text('{}', encoding="utf-8")
            # Models a file swapped after a path-based metadata check.
            with patch("tracecanary.canonical.os.fstat") as fstat:
                fstat.return_value.st_mode = 0o010600  # FIFO
                with self.assertRaisesRegex(InputError, "regular file"):
                    load_json(path, max_bytes=1024, max_depth=10)

    def test_regular_file_and_symlink_target_remain_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text('{"text":"café"}', encoding="utf-8")
            self.assertEqual(load_json(path, max_bytes=1024, max_depth=10), {"text": "café"})
            link = Path(directory) / "linked.json"
            try:
                link.symlink_to(path)
            except (OSError, NotImplementedError):
                return  # Windows may require privileges to create symlinks.
            path = link
            self.assertEqual(load_json(path, max_bytes=1024, max_depth=10), {"text": "café"})

    @unittest.skipUnless(os.name == "posix", "requires POSIX device files")
    def test_character_device_is_rejected(self):
        path = Path(os.devnull)
        with self.assertRaisesRegex(InputError, "regular file"):
            load_json(path, max_bytes=1024, max_depth=10)
