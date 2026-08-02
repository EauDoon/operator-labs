# Threat model

TraceCanary is intended to detect a narrow regression: a known, synthetic sentinel that was planted before a telemetry pipeline appears in a later OTLP/HTTP JSON trace export. It also detects configured forbidden attribute keys or paths, and missing operational fields.

## Assumptions

- The operator chooses synthetic canary values that are unique to the test run and never uses personal or production values as canaries.
- The input is a local OTLP/HTTP JSON trace export and is untrusted until validated.
- The contract accurately states fields that are disallowed and fields that must remain available for operations.
- A passing baseline is a meaningful point of comparison for the candidate.

## Defenses

- Duplicate JSON object keys fail closed.
- File-size and nesting limits fail closed before trace analysis.
- Unsupported contract and semantic-convention versions return unresolved status.
- Reports omit matched canary values even when a check fails.
- Input ordering cannot change JSON report byte order.

## Out of scope threats

- A secret or identifier that was not configured as a canary.
- Leakage through telemetry formats other than supported OTLP/HTTP JSON traces.
- Data loss before or after the inspected export.
- An adversary who changes the contract, the checker binary, or the test fixture.
- Service availability under maliciously large inputs beyond the configured parser limits or host process limits.
