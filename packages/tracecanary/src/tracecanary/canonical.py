"""Canonical JSON and safe JSON loading primitives."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


class InputError(ValueError):
    """A malformed or unsafe input payload."""


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError("JSON object contains a duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    """Reject the non-standard NaN and Infinity spellings accepted by json.loads."""
    raise InputError(f"JSON constant {value} is not permitted")


def parse_json_text(text: str, *, max_bytes: int, max_depth: int) -> Any:
    """Parse UTF-8 JSON text with the same rejection rules as ``load_json``.

    ``json.loads`` keeps the last duplicate key. A draft checked that way can
    validate and then be saved as text the file loader refuses.
    """
    if not isinstance(text, str):
        raise InputError("input must be UTF-8 JSON")
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InputError("input must be UTF-8 JSON") from exc
    if len(raw) > max_bytes:
        raise InputError(f"input exceeds the {max_bytes}-byte limit")
    try:
        data = json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
        )
    except RecursionError as exc:
        raise InputError("input exceeds the parser nesting safety limit") from exc
    except json.JSONDecodeError as exc:
        raise InputError("input is not valid JSON") from exc
    _check_depth(data, max_depth)
    _check_unicode_scalars(data)
    return data


def load_json(path: Path, *, max_bytes: int, max_depth: int) -> Any:
    """Load UTF-8 JSON while rejecting duplicate keys, large files and deep trees."""
    try:
        # Opening a FIFO must not block before we can inspect the descriptor.
        # Inspect the opened file, not a separate path stat, to avoid a race.
        with open(
            path,
            "rb",
            opener=lambda name, flags: os.open(name, flags | getattr(os, "O_NONBLOCK", 0)),
        ) as input_file:
            info = os.fstat(input_file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise InputError("input must be a regular file")
            if info.st_size > max_bytes:
                raise InputError(f"input exceeds the {max_bytes}-byte limit")
            raw = input_file.read(max_bytes + 1)
    except FileNotFoundError as exc:
        raise InputError("input file does not exist") from exc
    except IsADirectoryError as exc:
        raise InputError("input path is a directory") from exc
    except PermissionError as exc:
        # Windows reports opening a directory as a permission error. This
        # path check only refines a rejection, never authorizes a file read.
        try:
            is_directory = path.is_dir()
        except OSError:
            is_directory = False
        if is_directory:
            raise InputError("input path is a directory") from exc
        raise InputError("input file cannot be read") from exc
    except OSError as exc:
        raise InputError("input file cannot be read") from exc
    if len(raw) > max_bytes:
        raise InputError(f"input exceeds the {max_bytes}-byte limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError("input must be UTF-8 JSON") from exc
    return parse_json_text(text, max_bytes=max_bytes, max_depth=max_depth)


def _check_depth(value: Any, limit: int) -> None:
    """Check nesting iteratively so adversarial input cannot recurse in Python."""
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > limit:
            raise InputError(f"input exceeds the nesting limit of {limit}")
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)


def _check_unicode_scalars(value: Any) -> None:
    """Reject escaped lone surrogates that cannot be emitted as UTF-8."""
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            try:
                current.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise InputError("input contains an invalid Unicode scalar value") from exc
        elif isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)


def canonical_json(value: Any) -> str:
    """Serialize a report with stable key order, separators and newline."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def json_pointer(parts: tuple[str, ...]) -> str:
    """Return an RFC 6901-compatible JSON pointer."""
    if not parts:
        return ""
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def pointer_matches(pattern: str, parts: tuple[str, ...]) -> bool:
    """Return whether an exact-or-wildcard JSON pointer is a prefix of parts."""
    if not pattern.startswith("/"):
        return False
    raw = pattern.split("/")[1:]
    if len(raw) > len(parts):
        return False
    for expected, actual in zip(raw, parts):
        expected = expected.replace("~1", "/").replace("~0", "~")
        if expected != "*" and expected != actual:
            return False
    return True
