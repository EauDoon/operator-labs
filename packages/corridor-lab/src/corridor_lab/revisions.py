"""Explicit, user-directed scenario revision storage.

Corridor Lab never autosaves. A revision exists only after the user asks for one
and chooses where it goes. Revisions are plain scenario documents with a
deterministic, padded sequence number so that lexicographic file order is also
chronological order.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .canonical import InputError, canonical_dumps_decimal, load_json, read_bounded_bytes
from .scenario import parse_scenario

REVISION_SUFFIX = ".json"
MAX_REVISIONS = 512
_REVISION_NAME = re.compile(r"^(?P<stem>.+)-r(?P<number>\d{4,6})$")


class RevisionError(InputError):
    """A revision could not be listed, read, or written."""


def revision_path(directory: str | Path, scenario_id: str, number: int) -> Path:
    return Path(directory) / f"{scenario_id}-r{number:04d}{REVISION_SUFFIX}"


def next_revision_number(directory: str | Path, scenario_id: str) -> int:
    """Return the next sequence number for one scenario in a revision folder."""
    return max((item["number"] for item in list_revisions(directory) if item["scenario_id"] == scenario_id), default=0) + 1


def save_revision(directory: str | Path, document: dict[str, Any], *, overwrite: bool = False) -> Path:
    """Validate a scenario document and write it as the next revision.

    The document is parsed first, so an invalid draft can never be stored as a
    revision. An existing file is replaced only when the caller passes
    ``overwrite=True``, which the GUI never does for an automatically derived
    path.
    """
    parsed = parse_scenario(document)
    target_directory = Path(directory)
    if not target_directory.is_dir():
        raise RevisionError(f"revision folder does not exist: {target_directory}")
    target = revision_path(target_directory, parsed.scenario_id, next_revision_number(target_directory, parsed.scenario_id))
    if target.exists() and not overwrite:
        raise RevisionError(f"revision already exists: {target}")
    try:
        target.write_text(canonical_dumps_decimal(document), encoding="utf-8", newline="\n")
    except OSError as exc:
        raise RevisionError(f"revision could not be written: {exc}") from exc
    return target


def list_revisions(directory: str | Path) -> list[dict[str, Any]]:
    """Return bounded revision metadata sorted by sequence number, then name."""
    target_directory = Path(directory)
    if not target_directory.is_dir():
        raise RevisionError(f"revision folder does not exist: {target_directory}")
    found: list[dict[str, Any]] = []
    for path in target_directory.glob(f"*{REVISION_SUFFIX}"):
        match = _REVISION_NAME.fullmatch(path.stem)
        if match is None:
            continue
        found.append(
            {
                "path": str(path),
                "name": path.name,
                "scenario_id": match.group("stem"),
                "number": int(match.group("number")),
            }
        )
        if len(found) > MAX_REVISIONS:
            raise RevisionError(f"revision folder exceeds the {MAX_REVISIONS}-revision budget")
    found.sort(key=lambda item: (item["scenario_id"], item["number"], item["name"]))
    return found


def load_revision(path: str | Path) -> dict[str, Any]:
    """Read one revision and return it only if it is a valid scenario."""
    document = load_json(path)
    if not isinstance(document, dict):
        raise RevisionError(f"revision is not a scenario object: {path}")
    parse_scenario(document)
    return document


def read_revision_text(path: str | Path) -> str:
    """Return the raw text of one revision for the editor, after a size check."""
    return read_bounded_bytes(path).decode("utf-8")
