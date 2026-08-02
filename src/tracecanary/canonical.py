"""Canonical JSON and safe JSON loading primitives."""

from __future__ import annotations

import json
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


def load_json(path: Path, *, max_bytes: int, max_depth: int) -> Any:
    """Load UTF-8 JSON while rejecting duplicate keys, large files and deep trees."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise InputError("input file cannot be read") from exc
    if size > max_bytes:
        raise InputError(f"input exceeds the {max_bytes}-byte limit")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError("input file cannot be read") from exc
    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise InputError("input must be UTF-8 JSON") from exc
    except RecursionError as exc:
        raise InputError("input exceeds the parser nesting safety limit") from exc
    except json.JSONDecodeError as exc:
        raise InputError("input is not valid JSON") from exc
    _check_depth(data, max_depth)
    return data


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
