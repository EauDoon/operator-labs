"""Shared helpers for TraceCanary tests added in the 0.4.0 release."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecanary.cli import main as cli_main  # noqa: E402
from tracecanary.fixture import bundle  # noqa: E402


def run_cli(*args: object) -> tuple[int, str, str]:
    """Run the CLI in-process and return (exit status, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli_main([str(arg) for arg in args])
    return code, stdout.getvalue(), stderr.getvalue()


def write_json(path: Path, value: object, *, indent: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=indent), encoding="utf-8", newline="\n")
    return path


def write_fixture(path: Path, name: str) -> Path:
    """Write one file of the built-in synthetic fixture bundle."""
    return write_json(path, bundle()[name])


def snapshot(directory: Path) -> dict[str, bytes | None]:
    """Every path under ``directory`` with file bytes, for exact before/after comparisons."""
    return {
        path.relative_to(directory).as_posix(): (path.read_bytes() if path.is_file() else None)
        for path in sorted(directory.rglob("*"))
    }


def make_directory_link(link: Path, target: Path) -> bool:
    """Create a directory symlink, or a junction on Windows; False if neither works.

    Some Windows accounts cannot create symlinks, while junctions need no
    privilege, so containment tests cover both kinds of directory link.
    """
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        try:
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
            return True
        except (ImportError, AttributeError, OSError):
            pass
    return False


def remove_directory_link(link: Path) -> None:
    """Remove only the link itself, never the directory it points at."""
    if os.name == "nt":
        os.rmdir(link)
    else:
        os.unlink(link)
