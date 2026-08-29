# Method

TraceCanary evaluates an exported OTLP/HTTP JSON trace against a declared contract. It does not mutate the trace or the exporter configuration.

1. Load the contract with duplicate-key, size, nesting, field, and version checks.
2. Load and structurally validate an OTLP trace payload containing `resourceSpans`.
3. Walk every scalar value and compare each string by exact equality against each configured synthetic canary.
4. Extract resource, instrumentation-scope, span, event, and link attributes. Check exact forbidden keys and forbidden key prefixes.
5. Check configured wildcard JSON-pointer path prefixes when a matching scalar is populated.
6. Confirm each required retained field is present at its declared scope.
7. For `diff`, require the baseline to pass, then compare counts of every required retained field between baseline and candidate.

Reports are constructed from labels, categories, keys, scopes, paths, and stable error codes. Canary values are deliberately excluded from the report model and renderer.

The checker is deterministic: it does not use clocks, randomness, network state, or unordered report serialization. JSON output uses sorted keys, compact separators, and a final newline.
