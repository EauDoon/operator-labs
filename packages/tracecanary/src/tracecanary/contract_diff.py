"""Review how a contract change alters what TraceCanary checks.

This is a **coverage review, not a privacy measurement**. A contract declares
which synthetic values, attribute keys, JSON paths, retained fields, retention
requirements, input limits, and pinned versions TraceCanary understands. Adding
or removing any of those changes what the checker looks for. It says nothing
about how private any real system is, in either direction.

Canaries are compared and reported **by label only**. A canary value is never
emitted, never compared for anything but a private equality check, and never
echoed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

from tracecanary.contract import Contract
from tracecanary.retention import RetentionRequirement, RetentionSpec
from tracecanary.report import ensure_object_values_absent, ensure_text_values_absent


REVIEW_VERSION = "tracecanary.contract-review/v1"

REDUCED: Literal["coverage_reduced"] = "coverage_reduced"
INCREASED: Literal["coverage_increased"] = "coverage_increased"
CHANGED: Literal["coverage_changed"] = "coverage_changed"
UNCHANGED: Literal["coverage_unchanged"] = "coverage_unchanged"

VERDICTS = (REDUCED, INCREASED, CHANGED, UNCHANGED)

DISCLAIMER = (
    "This review describes changes in what TraceCanary checks. It is not a measurement "
    "of real-world privacy, redaction correctness, or compliance."
)

Classification = Literal["coverage_reduced", "coverage_increased", "coverage_changed"]


@dataclass(frozen=True)
class ContractChange:
    """One described change in checking coverage, with the direction explained."""

    category: str
    classification: Classification
    target: str
    change: str
    note: str
    before: str | int | tuple[str, ...] | None = None
    after: str | int | tuple[str, ...] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "category": self.category,
            "classification": self.classification,
            "target": self.target,
            "change": self.change,
            "note": self.note,
        }
        if self.before is not None:
            payload["before"] = self.before
        if self.after is not None:
            payload["after"] = self.after
        return payload


def review_contract_change(
    before: Contract,
    after: Contract,
    *,
    redacted_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Report how moving from one contract to another changes checking coverage.

    The verdict is the strict aggregation of every described change: any
    reduction wins, otherwise any increase, otherwise unchanged.
    """
    changes: list[ContractChange] = []
    changes.extend(_canary_changes(before, after))
    changes.extend(_prohibition_changes(before, after))
    changes.extend(_retained_field_changes(before, after))
    changes.extend(_retention_changes(before, after))
    changes.extend(_limit_changes(before, after))
    changes.extend(_version_changes(before, after))
    counts = {
        "reduced": sum(item.classification == REDUCED for item in changes),
        "increased": sum(item.classification == INCREASED for item in changes),
        "changed": sum(item.classification == CHANGED for item in changes),
    }
    verdict = REDUCED if counts["reduced"] else INCREASED if counts["increased"] else UNCHANGED
    review: dict[str, Any] = {
        "review_version": REVIEW_VERSION,
        "verdict": verdict,
        "counts": counts,
        "changes": [item.as_dict() for item in changes],
        "disclaimer": DISCLAIMER,
    }
    values = tuple(dict.fromkeys((*redacted_values, *(canary.value for canary in before.canaries), *(canary.value for canary in after.canaries))))
    ensure_object_values_absent(review, values)
    return review


def render_contract_review_human(review: dict[str, Any], *, redacted_values: tuple[str, ...] = ()) -> str:
    """Render a contract review as deterministic human text, disclaimer included."""
    counts = review.get("counts", {})
    changes = review.get("changes", [])
    lines = [
        f"TraceCanary contract review: {str(review.get('verdict', UNCHANGED)).upper()}",
        f"disclaimer: {DISCLAIMER}",
        f"reduced: {counts.get('reduced', 0)}; increased: {counts.get('increased', 0)}; changed: {counts.get('changed', 0)}",
    ]
    if not changes:
        lines.append("- no change in checking coverage was detected between the two contracts")
    for change in changes:
        lines.append(f"- [{change['classification']}] {change['category']}: {change['target']} {change['change']}")
        if "before" in change or "after" in change:
            lines.append(f"    before={_render(change.get('before'))} after={_render(change.get('after'))}")
        lines.append(f"    {change['note']}")
    text = "\n".join(lines) + "\n"
    ensure_text_values_absent(text, redacted_values)
    return text


def _render(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value) if value else "none"
    return str(value)


def _canary_changes(before: Contract, after: Contract) -> list[ContractChange]:
    """Compare canaries by label, never by value."""
    before_labels = {canary.label: canary for canary in before.canaries}
    after_labels = {canary.label: canary for canary in after.canaries}
    changes = [
        ContractChange(
            "canary",
            REDUCED,
            label,
            "removed",
            "this canary is no longer declared, so its value is no longer matched anywhere in the input",
        )
        for label in sorted(set(before_labels) - set(after_labels))
    ]
    changes.extend(
        ContractChange(
            "canary",
            INCREASED,
            label,
            "added",
            "this canary is newly declared, so its value is now matched where it was previously invisible",
        )
        for label in sorted(set(after_labels) - set(before_labels))
    )
    for label in sorted(set(before_labels) & set(after_labels)):
        previous = before_labels[label]
        current = after_labels[label]
        if previous.category != current.category:
            changes.append(
                ContractChange(
                    "canary",
                    CHANGED,
                    label,
                    "category changed",
                    "the declared role changed, which changes how findings are labelled and grouped, not which value is matched",
                    before=previous.category,
                    after=current.category,
                )
            )
        if previous.value != current.value:
            changes.append(
                ContractChange(
                    "canary",
                    CHANGED,
                    label,
                    "value replaced",
                    "the declared value is not identical, so a different string is now matched; TraceCanary compares values only for this equality check and never renders them, so it cannot say from the label alone which value is broader",
                )
            )
    return changes


def _prohibition_changes(before: Contract, after: Contract) -> list[ContractChange]:
    fields = (
        ("forbidden_attribute_keys", "forbidden attribute key"),
        ("forbidden_attribute_key_prefixes", "forbidden attribute key prefix"),
        ("forbidden_path_prefixes", "forbidden path prefix"),
    )
    changes: list[ContractChange] = []
    for field, description in fields:
        previous = set(getattr(before, field))
        current = set(getattr(after, field))
        changes.extend(
            ContractChange(
                field,
                REDUCED,
                entry,
                "removed",
                f"this {description} is no longer declared, so an input carrying it is no longer reported",
            )
            for entry in sorted(previous - current)
        )
        changes.extend(
            ContractChange(
                field,
                INCREASED,
                entry,
                "added",
                f"this {description} is newly declared, so an input carrying it is now reported",
            )
            for entry in sorted(current - previous)
        )
    return changes


def _retained_field_changes(before: Contract, after: Contract) -> list[ContractChange]:
    """Compare the v1 required-retained-fields list by declared scope and key."""
    previous = {(field.scope, field.key) for field in before.required_retained_fields}
    current = {(field.scope, field.key) for field in after.required_retained_fields}
    changes = [
        ContractChange(
            "required_retained_fields",
            REDUCED,
            f"{scope}:{key}",
            "removed",
            "this operational field is no longer required, so its absence is no longer reported",
        )
        for scope, key in sorted(previous - current)
    ]
    changes.extend(
        ContractChange(
            "required_retained_fields",
            INCREASED,
            f"{scope}:{key}",
            "added",
            "this operational field is newly required, so its absence is now reported",
        )
        for scope, key in sorted(current - previous)
    )
    return changes


def _retention_changes(before: Contract, after: Contract) -> list[ContractChange]:
    """Compare v2 retention requirements by declared requirement id."""
    previous = {item.requirement_id: item for item in _requirements(before.retention)}
    current = {item.requirement_id: item for item in _requirements(after.retention)}
    changes: list[ContractChange] = []
    changes.extend(
        ContractChange(
            "retention",
            REDUCED,
            identifier,
            "requirement removed",
            "this retention requirement is no longer declared, so the attribute it counted is no longer checked",
        )
        for identifier in sorted(set(previous) - set(current))
    )
    changes.extend(
        ContractChange(
            "retention",
            INCREASED,
            identifier,
            "requirement added",
            "this retention requirement is newly declared, so the attribute it counts is now checked",
        )
        for identifier in sorted(set(current) - set(previous))
    )
    for identifier in sorted(set(previous) & set(current)):
        changes.extend(_requirement_changes(previous[identifier], current[identifier]))
    return changes


def _requirements(spec: RetentionSpec | None) -> tuple[RetentionRequirement, ...]:
    return () if spec is None else spec.requirements


def _requirement_changes(before: RetentionRequirement, after: RetentionRequirement) -> list[ContractChange]:
    changes: list[ContractChange] = []
    target = before.requirement_id
    if before.minimum_count != after.minimum_count:
        lowered = after.minimum_count < before.minimum_count
        changes.append(
            ContractChange(
                "retention",
                REDUCED if lowered else INCREASED,
                target,
                "minimum_count lowered" if lowered else "minimum_count raised",
                "a lower minimum_count accepts fewer matching attributes before a finding is reported, so fewer traces fail"
                if lowered
                else "a higher minimum_count accepts only traces with at least that many matching attributes, so more traces fail",
                before=before.minimum_count,
                after=after.minimum_count,
            )
        )
    changes.extend(_value_type_changes(before, after))
    if before.comparison != after.comparison:
        changes.append(
            ContractChange(
                "retention",
                CHANGED,
                target,
                "comparison changed",
                f"the comparison mode changed from {before.comparison} to {after.comparison}; "
                f"{_comparison_note(before.comparison, after.comparison)}",
                before=before.comparison,
                after=after.comparison,
            )
        )
    changes.extend(_matching_key_changes(before, after))
    if before.denominator_requirement_id != after.denominator_requirement_id:
        changes.append(
            ContractChange(
                "retention",
                CHANGED,
                target,
                "denominator changed",
                "the declared denominator requirement changed, so the ratio is taken over a different population and results from the two contracts are not comparable",
                before=before.denominator_requirement_id or "none",
                after=after.denominator_requirement_id or "none",
            )
        )
    for field, description in (("scope", "the counted scope"), ("key", "the counted key")):
        previous_value = getattr(before, field)
        current_value = getattr(after, field)
        if previous_value != current_value:
            changes.append(
                ContractChange(
                    "retention",
                    CHANGED,
                    target,
                    f"{field} changed",
                    f"{description} changed, so this requirement counts different attributes than it did before",
                    before=previous_value,
                    after=current_value,
                )
            )
    return changes


def _comparison_note(before: str, after: str) -> str:
    return (
        f"{before} checked only what that mode can see, while {after} checks "
        f"{'presence against the declared minimum_count' if after == 'presence' else 'a strict decrease against a baseline' if after == 'count' else 'a per-identity ratio, which additionally requires declared matching keys and a declared denominator'}"
    )


def _value_type_changes(before: RetentionRequirement, after: RetentionRequirement) -> list[ContractChange]:
    """Classify a value_types change by whether the check became stricter.

    ``value_types`` is the set of permitted OTLP value kinds, so a *narrower*
    permitted set rejects more inputs and is an increase in checking coverage.
    """
    previous = before.value_types
    current = after.value_types
    if previous == current:
        return []
    target = before.requirement_id
    if previous is None:
        return [
            ContractChange(
                "retention",
                INCREASED,
                target,
                "value_types declared",
                "a value-kind expectation was added, so a matching attribute with an undeclared OTLP value kind is now reported",
                before="none",
                after=current or (),
            )
        ]
    if current is None:
        return [
            ContractChange(
                "retention",
                REDUCED,
                target,
                "value_types removed",
                "the value-kind expectation was removed, so the value kind of a matching attribute is no longer checked at all",
                before=previous,
                after="none",
            )
        ]
    previous_set = set(previous)
    current_set = set(current)
    if current_set < previous_set:
        return [
            ContractChange(
                "retention",
                INCREASED,
                target,
                "value_types narrowed",
                "the permitted set is narrower, so more value kinds are reported as a mismatch",
                before=previous,
                after=current,
            )
        ]
    if previous_set < current_set:
        return [
            ContractChange(
                "retention",
                REDUCED,
                target,
                "value_types widened",
                "the permitted set is wider, so fewer value kinds are reported as a mismatch",
                before=previous,
                after=current,
            )
        ]
    return [
        ContractChange(
            "retention",
            CHANGED,
            target,
            "value_types changed",
            "the permitted set changed without containing the previous one, so different value kinds are accepted and the results are not comparable",
            before=previous,
            after=current,
        )
    ]


def _matching_key_changes(before: RetentionRequirement, after: RetentionRequirement) -> list[ContractChange]:
    previous = set(_pairs(before.matching_keys))
    current = set(_pairs(after.matching_keys))
    target = before.requirement_id
    if previous == current:
        return []
    removed = sorted(previous - current)
    added = sorted(current - previous)
    changes = [
        ContractChange(
            "retention",
            REDUCED,
            f"{target}:{scope}:{key}",
            "matching key removed",
            "identity is now established from fewer declared keys, so more items share one identity and per-identity ratios are compared over coarser groups",
        )
        for scope, key in removed
    ]
    changes.extend(
        ContractChange(
            "retention",
            INCREASED,
            f"{target}:{scope}:{key}",
            "matching key added",
            "identity is now established from more declared keys, so comparison groups are finer and identity is harder to establish by accident",
        )
        for scope, key in added
    )
    if removed and added:
        changes.append(
            ContractChange(
                "retention",
                CHANGED,
                target,
                "matching keys replaced",
                "the declared identity changed, so identities from the two contracts do not describe the same populations",
                before=tuple(f"{scope}:{key}" for scope, key in sorted(previous)),
                after=tuple(f"{scope}:{key}" for scope, key in sorted(current)),
            )
        )
    return changes


def _pairs(matching_keys: Any) -> Iterable[tuple[str, str]]:
    return tuple((item.scope, item.key) for item in matching_keys) if matching_keys else ()


def _limit_changes(before: Contract, after: Contract) -> list[ContractChange]:
    notes = {
        "max_input_bytes": (
            "a larger max_input_bytes means larger inputs are accepted, not that checking got weaker or stronger; "
            "a smaller one means inputs that were once checked are now rejected as unresolved"
        ),
        "max_nesting": (
            "a larger max_nesting means deeper nesting is accepted, not that checking got weaker or stronger; "
            "a smaller one means deeply nested inputs that were once checked are now rejected as unresolved"
        ),
        "max_batch_files": (
            "a larger max_batch_files means more files are accepted in one batch, not that checking got weaker or stronger; "
            "a smaller one means a directory that was once checked in full is now rejected as unresolved"
        ),
    }
    changes = []
    for field, note in notes.items():
        previous = getattr(before, field)
        current = getattr(after, field)
        if previous != current:
            changes.append(ContractChange("limits", CHANGED, field, "changed", note, before=previous, after=current))
    return changes


def _version_changes(before: Contract, after: Contract) -> list[ContractChange]:
    changes = []
    for field, description in (
        ("contract_version", "the contract schema"),
        ("semantic_conventions_version", "the semantic conventions"),
    ):
        previous = getattr(before, field)
        current = getattr(after, field)
        if previous != current:
            changes.append(
                ContractChange(
                    "version",
                    CHANGED,
                    field,
                    "changed",
                    f"a {description} change alters what the checker understands and must be reviewed against the pinned specifications; "
                    "features that exist in one version may not exist in the other",
                    before=previous,
                    after=current,
                )
            )
    return changes
