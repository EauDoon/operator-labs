"""Bounded, in-memory, value-free run history.

The history exists only for the lifetime of the process that created it. It is
never written to a file, never read back, and never persisted between runs:
clearing it discards it permanently. Records carry no timestamp, so two
identical runs are indistinguishable except by their insertion order, which is
what keeps an export byte-stable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tracecanary.canonical import InputError, canonical_json
from tracecanary.report import BatchReport, Report, ensure_object_values_absent


HISTORY_VERSION = "tracecanary.history/v1"
DEFAULT_HISTORY_BOUND = 64
UNKNOWN_CONTRACT_VERSION = "unknown"
STATUSES: tuple[str, ...] = ("pass", "regression", "unresolved")

RunReport = Report | BatchReport


@dataclass(frozen=True)
class RunRecord:
    """One recorded run, identified by its insertion order and nothing else.

    ``sequence`` is 1-based and assigned in insertion order. There is no
    timestamp on purpose: a clock reading would make every export differ and
    would say nothing about the analysis.
    """

    sequence: int
    mode: str
    contract_version: str
    status: str
    summary: dict[str, Any]
    group: str | None
    report: RunReport


class RunHistory:
    """A bounded, in-memory list of run records.

    The bound is a hard limit, not a suggestion: appending past it is rejected
    with :class:`InputError` so memory use cannot grow without bound in a long
    desktop session. Callers decide whether to clear or to stop recording.
    """

    def __init__(self, bound: int = DEFAULT_HISTORY_BOUND) -> None:
        if type(bound) is not int or bound < 1:
            raise InputError("history bound must be an integer of at least 1")
        self._bound = bound
        self._records: list[RunRecord] = []
        self._values: list[str] = []

    @property
    def bound(self) -> int:
        """The maximum number of records this history will hold."""
        return self._bound

    def append(
        self,
        *,
        mode: str,
        contract_version: str,
        status: str,
        summary: Mapping[str, Any],
        report: RunReport,
        group: str | None = None,
        redacted_values: tuple[str, ...] = (),
    ) -> RunRecord:
        """Record one run and return its immutable record.

        ``redacted_values`` are the canary values that this run could have
        matched. They are accumulated and used to fail closed at export time, so
        an export is rejected rather than emitted if any recorded run could have
        carried a matched value into it.
        """
        if not isinstance(mode, str) or not mode.strip():
            raise InputError("run mode must be a non-empty string")
        if not isinstance(contract_version, str) or not contract_version.strip():
            raise InputError("run contract version must be a non-empty string")
        if status not in STATUSES:
            raise InputError("run status must be one of " + ", ".join(STATUSES))
        if not isinstance(summary, Mapping):
            raise InputError("run summary must be a mapping")
        if not isinstance(report, Mapping):
            raise InputError("run report must be a report object")
        if group is not None and (not isinstance(group, str) or not group.strip()):
            raise InputError("run group must be a non-empty string or None")
        if self.is_full():
            raise InputError(f"run history is full at its bound of {self._bound} run(s); clear it before recording more")
        self._values.extend(value for value in redacted_values if value not in self._values)
        record = RunRecord(
            sequence=len(self._records) + 1,
            mode=mode.strip(),
            contract_version=contract_version.strip(),
            status=status,
            summary=dict(summary),
            group=None if group is None else group.strip(),
            report=report,
        )
        self._records.append(record)
        return record

    def records(self) -> tuple[RunRecord, ...]:
        """Return every record in insertion order."""
        return tuple(self._records)

    def clear(self) -> None:
        """Discard every record and accumulated value. This cannot be undone."""
        self._records.clear()
        self._values.clear()

    def latest(self) -> RunRecord | None:
        """Return the most recently recorded run, or None when nothing was recorded."""
        return self._records[-1] if self._records else None

    def is_full(self) -> bool:
        """Return whether the bound has been reached."""
        return len(self._records) >= self._bound

    def redacted_values(self) -> tuple[str, ...]:
        """Return every canary value accumulated by the recorded runs, in first-seen order."""
        return tuple(self._values)

    def export(self, *, redacted_values: tuple[str, ...] = ()) -> str:
        """Return the whole history as deterministic canonical JSON.

        The export is checked against the canary values of every recorded run
        before it is returned, so a protected value fails the export closed
        instead of reaching a file.
        """
        payload = {
            "history_version": HISTORY_VERSION,
            "bound": self._bound,
            "count": len(self._records),
            "runs": [_run_payload(record) for record in self._records],
        }
        values = self.redacted_values() + tuple(value for value in redacted_values if value not in self._values)
        ensure_object_values_absent(payload, values)
        return canonical_json(payload)


def _run_payload(record: RunRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sequence": record.sequence,
        "mode": record.mode,
        "contract_version": record.contract_version,
        "status": record.status,
        "summary": record.summary,
        "report": record.report,
    }
    if record.group is not None:
        payload["group"] = record.group
    return payload
