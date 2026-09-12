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

Open the M1 PR checkpoint, then start Milestone 2 (Corridor Lab scenario
experimentation: named derived variants with assumption diffs) on a stacked
branch.

## Verification commands (authoritative)

```text
cd packages/corridor-lab && PYTHONPATH=src python -m unittest discover -s tests -v && python -m compileall -q src
cd packages/tracecanary && python -m unittest discover -s tests -v && python -m compileall -q src
corridorlab-gui --smoke-test && tracecanary-gui --smoke-test   # after installation
```

## Blockers

None.
