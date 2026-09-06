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
