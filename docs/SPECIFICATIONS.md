# TraceCanary v1 specification

## Input contract

The supported contract version is `tracecanary/v1`; the supported semantic-convention snapshot is `opentelemetry/semconv/1.43.0`. Both identifiers must match exactly. The contract schema is provided in `schemas/contract.schema.json`; runtime validation is authoritative and requires no third-party JSON-schema library.

OpenTelemetry describes its GenAI semantic conventions as Development. TraceCanary pins this reviewed snapshot and checks only a narrow reviewed subset: OTLP JSON resource, instrumentation-scope, span, event, and link attributes used by its explicit contract. It does not implement the full semantic-convention registry. See the official [semantic conventions documentation](https://opentelemetry.io/docs/specs/semconv/) and [GenAI attribute registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/).

`canaries` is a non-empty list of unique objects with `label`, `category`, and `value`. The values are exact string sentinels. `forbidden_attribute_keys`, `forbidden_attribute_key_prefixes`, and `forbidden_path_prefixes` are optional unique string lists. Path prefixes use RFC 6901-style segments and allow `*` for one segment. `required_retained_fields` is a list of unique `{scope, key}` entries, where scope is `resource`, `span`, or `event`.

`limits.max_input_bytes` defaults to 5,000,000 and must be from 1,024 through 50,000,000. `limits.max_nesting` defaults to 100 and must be from 2 through 1,000.

## Supported trace shape

The top-level object contains only `resourceSpans`. Every resource span contains a `resource` object and `scopeSpans` list. Each scope span contains a `spans` list and may identify an instrumentation scope with attributes and a uint32 `droppedAttributesCount`. Every span has a string `name`, an optional `attributes` list, and optional event and link lists. Links may include attributes and uint32 `flags`. Every event has a string `name` and optional attributes list. Every inspected attribute has exactly `key` and `value` fields, with a non-empty string key and an object value.

This structural subset accepts the fields necessary for the stated v1 checks. Inputs outside the subset return exit code `2` rather than receiving partial analysis.

## Finding codes

| Code | Meaning |
| --- | --- |
| `TC001` | An exact synthetic canary survived the export. |
| `TC002` | A forbidden attribute key or key prefix is present. |
| `TC003` | A forbidden JSON-pointer path prefix reaches a scalar value. |
| `TC004` | A contract-required operational field is absent. |
| `TC005` | A candidate has fewer contract-required fields than a passing baseline. |
| `TC006` | A batch item could not be validated, so that item is unresolved. |
| `TC900` | The baseline does not satisfy the contract, so comparison is unresolved. |

## GUI guidance codes

The desktop GUI reserves `GUI001` through `GUI006` for local, safe guidance. These codes never contain selected paths, input values, parser detail, or matched canary values.

| Code | Meaning |
| --- | --- |
| `GUI001` | A contract selection is required for the requested action. |
| `GUI002` | An OTLP input selection is required for Check. |
| `GUI003` | A baseline selection is required for Diff. |
| `GUI004` | A candidate selection is required for Diff. |
| `GUI005` | A selected file could not be analyzed as supported JSON. |
| `GUI006` | An empty destination directory is required for synthetic starter files. |

The GUI may create synthetic starter files only after the user selects an empty destination directory. Its file mapping uses `safe-export.json` for Input and Baseline and `missing-operational-fields.json` for Candidate, so Diff demonstrates an intentional retained-field regression.

`check` returns `0` for no findings and `1` for findings. `diff` returns `2` when its baseline cannot provide a passing comparison point. Malformed files, duplicate keys, invalid structures, and unsupported versions return `2`.

## Determinism and disclosure

JSON reports have sorted object keys, fixed separators, and one trailing newline. Findings are ordered by code, path, label, and key. Reports never carry or render a matched canary value. Contract files may contain synthetic canary values by design and should be protected according to the test environment's needs.
