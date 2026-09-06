"""Version-pinned retention requirements for ``tracecanary/v2`` contracts.

A retention requirement declares that a contract-visible attribute key must still
be exported, optionally with a declared OTLP value kind, and optionally compares
that observation with a baseline. Requirement identity is never inferred: the
``matched_ratio`` comparison only groups observations by keys the contract
explicitly declares in ``matching_keys``.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterator

from tracecanary.canonical import canonical_json
from tracecanary.contract import ContractError
from tracecanary.report import Violation


RETENTION_VERSION = "tracecanary.retention/v1"
MAX_RETENTION_REQUIREMENTS = 64
MAX_MATCHING_KEYS = 8
MAX_REQUIREMENT_ID_LENGTH = 64

REQUIREMENT_SCOPES = ("resource", "scope", "span", "event", "link")
VALUE_TYPES = (
    "stringValue",
    "boolValue",
    "intValue",
    "doubleValue",
    "arrayValue",
    "kvlistValue",
    "bytesValue",
)
COMPARISONS = ("presence", "count", "matched_ratio")

_REQUIREMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*")
_REQUIREMENT_FIELDS = {
    "requirement_id",
    "scope",
    "key",
    "value_types",
    "minimum_count",
    "comparison",
    "matching_keys",
    "denominator_requirement_id",
}

# Containment rank of the supported scopes. ``event`` and ``link`` are siblings
# beneath a span, so neither is an ancestor of the other.
_SCOPE_RANK = {"resource": 0, "scope": 1, "span": 2, "event": 3, "link": 3}


@dataclass(frozen=True)
class MatchingKey:
    """A contract-declared key used to establish comparison identity."""

    scope: str
    key: str


@dataclass(frozen=True)
class RetentionRequirement:
    """One declared retention requirement."""

    requirement_id: str
    scope: str
    key: str
    value_types: tuple[str, ...] | None
    minimum_count: int
    comparison: str
    matching_keys: tuple[MatchingKey, ...] | None
    denominator_requirement_id: str | None


@dataclass(frozen=True)
class RetentionSpec:
    """The parsed ``retention`` object of a v2 contract."""

    version: str
    requirements: tuple[RetentionRequirement, ...]


@dataclass(frozen=True)
class Observation:
    """One attribute seen in a trace, with the OTLP value kind actually present.

    ``value`` is never rendered into a report; it exists only so a declared
    matching key can establish identity between two traces.
    """

    scope: str
    key: str
    value_kind: str
    value: Any
    context: tuple[int, ...]


def parse_retention(raw: Any) -> RetentionSpec:
    """Parse and validate the optional ``retention`` object of a v2 contract."""
    if not isinstance(raw, dict):
        raise ContractError("retention must be a JSON object")
    if set(raw) - {"version", "requirements"}:
        raise ContractError("retention contains unsupported fields")
    if "version" not in raw:
        raise ContractError("retention requires a version")
    version = raw["version"]
    if version != RETENTION_VERSION:
        raise ContractError(f"retention version must be {RETENTION_VERSION}")
    if "requirements" not in raw:
        raise ContractError("retention requires requirements")
    return RetentionSpec(version, _parse_requirements(raw["requirements"]))


def reportable_strings(spec: RetentionSpec) -> tuple[str, ...]:
    """Return retention text that a report could echo, for canary-value checks."""
    values: list[str] = []
    for requirement in spec.requirements:
        values.append(requirement.requirement_id)
        values.append(requirement.key)
        for matching_key in requirement.matching_keys or ():
            values.append(matching_key.key)
    return tuple(values)


def _parse_requirements(value: Any) -> tuple[RetentionRequirement, ...]:
    if not isinstance(value, list) or not value:
        raise ContractError("retention.requirements must be a non-empty array")
    if len(value) > MAX_RETENTION_REQUIREMENTS:
        raise ContractError(f"retention.requirements must contain at most {MAX_RETENTION_REQUIREMENTS} entries")
    requirements: list[RetentionRequirement] = []
    identifiers: set[str] = set()
    for index, item in enumerate(value):
        requirement = _parse_requirement(item, index)
        if requirement.requirement_id in identifiers:
            raise ContractError(f"retention requirement {index} repeats an existing requirement_id")
        identifiers.add(requirement.requirement_id)
        requirements.append(requirement)
    _reject_cross_field_errors(requirements)
    return tuple(requirements)


def _parse_requirement(item: Any, index: int) -> RetentionRequirement:
    if not isinstance(item, dict):
        raise ContractError(f"retention requirement {index} must be a JSON object")
    if set(item) - _REQUIREMENT_FIELDS:
        raise ContractError(f"retention requirement {index} contains unsupported fields")
    requirement_id = _parse_requirement_id(item.get("requirement_id"), index)
    scope = item.get("scope")
    if scope not in REQUIREMENT_SCOPES:
        raise ContractError(f"retention requirement {index} scope must be one of " + ", ".join(REQUIREMENT_SCOPES))
    key = item.get("key")
    if not isinstance(key, str) or not key:
        raise ContractError(f"retention requirement {index} key must be a non-empty string")
    value_types = _parse_value_types(item.get("value_types"), index)
    minimum_count = _parse_minimum_count(item.get("minimum_count", 1), index)
    comparison = item.get("comparison", "presence")
    if comparison not in COMPARISONS:
        raise ContractError(f"retention requirement {index} comparison must be one of " + ", ".join(COMPARISONS))
    matching_keys = _parse_matching_keys(item.get("matching_keys"), index)
    denominator = item.get("denominator_requirement_id")
    if denominator is not None and (not isinstance(denominator, str) or not denominator):
        raise ContractError(f"retention requirement {index} denominator_requirement_id must be a non-empty string")
    return RetentionRequirement(
        requirement_id=requirement_id,
        scope=scope,
        key=key,
        value_types=value_types,
        minimum_count=minimum_count,
        comparison=comparison,
        matching_keys=matching_keys,
        denominator_requirement_id=denominator,
    )


def _parse_requirement_id(value: Any, index: int) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"retention requirement {index} requires a non-empty requirement_id")
    if len(value) > MAX_REQUIREMENT_ID_LENGTH:
        raise ContractError(f"retention requirement {index} requirement_id must be at most {MAX_REQUIREMENT_ID_LENGTH} characters")
    if not _REQUIREMENT_ID.fullmatch(value):
        raise ContractError(f"retention requirement {index} requirement_id must match [A-Za-z0-9][A-Za-z0-9._:/-]*")
    return value


def _parse_value_types(value: Any, index: int) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ContractError(f"retention requirement {index} value_types must be a non-empty array")
    if any(item not in VALUE_TYPES for item in value):
        raise ContractError(f"retention requirement {index} value_types contains an unsupported OTLP value kind")
    if len(set(value)) != len(value):
        raise ContractError(f"retention requirement {index} value_types must not contain duplicates")
    return tuple(value)


def _parse_minimum_count(value: Any, index: int) -> int:
    if type(value) is not int or value < 1:
        raise ContractError(f"retention requirement {index} minimum_count must be an integer of at least 1")
    return value


def _parse_matching_keys(value: Any, index: int) -> tuple[MatchingKey, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ContractError(f"retention requirement {index} matching_keys must be a non-empty array")
    if len(value) > MAX_MATCHING_KEYS:
        raise ContractError(f"retention requirement {index} matching_keys must contain at most {MAX_MATCHING_KEYS} entries")
    result: list[MatchingKey] = []
    seen: set[tuple[str, str]] = set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"scope", "key"}:
            raise ContractError(f"retention requirement {index} has a matching key without exactly scope and key")
        if entry["scope"] not in REQUIREMENT_SCOPES or not isinstance(entry["key"], str) or not entry["key"]:
            raise ContractError(f"retention requirement {index} matching key scope or key is invalid")
        if (entry["scope"], entry["key"]) in seen:
            raise ContractError(f"retention requirement {index} matching keys must be unique")
        seen.add((entry["scope"], entry["key"]))
        result.append(MatchingKey(entry["scope"], entry["key"]))
    return tuple(result)


def _reject_cross_field_errors(requirements: list[RetentionRequirement]) -> None:
    """Reject mode/field combinations that would require guessing an identity."""
    by_id = {requirement.requirement_id: requirement for requirement in requirements}
    for index, requirement in enumerate(requirements):
        comparison = requirement.comparison
        if comparison == "matched_ratio":
            if requirement.matching_keys is None:
                raise ContractError(f"retention requirement {index} requires matching_keys for the matched_ratio comparison")
            if requirement.denominator_requirement_id is None:
                raise ContractError(f"retention requirement {index} requires denominator_requirement_id for the matched_ratio comparison")
        else:
            if requirement.matching_keys is not None:
                raise ContractError(f"retention requirement {index} must not declare matching_keys for the {comparison} comparison")
            if requirement.denominator_requirement_id is not None:
                raise ContractError(f"retention requirement {index} must not declare denominator_requirement_id for the {comparison} comparison")
        denominator = requirement.denominator_requirement_id
        if denominator is None:
            continue
        if denominator == requirement.requirement_id:
            raise ContractError(f"retention requirement {index} must not name itself as its denominator")
        if denominator not in by_id:
            raise ContractError(f"retention requirement {index} names an unknown denominator_requirement_id")
        if _has_denominator_cycle(by_id, requirement):
            raise ContractError(f"retention requirement {index} creates a denominator cycle")


def _has_denominator_cycle(by_id: dict[str, RetentionRequirement], requirement: RetentionRequirement) -> bool:
    seen: set[str] = {requirement.requirement_id}
    current = requirement.denominator_requirement_id
    while current is not None:
        if current in seen:
            return True
        seen.add(current)
        current = by_id[current].denominator_requirement_id if current in by_id else None
    return False


def iter_observations(payload: dict[str, Any]) -> Iterator[Observation]:
    """Yield every attribute with its OTLP value kind and containment context.

    Contexts are fixed-length so a containing resource, scope, or span can be
    derived without inspecting any attribute value: ``(resource, scope, span,
    event-or-link)`` with ``-1`` for levels that do not apply.
    """
    for resource_index, resource_span in enumerate(payload["resourceSpans"]):
        yield from _observations("resource", resource_span["resource"].get("attributes", []), (resource_index, -1, -1, -1))
        for scope_index, scope_span in enumerate(resource_span["scopeSpans"]):
            if "scope" in scope_span:
                yield from _observations("scope", scope_span["scope"].get("attributes", []), (resource_index, scope_index, -1, -1))
            for span_index, span in enumerate(scope_span["spans"]):
                span_context = (resource_index, scope_index, span_index, -1)
                yield from _observations("span", span.get("attributes", []), span_context)
                for event_index, event in enumerate(span.get("events", [])):
                    yield from _observations("event", event.get("attributes", []), (resource_index, scope_index, span_index, event_index))
                for link_index, link in enumerate(span.get("links", [])):
                    yield from _observations("link", link.get("attributes", []), (resource_index, scope_index, span_index, link_index))


def _observations(scope: str, attributes: list[dict[str, Any]], context: tuple[int, ...]) -> Iterator[Observation]:
    for attribute in attributes:
        value = attribute["value"]
        value_kind = next(iter(value))
        yield Observation(scope, attribute["key"], value_kind, value[value_kind], context)


def _matched(observations: tuple[Observation, ...], requirement: RetentionRequirement) -> tuple[Observation, ...]:
    """Return the observations of one requirement's declared scope and key."""
    return tuple(item for item in observations if item.scope == requirement.scope and item.key == requirement.key)


def check_requirements(spec: RetentionSpec, payload: dict[str, Any]) -> list[Violation]:
    """Report unmet retention requirements and value-kind mismatches."""
    observations = tuple(iter_observations(payload))
    violations: list[Violation] = []
    for requirement in spec.requirements:
        matched = _matched(observations, requirement)
        if len(matched) < requirement.minimum_count:
            violations.append(
                Violation(
                    "TC010",
                    "",
                    "retention requirement was not met",
                    key=requirement.requirement_id,
                    scope=requirement.scope,
                )
            )
        if requirement.value_types is not None and any(item.value_kind not in requirement.value_types for item in matched):
            violations.append(
                Violation(
                    "TC011",
                    "",
                    "retained attribute value type does not match the contract",
                    key=requirement.requirement_id,
                    scope=requirement.scope,
                )
            )
    return violations


def compare_requirements(spec: RetentionSpec, baseline: dict[str, Any], candidate: dict[str, Any]) -> list[Violation]:
    """Apply each requirement's declared comparison mode to two traces."""
    baseline_observations = tuple(iter_observations(baseline))
    candidate_observations = tuple(iter_observations(candidate))
    violations: list[Violation] = []
    for requirement in spec.requirements:
        if requirement.comparison == "presence":
            continue
        if requirement.comparison == "count":
            baseline_count = len(_matched(baseline_observations, requirement))
            candidate_count = len(_matched(candidate_observations, requirement))
            if candidate_count < baseline_count:
                violations.append(
                    Violation(
                        "TC012",
                        "",
                        "candidate retained fewer matching attributes than baseline",
                        key=requirement.requirement_id,
                        scope=requirement.scope,
                        detail=f"baseline_count={baseline_count} candidate_count={candidate_count}",
                    )
                )
            continue
        violations.extend(_compare_matched_ratio(spec, requirement, baseline_observations, candidate_observations))
    return violations


def _compare_matched_ratio(
    spec: RetentionSpec,
    requirement: RetentionRequirement,
    baseline_observations: tuple[Observation, ...],
    candidate_observations: tuple[Observation, ...],
) -> list[Violation]:
    baseline_groups, baseline_unidentified = _partition(baseline_observations, spec, requirement)
    candidate_groups, candidate_unidentified = _partition(candidate_observations, spec, requirement)
    violations: list[Violation] = []
    if baseline_unidentified or candidate_unidentified:
        violations.append(
            Violation(
                "TC014",
                "",
                "comparison identity could not be established from the declared matching keys",
                key=requirement.requirement_id,
                scope=requirement.scope,
                detail="identity-unestablished",
            )
        )
    for identity in sorted(set(baseline_groups) | set(candidate_groups)):
        baseline = baseline_groups.get(identity)
        candidate = candidate_groups.get(identity)
        if baseline is None or candidate is None:
            absent = "baseline" if candidate is None else "candidate"
            violations.append(
                Violation(
                    "TC014",
                    "",
                    "comparison identity is not present in both populations",
                    key=requirement.requirement_id,
                    scope=requirement.scope,
                    detail=f"identity-absent-{absent}",
                )
            )
            continue
        baseline_count, baseline_total = baseline
        candidate_count, candidate_total = candidate
        if not baseline_total or not candidate_total:
            violations.append(
                Violation(
                    "TC014",
                    "",
                    "declared denominator is not populated for this comparison identity",
                    key=requirement.requirement_id,
                    scope=requirement.scope,
                    detail="denominator-undefined",
                )
            )
            continue
        if candidate_count * baseline_total < baseline_count * candidate_total:
            violations.append(
                Violation(
                    "TC013",
                    "",
                    "candidate retained a lower matched ratio than baseline",
                    key=requirement.requirement_id,
                    scope=requirement.scope,
                    detail=f"baseline_count={baseline_count} baseline_total={baseline_total} candidate_count={candidate_count} candidate_total={candidate_total}",
                )
            )
    return violations


def _partition(
    observations: tuple[Observation, ...],
    spec: RetentionSpec,
    requirement: RetentionRequirement,
) -> tuple[dict[tuple[tuple[str, str], ...], tuple[int, int | None]], int]:
    """Group a requirement's scope by declared identity.

    Returns the ``identity -> (numerator, denominator)`` mapping and the number
    of items whose identity could not be established from declared keys. A
    ``None`` denominator means the declared denominator requirement could not be
    resolved for that identity, which is never treated as a pass.
    """
    by_container: dict[tuple[str, tuple[int, ...]], dict[str, Observation]] = {}
    for observation in observations:
        by_container.setdefault((observation.scope, observation.context), {}).setdefault(observation.key, observation)
    denominator = next(item for item in spec.requirements if item.requirement_id == requirement.denominator_requirement_id)
    items: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for observation in observations:
        if observation.scope == requirement.scope and observation.context not in seen:
            seen.add(observation.context)
            items.append(observation.context)
    groups: dict[tuple[tuple[str, str], ...], list[tuple[int, ...]]] = {}
    unidentified = 0
    for context in items:
        identity = _identity(by_container, context, requirement)
        if identity is None:
            unidentified += 1
            continue
        groups.setdefault(identity, []).append(context)
    partitioned: dict[tuple[tuple[str, str], ...], tuple[int, int | None]] = {}
    for identity, contexts in groups.items():
        numerator = sum(1 for context in contexts if requirement.key in by_container[(requirement.scope, context)])
        partitioned[identity] = (numerator, _denominator_count(by_container, contexts, requirement, denominator))
    return partitioned, unidentified


def _identity(
    by_container: dict[tuple[str, tuple[int, ...]], dict[str, Observation]],
    context: tuple[int, ...],
    requirement: RetentionRequirement,
) -> tuple[tuple[str, str], ...] | None:
    """Return the declared identity of one item, or None if it is undeclared."""
    values: list[tuple[str, str]] = []
    for matching_key in requirement.matching_keys or ():
        container = _ancestor(context, requirement.scope, matching_key.scope)
        if container is None:
            return None
        observation = by_container.get((matching_key.scope, container), {}).get(matching_key.key)
        if observation is None:
            return None
        values.append(_identity_value(observation))
    return tuple(values)


def _identity_value(observation: Observation) -> tuple[str, str]:
    """Return a hashable, sortable rendering of an identity value.

    The OTLP value kind is part of the identity so that, for example, the
    integer ``1`` and the boolean ``true`` cannot be conflated.
    """
    value = observation.value
    return (observation.value_kind, value if isinstance(value, str) else canonical_json(value))


def _ancestor(context: tuple[int, ...], item_scope: str, target_scope: str) -> tuple[int, ...] | None:
    """Return the containing context of ``target_scope``, or None if ambiguous."""
    if target_scope == item_scope:
        return context
    if _SCOPE_RANK[target_scope] > _SCOPE_RANK[item_scope]:
        return None
    if target_scope == "resource":
        return (context[0], -1, -1, -1)
    if target_scope == "scope":
        return (context[0], context[1], -1, -1)
    if target_scope == "span":
        return (context[0], context[1], context[2], -1)
    return None


def _denominator_count(
    by_container: dict[tuple[str, tuple[int, ...]], dict[str, Observation]],
    contexts: list[tuple[int, ...]],
    requirement: RetentionRequirement,
    denominator: RetentionRequirement,
) -> int | None:
    """Count the declared denominator within one identity, or None if undefined."""
    target = denominator.scope
    containers: set[tuple[int, ...]] = set()
    for context in contexts:
        if _SCOPE_RANK[target] <= _SCOPE_RANK[requirement.scope]:
            container = _ancestor(context, requirement.scope, target)
            if container is None:
                return None
            containers.add(container)
        else:
            containers.update(
                container
                for scope, container in by_container
                if scope == target and _ancestor(container, target, requirement.scope) == context
            )
    return sum(1 for container in containers if denominator.key in by_container.get((target, container), {}))
