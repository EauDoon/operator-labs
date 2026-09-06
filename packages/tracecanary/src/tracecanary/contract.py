"""Strict, version-pinned TraceCanary contract handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tracecanary.canonical import InputError, load_json

if TYPE_CHECKING:  # pragma: no cover - typing-only import
    from tracecanary.retention import RetentionSpec


SUPPORTED_CONTRACT_VERSION = "tracecanary/v1"
SUPPORTED_CONTRACT_VERSION_V2 = "tracecanary/v2"
SUPPORTED_CONTRACT_VERSIONS = (SUPPORTED_CONTRACT_VERSION, SUPPORTED_CONTRACT_VERSION_V2)
SUPPORTED_SEMCONV_VERSION = "opentelemetry/semconv/1.43.0"
DEFAULT_MAX_INPUT_BYTES = 5_000_000
DEFAULT_MAX_NESTING = 100
DEFAULT_MAX_BATCH_FILES = 256


class ContractError(ValueError):
    """An invalid or unsupported contract."""


@dataclass(frozen=True)
class Canary:
    label: str
    category: str
    value: str


@dataclass(frozen=True)
class RetainedField:
    scope: str
    key: str


@dataclass(frozen=True)
class Contract:
    contract_version: str
    semantic_conventions_version: str
    canaries: tuple[Canary, ...]
    forbidden_attribute_keys: tuple[str, ...]
    forbidden_attribute_key_prefixes: tuple[str, ...]
    forbidden_path_prefixes: tuple[str, ...]
    required_retained_fields: tuple[RetainedField, ...]
    max_input_bytes: int
    max_nesting: int
    max_batch_files: int
    retention: RetentionSpec | None = None


def load_contract(path: Path) -> Contract:
    try:
        raw = load_json(path, max_bytes=1_000_000, max_depth=50)
    except InputError as exc:
        raise ContractError(str(exc)) from exc
    return parse_contract(raw)


def parse_contract(raw: Any) -> Contract:
    if not isinstance(raw, dict):
        raise ContractError("contract must be a JSON object")
    allowed = {
        "contract_version",
        "semantic_conventions_version",
        "canaries",
        "forbidden_attribute_keys",
        "forbidden_attribute_key_prefixes",
        "forbidden_path_prefixes",
        "required_retained_fields",
        "limits",
    }
    if raw.get("contract_version") == SUPPORTED_CONTRACT_VERSION_V2:
        allowed = allowed | {"retention"}
    unknown = set(raw) - allowed
    if unknown:
        raise ContractError("contract contains unsupported fields")
    required = {"contract_version", "semantic_conventions_version", "canaries", "required_retained_fields"}
    if set(raw) & required != required:
        raise ContractError("contract is missing required fields")
    version = raw["contract_version"]
    semconv = raw["semantic_conventions_version"]
    if version not in SUPPORTED_CONTRACT_VERSIONS:
        raise ContractError("unsupported contract version")
    if semconv != SUPPORTED_SEMCONV_VERSION:
        raise ContractError("unsupported semantic-conventions version")
    canaries = _parse_canaries(raw["canaries"])
    retained = _parse_retained(raw["required_retained_fields"])
    keys = _string_list(raw.get("forbidden_attribute_keys", []), "forbidden_attribute_keys")
    key_prefixes = _string_list(raw.get("forbidden_attribute_key_prefixes", []), "forbidden_attribute_key_prefixes")
    paths = _string_list(raw.get("forbidden_path_prefixes", []), "forbidden_path_prefixes")
    if any(not item.startswith("/") for item in paths):
        raise ContractError("forbidden path prefixes must be JSON pointers")
    retention = _parse_retention(raw.get("retention")) if version == SUPPORTED_CONTRACT_VERSION_V2 else None
    _reject_reportable_canary_values(canaries, retained, keys, key_prefixes, paths, retention)
    max_bytes, max_nesting, max_batch_files = _parse_limits(raw.get("limits", {}))
    return Contract(
        contract_version=version,
        semantic_conventions_version=semconv,
        canaries=canaries,
        forbidden_attribute_keys=keys,
        forbidden_attribute_key_prefixes=key_prefixes,
        forbidden_path_prefixes=paths,
        required_retained_fields=retained,
        max_input_bytes=max_bytes,
        max_nesting=max_nesting,
        max_batch_files=max_batch_files,
        retention=retention,
    )


def _parse_retention(value: Any) -> RetentionSpec | None:
    """Parse the optional retention object, which only v2 contracts may carry."""
    if value is None:
        return None
    from tracecanary.retention import parse_retention

    return parse_retention(value)


def _parse_canaries(value: Any) -> tuple[Canary, ...]:
    if not isinstance(value, list) or not value:
        raise ContractError("canaries must be a non-empty list")
    result: list[Canary] = []
    labels: set[str] = set()
    values: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"label", "category", "value"}:
            raise ContractError("each canary must contain label, category and value")
        label, category, canary_value = item["label"], item["category"], item["value"]
        if not all(isinstance(part, str) and part for part in (label, category, canary_value)):
            raise ContractError("canary label, category and value must be non-empty strings")
        if label in labels or canary_value in values:
            raise ContractError("canary labels and values must be unique")
        labels.add(label)
        values.add(canary_value)
        result.append(Canary(label, category, canary_value))
    for canary in result:
        if any(value in canary.label or value in canary.category for value in values):
            raise ContractError("canary labels and categories must not contain canary values")
    return tuple(result)


def _parse_retained(value: Any) -> tuple[RetainedField, ...]:
    if not isinstance(value, list):
        raise ContractError("required_retained_fields must be a list")
    result: list[RetainedField] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"scope", "key"}:
            raise ContractError("each required retained field must contain scope and key")
        scope, key = item["scope"], item["key"]
        if scope not in {"resource", "span", "event"} or not isinstance(key, str) or not key:
            raise ContractError("retained field scope or key is invalid")
        if (scope, key) in seen:
            raise ContractError("required retained fields must be unique")
        seen.add((scope, key))
        result.append(RetainedField(scope, key))
    return tuple(result)


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ContractError(f"{field} must be a list of non-empty strings")
    if len(set(value)) != len(value):
        raise ContractError(f"{field} must not contain duplicates")
    return tuple(value)


def _reject_reportable_canary_values(
    canaries: tuple[Canary, ...],
    retained: tuple[RetainedField, ...],
    keys: tuple[str, ...],
    key_prefixes: tuple[str, ...],
    paths: tuple[str, ...],
    retention: RetentionSpec | None = None,
) -> None:
    retention_strings = ()
    if retention is not None:
        from tracecanary.retention import reportable_strings

        retention_strings = reportable_strings(retention)
    reportable = (*keys, *key_prefixes, *paths, *(field.key for field in retained), *retention_strings)
    if any(canary.value in value for canary in canaries for value in reportable):
        raise ContractError("report-visible contract fields must not contain canary values")


def _parse_limits(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, dict) or set(value) - {"max_input_bytes", "max_nesting", "max_batch_files"}:
        raise ContractError("limits contains unsupported fields")
    max_bytes = value.get("max_input_bytes", DEFAULT_MAX_INPUT_BYTES)
    max_nesting = value.get("max_nesting", DEFAULT_MAX_NESTING)
    max_batch_files = value.get("max_batch_files", DEFAULT_MAX_BATCH_FILES)
    if type(max_bytes) is not int or not 1_024 <= max_bytes <= 50_000_000:
        raise ContractError("limits.max_input_bytes must be an integer from 1024 to 50000000")
    if type(max_nesting) is not int or not 2 <= max_nesting <= 1_000:
        raise ContractError("limits.max_nesting must be an integer from 2 to 1000")
    if type(max_batch_files) is not int or not 1 <= max_batch_files <= 10_000:
        raise ContractError("limits.max_batch_files must be an integer from 1 to 10000")
    return max_bytes, max_nesting, max_batch_files
