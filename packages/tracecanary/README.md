# TraceCanary

TraceCanary detects privacy regressions in OTLP/HTTP JSON trace exports using synthetic canaries and explicit, version-pinned contracts.

It is a deterministic offline checker for OTLP trace attributes. It searches for exact synthetic canary values and forbidden telemetry keys across resource, instrumentation-scope, span, span-event, and span-link attributes, blocks forbidden JSON path prefixes, and verifies operational fields at resource, span, and event scope.

TraceCanary uses only the Python standard library at runtime. It has no network client, credentials, telemetry, account requirement, or production-data fixture.

![Flow diagram showing a pinned privacy contract applied to baseline and candidate trace exports, producing pass, regression, or unresolved reports.](https://raw.githubusercontent.com/EauDoon/operator-labs/main/packages/tracecanary/.github/assets/project-overview.svg)

## Scope

Supported in v0.2.0:

- OTLP/HTTP JSON traces with `resourceSpans`.
- Exact synthetic-canary detection anywhere in a supported payload.
- Forbidden attribute keys, key prefixes, and wildcard JSON-pointer path prefixes.
- Required fields at resource, span, and event scope.
- Baseline-to-candidate retained-field count comparison.
- Stable JSON and human-readable reports.
- Bounded directory checks with deterministic JSON, SARIF, and JUnit output.

Not supported in v0.2.0:

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

On POSIX shells, use `PYTHONPATH=src python -m tracecanary.gui`. From a checkout on Windows, double-click [TraceCanary.pyw](TraceCanary.pyw) instead. The desktop window is organized as six keyboard-reachable tabs (`Ctrl+1` through `Ctrl+6`) around the questions an operator needs answered, with a shared result panel (human and JSON views plus `Save Report`) underneath:

1. **Files and Starters** — selectors for the contract, sanitized input trace, baseline, candidate, and a batch directory; `Run Built-in Demo` (an in-memory safe check) and `Create Synthetic Starter Files...`, which writes the fictional bundle into an empty directory you choose and prepares the selectors.
2. **Is the Contract Usable?** — `Validate` and `Inspect Contract` (value-free check inventory, limits, and direct retention conflicts).
3. **Were Canaries Exercised?** — `Check Positive Control` verifies that the unsanitized synthetic positive control contains every declared canary. A control pass is displayed as `CONTROL PASS` and only confirms canary exercise; it is never a privacy pass. Run `Check` on the separately sanitized export afterwards.
4. **Did the Candidate Leak?** — `Check Sanitized Export` (exact canary values, forbidden keys, forbidden path prefixes) and `Diff Baseline vs Candidate`.
5. **Did Telemetry Survive?** — `Coverage`, `Retention Matrix` (value-free structural pointers), `Dropped Telemetry` with an optional explicit zero gate, the `Coverage Gate` (explicit per-field retained-field ratio with population denominators; empty or invalid required populations stay unresolved), the `Population Gate`, and `Coverage Diff` (exact rates with both denominators; a decrease is a regression).
6. **Batch Directories** — `Run Batch Check` over the selected directory (bounded enumeration, no symlinked files, per-file results, unresolved precedence, optional baseline comparison, opt-in paths) and `Run Coverage Batch` (aggregate sums with an optional exact per-file ratio gate).

Reports are written only through `Save Report` after the user chooses a file path; synthetic files are written only through the explicit starter-files action after the user chooses an empty directory. Report destinations that would replace a tracked input (including symlinks and hard links) or sit inside a scanned batch directory are rejected before anything is written. The GUI calls TraceCanary library functions directly and never launches a subprocess.

`Run Built-in Demo` performs a safe synthetic check entirely in memory, so it works after installation without repository fixture files. `Create Synthetic Starter Files` requires a directory selected by the user, writes only the existing fictional fixture bundle to an empty directory, and then prepares the selectors. The starter files support a reproducible acceptance walk-through: `safe-export.json` passes, `leaked-*.json` each detect a leak, `missing-operational-fields.json` loses retained event fields, `sparse-retention.json` fails an explicit `coverage-gate` threshold (for example `--minimum-ratio 0.95`), `invalid-export.json` stays unresolved, and `positive-control.json` exercises every canary for `control-check`. The GUI calls TraceCanary library functions directly and never launches a subprocess.

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

## Saved local projects

`tracecanary project create --directory investigation --project-id fictional-campaign --contract contract.json [--input export.json] [--baseline before.json] [--candidate after.json] [--batch-dir exports --batch-recursive --batch-include-paths --batch-minimum-ratio 0.95] [--minimum-ratio 0.95] [--population-scope span --population-minimum 1]` saves a self-contained, portable project: the validated `tracecanary.project/v1` manifest plus explicitly copied synthetic inputs. Relative paths resolve against the project directory, and each input (including the batch directory) records a SHA-256 fingerprint, so `project validate` and `project open` explain missing or modified inputs instead of accepting them silently. Saved settings are separate from result evidence; the desktop **Open Project...** applies them to the selectors only, and reports still require an explicit save.

## Regression campaigns

`tracecanary campaign run PROJECT [--control control.json] [--save-summary summary.json]` runs one bounded campaign from a saved project: contract validity, canary exercise in the unsanitized positive control (a control pass confirms exercise, never a privacy pass), baseline validity (a failing baseline is never used), per-candidate privacy and retention findings, the batch directory through the bounded batch engine, and the configured coverage and population gates. Every phase keeps its own status; the campaign status applies unresolved precedence. Value-free, deterministic summaries are saved only through the explicit `--save-summary` action (outside the project directory), and `tracecanary campaign compare baseline.json candidate.json` compares two saved summaries after strict compatibility checks (same contract version), aggregating findings by value-free code as persistent, resolved, or new — no entity identity or causal attribution is implied. `tracecanary project promote-baseline PROJECT --candidate candidate.json` promotes a candidate to the project baseline only after the candidate satisfies the contract. The desktop **Regression Campaign** tab runs the same campaign over the current selectors, saves summaries, and compares saved summaries.

## Contract development and diagnosis

`tracecanary contract template --output new-contract.json` writes a minimal valid synthetic contract (never overwritten; replace the placeholder canary value before use). `tracecanary contract review draft.json` adds conservative, value-free diagnostics on top of the strict runtime validator: direct retention conflicts with actionable rule locations, malformed wildcard path prefixes that can never match, forbidden paths that stop before a scalar value, and forbidden exact keys shadowed by broader prefix rules. Every diagnostic names a safe structural location, explains the issue, and suggests a correction without weakening the contract; canary values never appear, and passing review is not a privacy guarantee. The desktop **Is the Contract Usable?** tab gains **Review Contract** and **Edit Contract JSON...** — a transactional editor with a minimal template, strict validation, and an explicit **Save Contract As...** action that is clearly labeled as writing canary configuration, distinct from value-free report exports.

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

`tracecanary dropped-telemetry --contract contract.json --input export.json --require-zero`
reports declared dropped attribute, event, and link counters by entity scope.
Without `--require-zero` the counters are descriptive; with it, any positive
counter produces TC014 and exit 1. Existing privacy findings still fail the check.
Absent counters count as zero according to the supported input representation;
they do not establish that a collector retained all telemetry.

`tracecanary population-gate --contract contract.json --input export.json --scope span --minimum 10`
requires at least the explicitly selected entity count while preserving every
normal privacy check. A smaller or empty population returns regression (1, TC013).
Supported scopes are resource, scope, span, event, and link; the integer minimum
must be from 1 to 1,000,000. This catches small samples that presence or ratio
checks alone can pass. It does not prove telemetry completeness or distinct identity.

`tracecanary control-check --contract contract.json --input unsanitized-control.json`
checks that **every** declared canary occurs as an exact scalar in a synthetic
positive control before sanitization. Missing canaries return unresolved (2),
including substrings the existing exact-match checker cannot detect. The value-free
report uses one-based canary ordinals and occurrence counts. PASS (0) means the
control exercised the canaries, **not** that it is privacy-safe. Run ordinary
`check` on the separately sanitized export; no collector is invoked or configured.

`tracecanary coverage-gate --contract contract.json --input export.json
--minimum-ratio 0.95 --format json` adds an explicit per-required-field entity
coverage gate. Decimal thresholds from 0 to 1 (at most six places) use exact
fraction comparisons. Sparse presence yields `TC011` and exit 1; zero populations
or no retention requirements are unresolved (exit 2), even at threshold zero.
Existing privacy findings still apply. The default checker remains unchanged.

`tracecanary inspect-contract contract.json --format json` inventories effective
limits and check counts without exposing canary values or field keys. Required
fields use stable ordinal IDs. Direct conflicts between required retention and
forbidden attribute keys/prefixes produce `TC010` and exit 1. This conservative
inspection does not prove the absence of every possible contract contradiction.

`tracecanary coverage --contract contract.json --input export.json --format json` runs the same privacy check and adds entity counts, attribute counts by scope, and required-field presence counts. Required IDs refer to the one-based order of `required_retained_fields` in the contract, without copying field keys into coverage metadata. Human output explains the counts. The existing checker requires presence somewhere in a scope; coverage reveals sparse presence across entities without changing that contract rule. Empty exports show zero counts, never implied coverage. Coverage is descriptive, not a completeness or compliance claim.

SARIF findings now retain redacted JSON-pointer locations in result properties and percent-encode artifact URI path characters. JUnit failures and errors include stable finding codes and pointers; `--include-paths` populates each test case file attribute. XML-invalid filename controls are replaced. Default artifacts use anonymous item IDs and contain no file paths. All emitted text remains subject to the protected-value check.

The desktop **Coverage** action uses the selected contract and input, preserves pass/regression/unresolved status, and shows the same value-free counts in Human and JSON views. Use **Save Report** for an explicit export. Missing selections give inline guidance; unreadable inputs show unresolved without disclosing input contents.

### Compare population coverage

`tracecanary coverage-diff --contract contract.json --baseline before.json --candidate after.json --format json`
compares exact retained-field fractions and reports both sample denominators. A decrease is TC012 even when raw presence counts stay constant. Invalid baselines or empty required populations are unresolved. This opt-in command compares samples, not matched entity identities or causal effects; existing `diff` semantics remain unchanged.

### Locate sparse retention

Required retained fields also accept `scope` and `link`. These opt-in rules flow
through check, diff, coverage, gates, batches, and retention matrices just like
resource/span/event fields. Each `scopeSpans` group is one scope population, even
when its optional `scope` object is absent; a missing object has no attributes.
Links with no attribute list remain in the link denominator and missing-path list.

`tracecanary retention-matrix --contract contract.json --input export.json --format json`
shows missing entity locations by required-field ordinal and structural JSON pointer. It includes entities with absent attribute arrays, exposes no attribute keys or values, and rejects more than 10,000 entity-requirement checks instead of truncating. Matrix coverage is descriptive; use `coverage-gate` to enforce per-entity coverage.

### Aggregate bounded batch coverage

Add `--minimum-ratio 0.95` to apply `coverage-gate` independently to **every** file.
An aggregate ratio cannot conceal an individual sparse export. Existing exact
threshold validation, privacy findings, and unresolved empty-population behavior
apply per file. Human and JSON summaries name the per-file threshold alongside
aggregate counts. Omitting the option preserves descriptive batch coverage.
`validated_items` counts structurally valid exports, `unresolved_items` counts
all unresolved results, and `excluded_items` counts malformed inputs omitted from
aggregate denominators. A valid empty export can be an unresolved gate result
without being excluded from the coverage input count.

`tracecanary coverage-batch --contract contract.json --input-dir exports --format json`
uses the same strict file, nesting, symlink and file-count bounds as `batch`. Each valid export includes normal privacy findings plus coverage. The aggregate sums presence counts and entity denominators, rather than averaging percentages. Invalid items are unresolved and explicitly excluded from aggregate denominators; an empty denominator has a null ratio. Counts describe the supplied files and may double-count repeated entities across exports. Paths remain opt-in. Human and JSON formats are supported; no production telemetry or collection is enabled.
