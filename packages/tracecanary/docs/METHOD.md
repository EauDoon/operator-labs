# Method

TraceCanary evaluates an exported OTLP/HTTP JSON trace against a declared contract. It does not mutate the trace or the exporter configuration.

1. Load the contract with duplicate-key, size, nesting, field, and version checks. `tracecanary/v1` and the additive `tracecanary/v2` are both accepted; v2 additionally accepts an optional `retention` object.
2. Load and structurally validate an OTLP trace payload containing `resourceSpans`. Duplicate attribute keys and duplicate span IDs fail closed. Validation failures name the failing JSON pointer in the error message.
3. Walk every scalar value and compare each string by exact equality against each configured synthetic canary.
4. Extract resource, instrumentation-scope, span, event, and link attributes. Check exact forbidden keys and forbidden key prefixes.
5. Check configured wildcard JSON-pointer path prefixes when a matching scalar is populated.
6. Confirm each required retained field is present at its declared scope.
7. For a v2 contract, evaluate each `retention` requirement against the attributes actually present: `TC010` when fewer than `minimum_count` matching attributes are present, `TC011` when a matching attribute's OTLP value kind is not one of the declared `value_types`.
8. For `diff`, require the baseline to pass, then compare counts of every required retained field between baseline and candidate.
9. For `diff` on a v2 contract with `retention`, apply each requirement's declared comparison mode: `presence` compares only against `minimum_count`; `count` reports `TC012` only on a strict decrease; `matched_ratio` partitions both traces by the keys declared in `matching_keys` and compares `numerator / denominator` per identity, reporting `TC013` on a strict decrease and `TC014` when the identity is not present in both populations or the declared denominator is zero.

Reports are constructed from labels, categories, keys, scopes, paths, counts, and stable error codes. Canary values are deliberately excluded from the report model and renderer. `TC010` and `TC011` report the requirement id, never a path or a value, and `TC012`/`TC013` report counts only.

The checker is deterministic: it does not use clocks, randomness, network state, or unordered report serialization. JSON output uses sorted keys, compact separators, and a final newline.

## Retention identity

`matched_ratio` never infers identity. An identity exists only where every key
declared in `matching_keys` is observed together with one item of the
requirement's declared scope. Items whose identity cannot be established from
declared keys, identities seen in only one of the two traces, and identities
whose declared denominator is zero are all reported as `TC014` with status
`unresolved` (exit status 2), because an unresolved comparison must never be
reported as a pass. Identity values themselves are trace data and are never
rendered.

## Summary, grouping, and filtering

`summarize`, `group_findings`, and `filter_findings` are pure functions over a
report document. They read no files, clocks, or environment, so the same report
always produces the same view.

- `summarize` reports `status`, `total`, `by_code`, `by_scope`, `by_category`,
  `by_key`, and whether the status is `unresolved`. `by_scope` and
  `by_category` count only findings that carry that field, because a finding
  with no scope has no scope to attribute it to.
- `group_findings` groups by `code`, `scope`, `category`, or `key`. Findings
  with no value for the chosen key are collected into the group whose value is
  the empty string, so grouping never silently drops a finding. An unknown key
  is rejected rather than grouped by accident.
- `filter_findings` returns a **new** report whose summary is recomputed to
  describe the filtered set.

**Filtering never changes the status.** Hiding a finding is a viewing decision,
not a re-run of the analysis, so a regression stays a regression even when every
finding is filtered out, and an unresolved comparison stays unresolved. Exit
codes are always decided from the unfiltered status. A `--filter-code` value
that TraceCanary cannot emit is rejected (exit status 2) instead of quietly
matching nothing, because a filter that matches nothing must not look like a
clean report. An empty selection applies no constraint for that field.

`explain` renders what was checked, what failed, and what remains unknown. It
states the two coverage caveats a reader cannot see from a report alone: canary
detection is exact matching of the declared values only, so any encoding, hash,
substring, reformatting, or other transformation is **not covered**; and `path`
pointers are structural and omit values by design, so they locate a finding
without echoing trace data. For `diff` it also separates what the baseline and
the candidate each contributed: the baseline must satisfy the contract before
any comparison is made, so it contributes the reference counts, while the
candidate contributes its own findings plus the comparison findings
(`TC005`/`TC012`/`TC013`, with `TC014` counted as unresolved rather than as a
comparison result).

## Run history

The desktop controller keeps a `RunHistory` in memory. Each recorded run is a
`RunRecord` with a 1-based `sequence` assigned in insertion order, the mode, the
contract version, the status, the summary, an optional declared `group` label,
and the report. There is no timestamp: two identical runs are distinguished only
by order, which is what keeps an export byte-stable.

The history is bounded (64 records by default). Appending past the bound is
rejected so a long session cannot grow without limit; the desktop controller
clears the history when the bound is reached rather than failing a run that
already produced a result. The history is never written by itself. Export is an
explicit user action that asks for a destination and writes only after one is
chosen; the exported text is checked against the canary values of every recorded
run first, so an export fails closed rather than emitting a protected value.

## Batch pairing

`tracecanary batch-diff` pairs two directories under one of two explicit rules.
Nothing is guessed.

- `filename` (default): pair by directory-relative POSIX path. The two relative
  name sets must be identical. A name present on only one side, and two names on
  one side that differ only by case, are unresolved pairing errors.
- `order`: pair the i-th baseline with the i-th candidate in the documented sort
  order (relative POSIX path casefolded, then exact). The two directories must
  contain the same number of files.

Both sides are discovered and sorted before pairing, so the pair order is fully
deterministic and independent of filesystem order. Every pair is loaded with the
contract's limits, structurally validated, and diffed. A pair that cannot be
loaded, validated, or compared becomes an unresolved item, and the batch status
is the strict aggregation: any unresolved item makes the batch `unresolved`
(exit 2), otherwise any `regression` makes it `regression` (exit 1), otherwise
`pass` (exit 0). A missing, duplicate, mismatched, invalid, or ambiguous pair
therefore can never produce an apparent pass.

The report is `tracecanary.batch-diff/v1`. It carries the declared `pairing`
mode and per-pair identifiers (`pair-0001`, ...). Host paths are never echoed:
only directory-relative POSIX names appear, and only with `--include-paths`. The
existing SARIF and JUnit renderers are reused unchanged.

## Contract-change review

`tracecanary contract-diff` answers one question: **what does TraceCanary check
differently under the new contract?** It is not a measurement of real-world
privacy in either direction, and every output carries that disclaimer.

Canaries are compared and reported **by label only**. A value is never emitted,
never echoed, and never used for anything but a private equality check that
detects whether a label now declares a different value.

Each described change is classified as `coverage_reduced`,
`coverage_increased`, or `coverage_changed`:

| Change | Classification |
|---|---|
| Canary label removed / added | reduced / increased |
| Canary category changed, or value replaced | changed |
| Forbidden key, key prefix, or path prefix removed / added | reduced / increased |
| `required_retained_fields` entry removed / added | reduced / increased |
| Retention requirement removed / added | reduced / increased |
| `minimum_count` lowered / raised | reduced / increased |
| `value_types` removed / widened | reduced |
| `value_types` declared / narrowed | increased |
| `value_types` changed to a set that neither contains the old nor is contained by it | changed |
| Comparison mode changed | changed |
| Matching key removed / added | reduced / increased |
| Denominator requirement changed | changed |
| Requirement `scope` or `key` changed | changed |
| `max_input_bytes`, `max_nesting`, `max_batch_files` changed | changed |
| `contract_version` or `semantic_conventions_version` changed | changed |

`value_types` is the set of **permitted** OTLP value kinds, so a narrower
permitted set rejects more inputs and is an increase in checking coverage, while
a wider one is a reduction. A limit change is always `coverage_changed`: a larger
`max_input_bytes` means larger inputs are accepted, not that checking got weaker
or stronger, and a smaller one means inputs that were once checked are now
rejected as unresolved.

The overall verdict is `coverage_reduced` if any change is a reduction, else
`coverage_increased` if any is an increase, else `coverage_unchanged`. Exit
status is 0 for unchanged or increased and 1 for reduced, because a
reduced-coverage contract is a real finding for a reviewer; invalid input exits
2. A `coverage_changed` entry that is neither a reduction nor an increase does
not by itself change the exit status.
