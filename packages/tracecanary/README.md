# TraceCanary

TraceCanary detects privacy regressions in OTLP/HTTP JSON trace exports using synthetic canaries and explicit, version-pinned contracts.

It is a deterministic offline checker for OTLP trace attributes. It searches for exact synthetic canary values and forbidden telemetry keys across resource, instrumentation-scope, span, span-event, and span-link attributes, blocks forbidden JSON path prefixes, and verifies operational fields at resource, span, and event scope.

TraceCanary uses only the Python standard library at runtime. It has no network client, credentials, telemetry, account requirement, or production-data fixture.

![Flow diagram showing a pinned privacy contract applied to baseline and candidate trace exports, producing pass, regression, or unresolved reports.](https://raw.githubusercontent.com/EauDoon/operator-labs/main/packages/tracecanary/.github/assets/project-overview.svg)

## Scope

Supported in v0.1.1:

- OTLP/HTTP JSON traces with `resourceSpans`.
- Exact synthetic-canary detection anywhere in a supported payload.
- Forbidden attribute keys, key prefixes, and wildcard JSON-pointer path prefixes.
- Required fields at resource, span, and event scope.
- Baseline-to-candidate retained-field count comparison.
- Stable JSON and human-readable reports.
- Bounded directory checks with deterministic JSON, SARIF, and JUnit output.

Not supported in v0.1.1:

- Protobuf, logs, metrics, collector execution, or redaction.
- Generic secret or PII discovery.
- Real production traces or a privacy-law compliance determination.
- A claim that no sensitive data can leak.

## Desktop GUI

Install a local checkout before starting the desktop interface:

```text
python -m pip install .
```

Then run:

```text
tracecanary-gui
```

If the installed launcher is unavailable, use the module fallback:

```text
python -m tracecanary.gui
```

From a fresh checkout without installation, first expose `src` to Python, then use the fallback:

```powershell
$env:PYTHONPATH = "src"
python -m tracecanary.gui
```

On POSIX shells, use `PYTHONPATH=src python -m tracecanary.gui`. From a checkout on Windows, double-click [TraceCanary.pyw](TraceCanary.pyw) instead. The first screen provides file selectors for a contract, input, baseline, and candidate; `Validate`, `Check`, and `Diff` actions; an explicit pass, regression, or unresolved status; human and JSON report views; and a `Save Report` action. Reports are written only through `Save Report` after the user chooses a file path; synthetic files are written only through the explicit starter-files action after the user chooses an empty directory.

`Run Built-in Demo` performs a safe synthetic check entirely in memory, so it works after installation without repository fixture files. `Create Synthetic Starter Files` requires a directory selected by the user, writes only the existing fictional fixture bundle to an empty directory, and then prepares the selectors for a safe baseline and a retention-regression candidate. The GUI calls TraceCanary library functions directly and never launches a subprocess.

For a headless installation check that does not create a window:

```text
tracecanary-gui --smoke-test
```

From a checkout, use `PYTHONPATH=src python -m tracecanary.gui --smoke-test` on POSIX or set `$env:PYTHONPATH = "src"` first in PowerShell.

## Quick start

From a checkout, use the source tree directly:

```powershell
$env:PYTHONPATH = "src"
python -m tracecanary validate fixtures/v1/contract.json
python -m tracecanary check --contract fixtures/v1/contract.json --input fixtures/v1/safe-export.json --format json
python -m tracecanary diff --contract fixtures/v1/contract.json --baseline fixtures/v1/safe-export.json --candidate fixtures/v1/missing-operational-fields.json
```

On POSIX shells, replace the first line with `PYTHONPATH=src` before each command or export it for the session. Installing the package also provides the `tracecanary` and `tracecanary-gui` commands.

After local installation, the synthetic fixture writer creates an empty, self-contained fixture directory:

```text
tracecanary fixture create --output example
```

It refuses a non-empty output directory. From a fresh checkout, set `PYTHONPATH=src` before using `python -m tracecanary fixture create --output example`. All generated values are fictional.

## Commands and exit status

After installation, use:

```text
tracecanary validate contract.json
tracecanary check --contract contract.json --input export.json
tracecanary diff --contract contract.json --baseline safe.json --candidate changed.json
tracecanary batch --contract contract.json --input-dir exports --format sarif
tracecanary fixture create --output example/
tracecanary-gui
```

From a fresh checkout, set `PYTHONPATH=src` and replace `tracecanary` with `python -m tracecanary`; use `python -m tracecanary.gui` for the GUI. `0` means the contract is satisfied. `1` means a privacy or retention regression was detected. `2` means invalid input, an unsupported version, or an unresolved comparison. Invalid OTLP structure, including duplicate attribute keys and duplicate span IDs, is reported with a JSON pointer to the failing resource, span, event, link, or attribute; pointers never include span names or attribute keys.

`validate`, `check`, and `diff` accept `--format human` (default) or `--format json`. `batch` accepts `--format json` (default), `human`, `sarif`, or `junit`; `--recursive` includes `*.json` files in subdirectories; `--include-paths` adds directory-relative POSIX paths to JSON, SARIF, and JUnit items. Batch input is bounded by `limits.max_batch_files` (default 256). Batch `human` output is a per-item status rollup and does not repeat finding labels.

A single-trace JSON report contains `contract_version`, `mode`, `status`, `summary`, and `violations`. Each finding has `code`, `message`, and `path`, plus `label`/`category` or `key`/`scope` when they apply. Reports never include the matched canary value.

## Contract overview

The JSON contract is strict. Unknown fields, duplicate keys, unsupported versions, empty canary sets, and malformed limits are rejected. The supported identifiers are `tracecanary/v1` and `opentelemetry/semconv/1.43.0`.

```json
{
  "contract_version": "tracecanary/v1",
  "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
  "canaries": [{"label": "test-prompt", "category": "prompt", "value": "TCANARY_EXAMPLE_123"}],
  "forbidden_attribute_keys": ["gen_ai.prompt"],
  "forbidden_attribute_key_prefixes": ["enduser."],
  "forbidden_path_prefixes": ["/resourceSpans/*/scopeSpans/*/spans/*/attributes/*/value/bytesValue"],
  "required_retained_fields": [{"scope": "resource", "key": "service.name"}]
}
```

`*` matches one JSON-pointer path segment. A path prefix is checked only when it reaches a scalar value. Exact canaries are checked against every string scalar in the validated trace payload.

See [the contract schema](schemas/contract.schema.json), [method](docs/METHOD.md), [threat model](docs/THREAT_MODEL.md), [limitations](docs/LIMITATIONS.md), and [specification](docs/SPECIFICATIONS.md).

## Repository map

- `src/tracecanary/` contains the CLI, contract checker, reports, fixture bundle, and GUI controller/window modules.
- `TraceCanary.pyw` is the Windows double-click checkout launcher.
- `fixtures/v1/` contains synthetic contracts, trace inputs, and expected reports.
- `tests/` contains standard-library unit and controller tests.
- `schemas/` and `docs/` contain the contract schema and method boundaries.

## Development checks

After local installation, or after setting `PYTHONPATH=src` in a checkout, run:

```text
python -m unittest discover -s tests -v
python -m compileall -q src
python -m tracecanary.gui --smoke-test
```

The GitHub Actions workflow runs the suite on Windows and Linux, installs the local package without runtime dependencies, checks the CLI, and runs the GUI smoke test.

## License

Apache-2.0. See [LICENSE](LICENSE).

## Explicit report files

`validate`, `check`, `diff`, and `batch` accept `--output FILE`. Reports are fully rendered and privacy-checked before atomic UTF-8 replacement; stdout stays empty on successful file output. Outputs cannot alias inputs, and batch output must be outside the scanned directory. The parent directory must already exist. Exit codes retain their usual meaning, including regression reports written with exit 1.

## Compare many exports to a baseline

`tracecanary batch --contract contract.json --baseline baseline.json --input-dir candidates --format junit --output regression.xml` checks every candidate against one passing synthetic baseline. Baseline input is validated before candidates; a failing baseline returns unresolved. Each candidate retains privacy and retained-field checks, and malformed candidates do not hide other results. A batch containing any unresolved item returns 2; otherwise any regression returns 1. The same size, nesting, count, redaction, and path-opt-in rules apply.

## Inspect coverage

`tracecanary coverage --contract contract.json --input export.json --format json` runs the same privacy check and adds entity counts, attribute counts by scope, and required-field presence counts. Required IDs refer to the one-based order of `required_retained_fields` in the contract, without copying field keys into coverage metadata. Human output explains the counts. The existing checker requires presence somewhere in a scope; coverage reveals sparse presence across entities without changing that contract rule. Empty exports show zero counts, never implied coverage. Coverage is descriptive, not a completeness or compliance claim.

SARIF findings now retain redacted JSON-pointer locations in result properties and percent-encode artifact URI path characters. JUnit failures and errors include stable finding codes and pointers; `--include-paths` populates each test case file attribute. XML-invalid filename controls are replaced. Default artifacts use anonymous item IDs and contain no file paths. All emitted text remains subject to the protected-value check.
