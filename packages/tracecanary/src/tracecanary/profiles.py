"""Synthetic, version-pinned TraceCanary contract profiles.

Every profile is a real ``tracecanary/v2`` contract that parses through
:func:`tracecanary.contract.parse_contract`. Profiles exist so a user can start
from a declared, fictional contract instead of inventing canary values; they
contain no real telemetry and no real secrets.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from tracecanary.canonical import InputError, canonical_json, load_json


PROFILE_FILENAME = "contract.json"
# Profiles ship as package data inside the distribution, so `profile list`
# works from an installed wheel and not only from a source checkout.
_PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
_MAX_PROFILE_BYTES = 1_000_000
_MAX_PROFILE_DEPTH = 50

_METADATA: dict[str, dict[str, str]] = {
    "gen-ai-baseline": {
        "title": "GenAI baseline",
        "summary": (
            "Synthetic canaries for prompt, tool call arguments, tool call result, and end-user identifier "
            "leakage, with GenAI operational fields retained by an explicit retention requirement."
        ),
    },
    "http-service-baseline": {
        "title": "HTTP service baseline",
        "summary": (
            "Server and client HTTP spans: request method and route are retained, header attributes and "
            "structured header dumps are forbidden. Contains no GenAI attributes."
        ),
    },
    "database-client-baseline": {
        "title": "Database client baseline",
        "summary": (
            "Database client spans: system name and query summary are retained, statement text and bound "
            "parameter attributes are forbidden."
        ),
    },
    "strict-safety-net": {
        "title": "Strict safety net",
        "summary": (
            "Broadest profile: every GenAI, HTTP header, and database statement rule plus a matched_ratio "
            "retention requirement with declared matching keys and a declared denominator."
        ),
    },
}

PROFILE_IDS: tuple[str, ...] = tuple(sorted(_METADATA))


def profile(profile_id: str) -> dict[str, Any]:
    """Return a deep copy of one profile's contract document."""
    return deepcopy(_load(profile_id))


def write_profile(profile_id: str, destination: Path) -> Path:
    """Write a profile as ``contract.json`` into an existing empty directory."""
    contract = profile(profile_id)
    try:
        if not destination.exists():
            raise InputError("profile output directory does not exist")
        if not destination.is_dir():
            raise InputError("profile output must be a directory")
        if any(destination.iterdir()):
            raise InputError("profile output directory must be empty")
    except OSError as exc:
        raise InputError("profile output directory could not be read") from exc
    target = destination / PROFILE_FILENAME
    if target.exists():
        raise InputError(f"profile output already contains {PROFILE_FILENAME}")
    try:
        target.write_text(canonical_json(contract), encoding="utf-8", newline="\n")
    except OSError as exc:
        raise InputError("profile output could not be written") from exc
    return target


def describe(profile_id: str) -> dict[str, Any]:
    """Return stable metadata for one profile, derived from its contract."""
    contract = _load(profile_id)
    metadata = _METADATA[profile_id]
    return {
        "profile_id": profile_id,
        "title": metadata["title"],
        "summary": metadata["summary"],
        "contract_version": contract["contract_version"],
        "semantic_conventions_version": contract["semantic_conventions_version"],
        "covered_attributes": list(_covered_attributes(contract)),
        "retention_requirements": list(_retention_requirements(contract)),
    }


def _load(profile_id: str) -> dict[str, Any]:
    """Load one profile document, rejecting identifiers that are not shipped."""
    if profile_id not in _METADATA:
        raise InputError("unknown profile; valid profile ids: " + ", ".join(PROFILE_IDS))
    path = _PROFILE_DIR / f"{profile_id}.json"
    if not path.is_file():
        raise InputError("profile document is missing from the installed package")
    try:
        return load_json(path, max_bytes=_MAX_PROFILE_BYTES, max_depth=_MAX_PROFILE_DEPTH)
    except InputError as exc:
        raise InputError(f"profile could not be loaded: {exc}") from exc


def _covered_attributes(contract: dict[str, Any]) -> tuple[str, ...]:
    """Return the concrete keys and prefixes the contract actually checks."""
    covered: set[str] = set()
    for key in contract.get("forbidden_attribute_keys", []):
        covered.add(f"key:{key}")
    for prefix in contract.get("forbidden_attribute_key_prefixes", []):
        covered.add(f"key-prefix:{prefix}")
    for prefix in contract.get("forbidden_path_prefixes", []):
        covered.add(f"path-prefix:{prefix}")
    for field in contract.get("required_retained_fields", []):
        covered.add(f"{field['scope']}:{field['key']}")
    for requirement in contract.get("retention", {}).get("requirements", []):
        covered.add(f"{requirement['scope']}:{requirement['key']}")
        for matching_key in requirement.get("matching_keys", []):
            covered.add(f"identity:{matching_key['scope']}:{matching_key['key']}")
    return tuple(sorted(covered))


def _retention_requirements(contract: dict[str, Any]) -> tuple[dict[str, str], ...]:
    requirements: list[dict[str, str]] = []
    for requirement in contract.get("retention", {}).get("requirements", []):
        requirements.append(
            {
                "requirement_id": requirement["requirement_id"],
                "scope": requirement["scope"],
                "key": requirement["key"],
                "comparison": requirement.get("comparison", "presence"),
            }
        )
    return tuple(requirements)
