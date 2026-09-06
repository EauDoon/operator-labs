# Limitations

TraceCanary is a regression test, not a general privacy scanner or compliance tool.

- It matches only exact configured synthetic strings. Substrings, encodings, hashes, transformations, and unknown sensitive values are not detected unless represented by another explicit rule.
- Its OTLP reader supports only the trace JSON shape needed for resource, instrumentation-scope, span, event, and link attribute checks. It does not ingest protobuf, logs, or metrics.
- A forbidden path is evaluated against scalar values after structural validation. It is not a general JSON-policy engine.
- Baseline comparison uses counts of contract-required fields. It does not establish semantic equivalence of arbitrary spans or attributes.
- `tracecanary/v2` `retention` requirements count attributes by declared scope and key. A `TC010` count is taken over every matching attribute regardless of value kind; a wrong value kind is reported separately as `TC011`, so a trace can satisfy a count while still failing a type expectation.
- `matched_ratio` only groups by the keys a contract explicitly declares in `matching_keys`. An item missing any declared matching key has no identity and is reported as unresolved rather than being attributed to a group. Matching keys declared at a scope that is neither an ancestor nor a descendant of the requirement scope cannot be resolved at all.
- `matched_ratio` compares identities present in both traces only. A population that disappears entirely is unresolved (`TC014`), not a regression, so it is possible for a regression to be reported as unresolved instead of as a ratio drop.
- `TC014` makes a comparison `unresolved`, which exits 2. An unresolved result is a statement that the comparison could not be made, not evidence of a regression or of safety.
- A pass means this contract found no configured regression in this input. It does not demonstrate safety, redaction correctness, policy compliance, or absence of sensitive data.
- Input limits are guardrails, not a complete denial-of-service defense. Run untrusted files with appropriate host-level controls.
- The optional desktop GUI is a local view over the same checker. It requires a Tkinter-capable Python installation to open a window and does not provide additional analysis or privacy guarantees. Its starter-files action writes fictional fixtures only after the user selects an empty directory; it does not create or transform real traces.
