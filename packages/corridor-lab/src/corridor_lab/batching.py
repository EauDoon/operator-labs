"""Bounded scenario-batch execution shared by the CLI and the desktop controller."""

from __future__ import annotations

import os
import stat as stat_module
from decimal import DecimalException
from pathlib import Path

from .canonical import (
    MAX_BATCH_SCENARIOS,
    MAX_INPUT_BYTES,
    InputError,
    parse_json_bytes,
)
from .scenario import parse_scenario
from .comparison import evaluate_scenario


def _require_text(value: str, flag: str) -> str:
    text = value.strip()
    if not text:
        raise InputError(f"{flag} must not be empty")
    return text


def read_scanned_scenario(path: Path, expected: os.stat_result):
    """Read the same regular scenario file observed during batch discovery."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat_module.S_ISREG(opened.st_mode) or not os.path.samestat(expected, opened):
            raise InputError("batch input changed while being read")
        with os.fdopen(descriptor, "rb") as scenario_file:
            descriptor = None
            raw = scenario_file.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise InputError("batch input changed while being read") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > MAX_INPUT_BYTES:
        raise InputError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    return parse_scenario(parse_json_bytes(raw))


def _failure_text(exc: BaseException) -> str:
    """Render a diagnostic that keeps the exception type and chained cause."""
    message = str(exc).strip() or type(exc).__name__
    cause = exc.__cause__
    if cause is None:
        return message
    cause_text = str(cause).strip() or type(cause).__name__
    if cause_text in message:
        return message
    return f"{message}: {cause_text}"


def run_scenario_batch(input_dir: str, recursive: bool, include_paths: bool) -> dict[str, object]:
    displayed = Path(_require_text(input_dir, "input_dir"))
    root = displayed.resolve()
    if not root.is_dir():
        raise InputError(f"batch input_dir must be a directory: {displayed}")
    iterator = root.rglob("*") if recursive else root.iterdir()
    paths: list[tuple[Path, os.stat_result]] = []
    over_limit = False
    for path in iterator:
        if len(paths) > MAX_BATCH_SCENARIOS:
            # Stop reading the directory as soon as the budget is exceeded.
            # The full enumeration in the previous implementation allocated
            # a Path, an os.stat_result, and a resolve() syscall per entry
            # before raising, which is hostile to large directories on
            # Windows. Mirror the TraceCanary bound pattern from PR #18.
            over_limit = True
            break
        if not path.name.lower().endswith(".json"):
            continue
        try:
            metadata = os.lstat(path)
        except OSError:
            continue
        if not stat_module.S_ISREG(metadata.st_mode):
            continue
        try:
            if not path.resolve().is_relative_to(root):
                continue
        except OSError:
            continue
        paths.append((path, metadata))
    paths.sort(
        key=lambda entry: (
            entry[0].relative_to(root).as_posix().casefold(),
            entry[0].relative_to(root).as_posix(),
        ),
    )
    if not paths:
        raise InputError(f"batch input_dir contains no JSON scenario files: {displayed}")
    if over_limit or len(paths) > MAX_BATCH_SCENARIOS:
        raise InputError(f"batch exceeds the {MAX_BATCH_SCENARIOS}-scenario budget")
    items: list[dict[str, object]] = []
    for index, (path, metadata) in enumerate(paths, start=1):
        relative = path.relative_to(root).as_posix()
        try:
            report = evaluate_scenario(read_scanned_scenario(path, metadata))
            status = "pass"
        except (InputError, OSError, ValueError, DecimalException) as exc:
            report = {"status": "unresolved", "error": f"{relative}: {_failure_text(exc)}"}
            status = "unresolved"
        item: dict[str, object] = {"id": f"scenario-{index:04d}", "status": status, "report": report}
        if include_paths:
            item["path"] = relative
        items.append(item)
    return {"report_version": "corridor-lab.batch/v1", "status": "unresolved" if any(item["status"] == "unresolved" for item in items) else "pass", "items": items}
