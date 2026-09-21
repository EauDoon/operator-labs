# Changelog

All notable changes to Operator Labs (Corridor Lab and TraceCanary) are
documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file consolidates content previously split across `RELEASE-NOTES.md`
(release drafts) and `PROGRESS.md` (development status). Both source files
are now deprecated; see the deprecation note at the top of each.

## [Unreleased]

The next release is currently drafted as `0.3.0` pending owner approval.
Nothing here is published until the owner approves the release (see
`RELEASE-CHECKLIST.md`).

### Added

#### Corridor Lab

- **Saved local projects.** Portable `corridor-lab.project/v1` manifests
  bundle a scenario, route selection, baseline, named variants, and saved
  experiment configurations with relative paths and SHA-256 input
  fingerprints. Create, validate, open, and rerun from the CLI or the
  desktop; moving a self-contained project directory keeps it valid, and
  missing or modified inputs are reported instead of silently accepted.
  Reports cannot replace project inputs or land inside the project
  directory.
- **Scenario variants.** Derived variants apply controlled changes to
  declared transaction and route fields while preserving every other
  field, with an exact-decimal assumption diff before any result and a
  variant comparison across the declared set (currencies, units,
  guardrail satisfaction; declared cases, never a representative
  distribution, no composite score). `run-variants` reruns a saved
  experiment per variant.
- **Target and constraint analysis.** `target-search` evaluates declared
  candidate values against declared constraints per route (sender-cost
  ceiling, recipient floor, deadline probability, tail hours), reporting
  per-candidate rows, invalid candidates, the smallest tested feasible
  value per route (explicitly not an optimum), and unreachable tested
  sets. `robustness-review` checks constraints across supplied scenarios
  and names each route's first failing scenario.
- **Desktop workbench.** Four-tab workbench with structured
  exact-decimal transaction editing, saved projects, variants, targets,
  robustness, evidence export, and find-in-report. All desktop
  report/evidence exports carry the same input-collision protection as
  the CLI.

#### TraceCanary

- **Saved local projects.** Portable `tracecanary.project/v1` manifests
  hold the contract, synthetic inputs, baseline/candidate references,
  batch configuration, coverage thresholds, and population gates —
  fingerprinted and portable.
- **Regression campaigns.** One bounded pass over existing checkers and
  the batch engine with separate phase meanings (contract, control,
  baseline, candidates, batch, population gate). A failing baseline is
  never used; `project promote-baseline` promotes only validated
  passing candidates. Value-free deterministic summaries save
  explicitly; summary comparison enforces compatibility (same contract
  version) and aggregates findings by value-free code as persistent,
  resolved, or new.
- **Contract authoring and diagnosis.** `contract template` and
  `contract review` (conservative, actionable, value-free diagnostics:
  retention conflicts, malformed wildcard paths, paths stopping before
  a value, shadowed forbidden keys). The desktop gains a transactional
  contract editor whose save action is explicitly labeled as writing
  canary configuration.
- **Evidence exports.** Value-free evidence bundles (campaign summary,
  thresholds, tool version, limitations) that never bundle canary
  values, contracts, or trace inputs.

#### Both packages

- CI now runs on Linux, Windows, and macOS for Python 3.11 and 3.12.
- Measured bounded workloads are recorded in PROGRESS.md; results sit
  well inside all declared bounds.

### Changed

- Known platform limitation: full manual visual/interaction testing was
  performed on macOS arm64 only; Windows coverage includes an
  automated real-window background-batch regression in CI.

### Deprecated

- None.

### Removed

- None.

### Fixed

- **Corridor Lab (Milestone 8).** Materializing a variant mutated the
  caller's declared base data, so later assumption diffs lied;
  materialization is now deep-copied and a regression proves the base is
  never mutated.
- **TraceCanary (Milestone 8).** `promote-baseline` was calling the
  fingerprint helper with the wrong signature; regression added.

### Security

- None.

### Compatibility

- Python 3.11+; standard-library runtime; offline; no new entry points
  removed; all existing command names, report contracts, deterministic
  outputs, and status semantics preserved.

## Milestone history

This section preserves the milestone-by-milestone development record
previously maintained in `PROGRESS.md`. The program branch was
`dev/program-cycle-1` (from `main` at `45776ea`, the PR #30 merge).

### Baseline (PR #30 merged)

- Desktop workbenches with tabbed workflows, protected atomic report
  exports with tracked-input collision guards, exact-decimal structured
  transaction editing, controller/CLI report agreement, shared bounded
  batch engine with background execution and main-thread-only widget
  updates, synthetic starter bundles covering every acceptance case.
  Verified merged via PR #30.
- Baseline verification: corridor-lab 141 tests, tracecanary 151 tests,
  compile checks, both GUI smoke tests from the checkout and from clean
  installed packages with `PYTHONPATH` unset.

### Milestone 1: reusable local projects (complete pending PR)

Design decisions (lasting rationale):

- Each package gets its own project manifest format; no shared runtime:
  `corridor-lab.project/v1` and `tracecanary.project/v1`. Manifests are
  strict canonical JSON with explicit bounds and duplicate-key
  rejection, like every other package input.
- Relative paths resolve against the project directory; moving a
  self-contained directory keeps it valid. Absolute paths are refused so
  a project stays portable.
- Every referenced input stores a SHA-256 content fingerprint at save
  time; opening reports missing or modified inputs instead of silently
  accepting them. Fingerprints detect change, they never claim identity
  of entities.
- Result evidence stays out of the manifest. Reopening a project must
  not imply an old report describes current inputs; reports carry their
  own declared inputs and the GUI clears stale results on reopen.
- Saving is explicit: create/save-as write to a user-chosen location and
  refuse to replace an existing manifest silently.
- The same source chosen twice (input == baseline) is stored once and
  referenced twice; distinct sources with colliding names are refused.

Implemented (corridor-lab): `projects.py` library, CLI
`project create|validate|open|add-experiment|run` (combined
deterministic project-run reports; reports protected against replacing
inputs or landing inside the project), controller open/save/run, GUI
Open Project / Save Project As / saved-experiment section with a
transactional save-current-settings dialog. Acceptance flow verified
from the installed package: create -> close -> move -> reopen ->
identical deterministic rerun; modified inputs refuse to run with clear
diagnostics.

Implemented (tracecanary): `project.py` library (contract, input,
baseline, candidate, batch directory with tree fingerprints, coverage
threshold, population gate), CLI `project create|validate|open`,
controller open/save, GUI Open Project / Save Project As on the Files
tab. Acceptance flow verified from the installed package including
value-free human summaries.

Corridor tests: 157. TraceCanary tests: 164. Both suites, compile
checks, and GUI smoke tests green at commit `2569645`.

### Milestone 2: Corridor Lab scenario experimentation (implemented on `dev/scenario-experimentation`, base: `dev/program-cycle-1`)

- `variants.py`: derived variants with strict change validation
  (transaction fields plus declared route fee/spread/liquidity fields),
  materialization that preserves every unchanged field, exact-decimal
  assumption diffs, and a variant-comparison analysis table with
  currencies, units, guardrail satisfaction, and an explicit
  not-a-distribution note. No composite score.
- Manifest variants section accepts file references (existing) or
  derived specs (`base: "scenario"` only; chained bases deferred).
- CLI: `project add-variant | show-variant | compare-variants |
  run-variants` with the same input protection as other project
  commands.
- Desktop: variants section on the Investigate tab (Show Assumption
  Diff, Apply Variant, Compare Variants); applied variants are
  in-memory, unsaved, and clearly labeled; controller/CLI agreement
  asserted.
- Corridor tests: 171. Real-window drive passed on macOS arm64.

### Milestone 3: target and constraint analysis (implemented)

- `targeting.py`: strict constraint grammar (four kinds, op enforced per
  kind, currencies attached to cost/amount units), `target_search` over
  declared candidate sets with invalid-candidate reporting, per-route
  summaries ("smallest tested feasible value" — explicitly not an
  optimum — and `unreachable_within_tested_set`), row budget preserved;
  and `robustness_review` across supplied scenarios with matching
  currencies and first-failing-scenario per route. Declared cases,
  never forecasts.
- CLI: `target-search` and `robustness-review` (multiple scenario
  files; report-input protection extended to multi-file commands).
- Desktop: Target Search and Robustness Across Project Scenarios in
  the Investigate tab; the robustness case set is the base scenario
  plus derived variants.
- Hand-derived expected-cost check (fixed + percent + carry/volume +
  loss) and boundary tests: corridor-lab at 182 tests. Real-window
  drive passed.

### Milestone 4: TraceCanary regression campaigns (implemented)

- `campaign.py`: one bounded pass over existing checkers and the batch
  engine. Phases with separate meanings (contract, control, baseline,
  candidates, batch, population gate); a failing baseline is never
  used; unresolved precedence preserved; the combined document is
  re-checked against canary values. Value-free deterministic summaries
  save only through explicit actions; `compare_summaries` performs
  strict compatibility checks (same contract version, summary version)
  and aggregates findings by value-free code as
  persistent/resolved/new with no entity identity implied.
- CLI: `campaign run [--save-summary]`, `campaign compare`, and
  `project promote-baseline` (explicit, validated promotion only).
- Desktop: new **Regression Campaign** tab (7) with background
  execution, main-thread-only widget updates, a new Control
  (unsanitized) selector, Save Summary As..., and Compare Saved
  Summaries.
- TraceCanary tests: 174. Real-window drive passed on macOS arm64.

### Milestone 5: contract development and diagnosis (implemented)

- `authoring.py`: the runtime validator stays authoritative; the
  review covers only what it cannot — retention conflicts with
  actionable rule locations, malformed wildcard paths, paths stopping
  before a scalar value, and forbidden keys shadowed by prefixes.
  Value-free (canary values never appear); passing review is not a
  privacy guarantee.
- CLI: `contract review`, `contract template` (never overwrites).
- Desktop: **Review Contract** and **Edit Contract JSON...** —
  transactional editor (template / load selected / validate / Save
  Contract As...) whose export is explicitly labeled as containing
  canary configuration, distinct from value-free report exports.
- TraceCanary tests: 183. Real-window drive passed on macOS arm64.

### Milestone 6: evidence exports and find-in-report (implemented)

- Corridor Lab `evidence.py`: Export Evidence bundles the current
  report verbatim with tool version, analysis identity, declared input
  sources, and standing limitations; atomic, size-bounded,
  input-collision protected.
- TraceCanary: Save Evidence bundles the value-free campaign summary,
  thresholds, tool version, limitations. The summary is rebuilt from
  known fields, the protected-value check runs before any write, and
  contracts/canaries/inputs are never bundled (hashes of protected
  values are not treated as anonymization).
- Both desktops gained find-in-report highlighting.
- Charts deliberately deferred (documented in ROADMAP): text-first
  tables keep exact values; no chart library is allowed beyond the
  standard library, and an ASCII approximation would obscure rather
  than clarify.
- Corridor 182 tests, TraceCanary 186 tests.

### Milestone 7: cross-platform reliability and performance (implemented)

- CI: macOS added to both package test matrices
  (ubuntu/windows/macos x 3.11/3.12). Portable Windows build workflows
  unchanged.
- New display-guarded window tests: batch results applied on the main
  thread, window closure during work leaves no crash or stale callback,
  repeated batch runs re-enable and re-run.
- Measured bounded workloads (macOS arm64, Python 3.11.16; observation
  only, scripts in each package's tests/measure_workloads.py): corridor
  transaction sweep (24 values x 6 routes) 0.0065 s, stress grid
  (2x24 cells x 6 routes) 0.0097 s, JSON render/parse ~0.4 ms each;
  tracecanary batch (32 files x ~120 KB) 0.0625 s. Well inside all
  bounds; no optimization required and none of the limits changed.

### Milestone 8: integrated journeys and release readiness (implemented)

- Corridor journey (installed package, `PYTHONPATH` unset): create
  project → stage and apply variants → truthful assumption diffs → run
  saved experiment → compare across variants → target search
  (smallest tested feasible value) → robustness across variants →
  export evidence → save-as → reopen in a fresh controller → rerun.
- TraceCanary journey (installed): contract template → review
  (actionable diagnostics) → project with thresholds → control check
  (labeled not a privacy pass) → leak detection → campaign →
  coverage gate → value-free summaries → comparison → value-free
  evidence → move → reopen → explicit validated baseline promotion.
- RELEASE-NOTES.md and RELEASE-CHECKLIST.md drafted (owner approval
  required for any release); root README gains a documentation map.
- Final suites: corridor 183 tests, tracecanary 189 tests, compile
  checks, GUI smoke tests — green at the final head.

### Program state (checkpoint, as preserved from PROGRESS.md)

- Branch `dev/scenario-experimentation`, head `828fbb4`; both workflows
  green (Linux/Windows/macOS x 3.11/3.12).
- PRs awaiting owner approval: #31 (M1, base main) and #32 (M2-M8
  commits, base dev/program-cycle-1). The developer never merges own
  work.
- All eight milestones implemented; integrated journeys verified from
  installed packages; release material prepared but nothing merged,
  tagged, or published.
- Resumption note: branch `dev/scenario-experimentation` at `93ad0cc`,
  CI green on both workflows, PRs #31 (M1, base main) and #32 (M2,
  base dev/program-cycle-1) open awaiting owner approval; M3-M5
  commits are stacked on the same branch and will appear in PR #32 or
  follow-ups.
- Await owner approval/merge of PRs #31/#32, then execute
  RELEASE-CHECKLIST.md.

### Verification commands (authoritative, from PROGRESS.md)

```text
cd packages/corridor-lab && PYTHONPATH=src python -m unittest discover -s tests -v && python -m compileall -q src
cd packages/tracecanary && python -m unittest discover -s tests -v && python -m compileall -q src
corridorlab-gui --smoke-test && tracecanary-gui --smoke-test   # after installation
```

### Blockers

None.

## Notes on this consolidation

- The `[Unreleased]` section above is the consolidated release draft
  (sourced from `RELEASE-NOTES.md`).
- The `Milestone history` section above is the consolidated development
  status (sourced from `PROGRESS.md`).
- Both source files now carry a single-line deprecation note at the top
  pointing readers to this CHANGELOG.md.
- No content has been invented; every entry traces back to
  `RELEASE-NOTES.md` or `PROGRESS.md`.
