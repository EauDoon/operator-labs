# Release notes (draft, awaiting owner approval)

This draft covers the changes on `dev/scenario-experimentation` since the
merge of PR #30 (`45776ea`). Nothing here is published until the owner
approves a release.

## Corridor Lab

### New: saved local projects
Portable `corridor-lab.project/v1` manifests bundle a scenario, route
selection, baseline, named variants, and saved experiment configurations
with relative paths and SHA-256 input fingerprints. Create, validate, open,
and rerun from the CLI or the desktop; moving a self-contained project
directory keeps it valid, and missing or modified inputs are reported
instead of silently accepted. Reports cannot replace project inputs or land
inside the project directory.

### New: scenario variants
Derived variants apply controlled changes to declared transaction and route
fields while preserving every other field, with an exact-decimal assumption
diff before any result and a variant comparison across the declared set
(currencies, units, guardrail satisfaction; declared cases, never a
representative distribution, no composite score). `run-variants` reruns a
saved experiment per variant.

### New: target and constraint analysis
`target-search` evaluates declared candidate values against declared
constraints per route (sender-cost ceiling, recipient floor, deadline
probability, tail hours), reporting per-candidate rows, invalid candidates,
the smallest tested feasible value per route (explicitly not an optimum),
and unreachable tested sets. `robustness-review` checks constraints across
supplied scenarios and names each route's first failing scenario.

### Desktop
Four-tab workbench with structured exact-decimal transaction editing,
saved projects, variants, targets, robustness, evidence export, and
find-in-report. All desktop report/evidence exports carry the same
input-collision protection as the CLI.

## TraceCanary

### New: saved local projects
Portable `tracecanary.project/v1` manifests hold the contract, synthetic
inputs, baseline/candidate references, batch configuration, coverage
thresholds, and population gates — fingerprinted and portable.

### New: regression campaigns
One bounded pass over existing checkers and the batch engine with separate
phase meanings (contract, control, baseline, candidates, batch, population
gate). A failing baseline is never used; `project promote-baseline`
promotes only validated passing candidates. Value-free deterministic
summaries save explicitly; summary comparison enforces compatibility
(same contract version) and aggregates findings by value-free code as
persistent, resolved, or new.

### New: contract authoring and diagnosis
`contract template` and `contract review` (conservative, actionable,
value-free diagnostics: retention conflicts, malformed wildcard paths,
paths stopping before a value, shadowed forbidden keys). The desktop gains
a transactional contract editor whose save action is explicitly labeled as
writing canary configuration.

### New: evidence exports
Value-free evidence bundles (campaign summary, thresholds, tool version,
limitations) that never bundle canary values, contracts, or trace inputs.

## Both

- CI now runs on Linux, Windows, and macOS for Python 3.11 and 3.12.
- Measured bounded workloads are recorded in PROGRESS.md; results sit well
  inside all declared bounds.
- Known platform limitation: full manual visual/interaction testing was
  performed on macOS arm64 only; Windows coverage includes an automated
  real-window background-batch regression in CI.

## Compatibility

- Python 3.11+; standard-library runtime; offline; no new entry points
  removed; all existing command names, report contracts, deterministic
  outputs, and status semantics preserved.
