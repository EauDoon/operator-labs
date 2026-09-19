# Operator Labs development status

Program: sustained multi-cycle build per [ROADMAP.md](ROADMAP.md).
Merged state: PRs #31/#32 (the full eight-milestone program) are merged into
`main` at `28a6951` with owner approval; post-merge CI green. Earlier
program milestones (M1-M8) and their verification evidence are recorded in
git history on this file and in the PRs.

## Cycle 2 (branch `dev/cycle-2`, from main at `28a6951`)

Fresh-review findings and completed work:

1. **Campaign-summary compatibility was weaker than the Milestone 4 intent**
   (contract version only). Fixed: summaries now record the required
   retained-field identity (scope and key pairs — contract keys are
   configuration, not protected values) and the configured coverage
   threshold and population definition; `campaign compare` rejects each
   incompatible pair as unsupported with a specific explanation, and the
   comparison document records the shared identity. TraceCanary at 191
   tests.
2. **TraceCanary README desktop section was stale** (six tabs; no campaign
   tab, control selector, contract editor, or find-in-report). Rewritten for
   the current seven-tab interface.
3. **Corridor Lab portfolio batch was CLI-only.** The bounded batch engine
   moved to a shared `batching.py`; the desktop Compare Routes tab gains
   Portfolio Batch with directory selection, recursive/include-paths
   options, per-file results, unresolved precedence, and reports kept
   outside the scanned directory. Controller output is byte-identical with
   the CLI (asserted). Corridor at 185 tests.
4. **CLI evidence exports (Corridor Lab).** Every report-emitting command
   accepts `--evidence FILE` to additionally write the self-explaining
   evidence document with the same input-collision protection as reports;
   documented in the README, with regressions for the standard flow, batch
   and robustness exports, and collision refusals. Corridor at 187 tests.

## Cycle-2 heads

- PR #39 green and mergeable at `c810ae5`; PR body updated to cover all
  three-plus-one items.

Deferred (still): per-run history inside project manifests, zip-based
evidence bundles, ASCII chart approximations.

## Milestone 3: target and constraint analysis (implemented)

- `targeting.py`: strict constraint grammar (four kinds, op enforced per
  kind, currencies attached to cost/amount units), `target_search` over
  declared candidate sets with invalid-candidate reporting, per-route
  summaries ("smallest tested feasible value" — explicitly not an optimum —
  and `unreachable_within_tested_set`), row budget preserved; and
  `robustness_review` across supplied scenarios with matching currencies and
  first-failing-scenario per route. Declared cases, never forecasts.
- CLI: `target-search` and `robustness-review` (multiple scenario files;
  report-input protection extended to multi-file commands).
- Desktop: Target Search and Robustness Across Project Scenarios in the
  Investigate tab; the robustness case set is the base scenario plus derived
  variants.
- Hand-derived expected-cost check (fixed + percent + carry/volume + loss)
  and boundary tests: corridor-lab at 182 tests. Real-window drive passed.

Next: documentation checkpoint, push, wait for CI, then Milestone 4
(TraceCanary regression campaigns).

## Milestone 4: TraceCanary regression campaigns (implemented)

- `campaign.py`: one bounded pass over existing checkers and the batch
  engine. Phases with separate meanings (contract, control, baseline,
  candidates, batch, population gate); a failing baseline is never used;
  unresolved precedence preserved; the combined document is re-checked
  against canary values. Value-free deterministic summaries save only
  through explicit actions; `compare_summaries` performs strict
  compatibility checks (same contract version, summary version) and
  aggregates findings by value-free code as persistent/resolved/new with no
  entity identity implied.
- CLI: `campaign run [--save-summary]`, `campaign compare`, and
  `project promote-baseline` (explicit, validated promotion only).
- Desktop: new **Regression Campaign** tab (7) with background execution,
  main-thread-only widget updates, a new Control (unsanitized) selector,
  Save Summary As..., and Compare Saved Summaries.
- TraceCanary tests: 174. Real-window drive passed on macOS arm64.

Next: push, wait for CI, then Milestone 5 (contract development and
diagnosis).

## Milestone 5: contract development and diagnosis (implemented)

- `authoring.py`: the runtime validator stays authoritative; the review
  covers only what it cannot — retention conflicts with actionable rule
  locations, malformed wildcard paths, paths stopping before a scalar value,
  and forbidden keys shadowed by prefixes. Value-free (canary values never
  appear); passing review is not a privacy guarantee.
- CLI: `contract review`, `contract template` (never overwrites).
- Desktop: **Review Contract** and **Edit Contract JSON...** — transactional
  editor (template / load selected / validate / Save Contract As...) whose
  export is explicitly labeled as containing canary configuration, distinct
  from value-free report exports.
- TraceCanary tests: 183. Real-window drive passed on macOS arm64.

Next: Milestone 6 (explainable results and evidence exports), then
M7/M8. Resumption note: branch `dev/scenario-experimentation` at
`93ad0cc`, CI green on both workflows, PRs #31 (M1, base main) and #32 (M2,
base dev/program-cycle-1) open awaiting owner approval; M3-M5 commits are
stacked on the same branch and will appear in PR #32 or follow-ups.

## Milestone 6: evidence exports and find-in-report (implemented)

- Corridor Lab `evidence.py`: Export Evidence bundles the current report
  verbatim with tool version, analysis identity, declared input sources, and
  standing limitations; atomic, size-bounded, input-collision protected.
- TraceCanary: Save Evidence bundles the value-free campaign summary,
  thresholds, tool version, limitations. The summary is rebuilt from known
  fields, the protected-value check runs before any write, and contracts/
  canaries/inputs are never bundled (hashes of protected values are not
  treated as anonymization).
- Both desktops gained find-in-report highlighting.
- Charts deliberately deferred (documented in ROADMAP): text-first tables
  keep exact values; no chart library is allowed beyond the standard
  library, and an ASCII approximation would obscure rather than clarify.
- Corridor 182 tests, TraceCanary 186 tests.

## Milestone 7: cross-platform reliability and performance (implemented)

- CI: macOS added to both package test matrices (ubuntu/windows/macos x
  3.11/3.12). Portable Windows build workflows unchanged.
- New display-guarded window tests: batch results applied on the main
  thread, window closure during work leaves no crash or stale callback,
  repeated batch runs re-enable and re-run.
- Measured bounded workloads (macOS arm64, Python 3.11.16; observation only,
  scripts in each package's tests/measure_workloads.py): corridor
  transaction sweep (24 values x 6 routes) 0.0065 s, stress grid (2x24
  cells x 6 routes) 0.0097 s, JSON render/parse ~0.4 ms each; tracecanary
  batch (32 files x ~120 KB) 0.0625 s. Well inside all bounds; no
  optimization required and none of the limits changed.

Next: Milestone 8 (integrated journeys + release readiness), then the
program report.

## Milestone 8: integrated journeys and release readiness (implemented)

- Corridor journey (installed package, `PYTHONPATH` unset): create project →
  stage and apply variants → truthful assumption diffs → run saved
  experiment → compare across variants → target search (smallest tested
  feasible value) → robustness across variants → export evidence → save-as
  → reopen in a fresh controller → rerun. Found and fixed a real defect:
  materializing a variant mutated the caller's declared base data, so later
  assumption diffs lied; materialization is now deep-copied and a
  regression proves the base is never mutated.
- TraceCanary journey (installed): contract template → review (actionable
  diagnostics) → project with thresholds → control check (labeled not a
  privacy pass) → leak detection → campaign → coverage gate → value-free
  summaries → comparison → value-free evidence → move → reopen → explicit
  validated baseline promotion. Found and fixed `promote-baseline` calling
  the fingerprint helper with the wrong signature; regression added.
- RELEASE-NOTES.md and RELEASE-CHECKLIST.md drafted (owner approval
  required for any release); root README gains a documentation map.
- Final suites: corridor 183 tests, tracecanary 189 tests, compile checks,
  GUI smoke tests — green at the final head.

## Program state (checkpoint)

- Branch `dev/scenario-experimentation`, head `828fbb4`; both workflows
  green (Linux/Windows/macOS x 3.11/3.12).
- PRs awaiting owner approval: #31 (M1, base main) and #32 (M2-M8 commits,
  base dev/program-cycle-1). The developer never merges own work.
- All eight milestones implemented; integrated journeys verified from
  installed packages; release material prepared but nothing merged,
  tagged, or published.

## Next action

Await owner approval/merge of PRs #31/#32, then execute
RELEASE-CHECKLIST.md.

## Verification commands (authoritative)

```text
cd packages/corridor-lab && PYTHONPATH=src python -m unittest discover -s tests -v && python -m compileall -q src
cd packages/tracecanary && python -m unittest discover -s tests -v && python -m compileall -q src
corridorlab-gui --smoke-test && tracecanary-gui --smoke-test   # after installation
```

## Blockers

None.
