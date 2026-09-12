# Operator Labs development status

Program: sustained multi-cycle build per [ROADMAP.md](ROADMAP.md).
Program branch: `dev/program-cycle-1` (from `main` at `45776ea`, the PR #30 merge).
Baseline verification at that commit (executed, green): corridor-lab 141
tests, tracecanary 151 tests, compile checks, both GUI smoke tests from the
checkout and from clean installed packages with `PYTHONPATH` unset.

## Completed foundations (do not recreate)

Desktop workbenches with tabbed workflows, protected atomic report exports
with tracked-input collision guards, exact-decimal structured transaction
editing, controller/CLI report agreement, shared bounded batch engine with
background execution and main-thread-only widget updates, synthetic starter
bundles covering every acceptance case. Verified merged via PR #30.

## Milestone 1: reusable local projects (complete pending PR)

Design decisions (lasting rationale):
- Each package gets its own project manifest format; no shared runtime:
  `corridor-lab.project/v1` and `tracecanary.project/v1`. Manifests are
  strict canonical JSON with explicit bounds and duplicate-key rejection,
  like every other package input.
- Relative paths resolve against the project directory; moving a
  self-contained directory keeps it valid. Absolute paths are refused so a
  project stays portable.
- Every referenced input stores a SHA-256 content fingerprint at save time;
  opening reports missing or modified inputs instead of silently accepting
  them. Fingerprints detect change, they never claim identity of entities.
- Result evidence stays out of the manifest. Reopening a project must not
  imply an old report describes current inputs; reports carry their own
  declared inputs and the GUI clears stale results on reopen.
- Saving is explicit: create/save-as write to a user-chosen location and
  refuse to replace an existing manifest silently.
- The same source chosen twice (input == baseline) is stored once and
  referenced twice; distinct sources with colliding names are refused.

Implemented (corridor-lab): `projects.py` library, CLI `project
create|validate|open|add-experiment|run` (combined deterministic
project-run reports; reports protected against replacing inputs or landing
inside the project), controller open/save/run, GUI Open Project / Save
Project As / saved-experiment section with a transactional
save-current-settings dialog. Acceptance flow verified from the installed
package: create -> close -> move -> reopen -> identical deterministic rerun;
modified inputs refuse to run with clear diagnostics.

Implemented (tracecanary): `project.py` library (contract, input, baseline,
candidate, batch directory with tree fingerprints, coverage threshold,
population gate), CLI `project create|validate|open`, controller open/save,
GUI Open Project / Save Project As on the Files tab. Acceptance flow
verified from the installed package including value-free human summaries.

Corridor tests: 157. TraceCanary tests: 164. Both suites, compile checks,
and GUI smoke tests green at commit `2569645`.

## Next action

Milestone 2 (Corridor Lab scenario experimentation) is implemented on the
stacked branch `dev/scenario-experimentation` (base: `dev/program-cycle-1`):
- `variants.py`: derived variants with strict change validation (transaction
  fields plus declared route fee/spread/liquidity fields), materialization
  that preserves every unchanged field, exact-decimal assumption diffs, and
  a variant-comparison analysis table with currencies, units, guardrail
  satisfaction, and an explicit not-a-distribution note. No composite score.
- Manifest variants section accepts file references (existing) or derived
  specs (`base: "scenario"` only; chained bases deferred).
- CLI: `project add-variant | show-variant | compare-variants | run-variants`
  with the same input protection as other project commands.
- Desktop: variants section on the Investigate tab (Show Assumption Diff,
  Apply Variant, Compare Variants); applied variants are in-memory, unsaved,
  and clearly labeled; controller/CLI agreement asserted.
- Corridor tests: 171. Real-window drive passed on macOS arm64.

Next: push the stacked branch, open the M2 PR (base dev/program-cycle-1),
wait for CI, then start Milestone 3 (target and constraint analysis).

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

## Verification commands (authoritative)

```text
cd packages/corridor-lab && PYTHONPATH=src python -m unittest discover -s tests -v && python -m compileall -q src
cd packages/tracecanary && python -m unittest discover -s tests -v && python -m compileall -q src
corridorlab-gui --smoke-test && tracecanary-gui --smoke-test   # after installation
```

## Blockers

None.
