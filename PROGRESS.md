# Operator Labs development roadmap and state

Baseline commit: `eac7bff` (`fix: bound corridor-lab batch discovery during the directory walk (#20)`).
Working branch: `dev/operator-labs-release`.
Release evidence: [RELEASE-EVIDENCE.md](RELEASE-EVIDENCE.md).

## Baseline verification (executed, green)

| Check | Command (run from the package directory) | Result |
|---|---|---|
| Corridor Lab unit tests | `python -m unittest discover -s tests -v` | 88 passed |
| TraceCanary unit tests | `python -m unittest discover -s tests -v` | 97 passed |
| Corridor Lab compile | `python -m compileall -q src` | clean |
| TraceCanary compile | `python -m compileall -q src` | clean |
| Corridor Lab GUI smoke | `python -m corridor_lab --smoke-test` style: `corridorlab-gui --smoke-test` | pass |
| TraceCanary GUI smoke | `tracecanary-gui --smoke-test` | pass |
| Corridor Lab CLI | `corridorlab validate packages/corridor-lab/examples/fictional-corridor/scenario.json` | valid |

Verified with Python 3.11.16 (macOS/arm64) in a clean virtual environment with the
packages installed editable. No pre-existing failures were observed.

## Architectural boundaries (unchanged by this work)

- Two independently installable distributions: `corridor-lab` and `tracecanary`.
- No shared runtime, no root Python distribution, no cross-package import.
- Standard-library-only application runtimes; Tkinter optional and imported lazily.
- Offline, deterministic, synthetic-data-only. No network clients at runtime.
- Explicit user control over every file write.

## Prioritized milestones

### Corridor Lab

| ID | Milestone | Status |
|---|---|---|
| CL-1 | Model increment 1: declared tiered fee schedules, transaction vs period charges, workload/volume scenarios | in progress |
| CL-2 | Model increment 2: bounded multi-period funding and liquidity scenarios | pending |
| CL-3 | Model increment 3: bounded multi-leg route composition with declared joint outcomes | pending |
| CL-4 | Guided scenario/route editor + synthetic template library + revision save and diff workflow | pending |
| CL-5 | Analysis workflow: scenario-set summary, target-path sweeps, attribution, break-even exploration, visuals | pending |
| CL-6 | HTML report dossier + export bundles with manifest and fingerprints | pending |

### TraceCanary

| ID | Milestone | Status |
|---|---|---|
| TC-1 | Versioned retention-contract extension (value types, scopes, occurrence, comparison modes, matching keys) | pending |
| TC-2 | Guided contract editor + synthetic contract profiles | pending |
| TC-3 | Check/Diff/Batch workbench UX: summaries, filtering/grouping, run history, export | pending |
| TC-4 | Bounded baseline/candidate batch pairing with explicit pairing rules | pending |
| TC-5 | Contract-change review workflow | pending |
| TC-6 | Adversarial hardening, non-leakage audit for every output path, HTML dossier | pending |

### Repository

| ID | Milestone | Status |
|---|---|---|
| REPO-1 | macOS CI coverage, path filters, version-agnostic artifact handling | pending |
| REPO-2 | Root navigation, changelogs, release checklists, contributor guidance | pending |

## Current task

CL-1 (tiered fee schedules + workload/volume scenarios): schema evolution to
`corridor-lab.route/v2` and `corridor-lab.scenario/v2`, `corridor_lab/fees.py`,
`corridor_lab/workload.py`, CLI `workload` command, hand-worked example, tests.

## Blockers

None. No external service, credential, or paid resource is required for any
planned milestone.

## Verification commands (authoritative)

```text
cd packages/corridor-lab  && python -m unittest discover -s tests -v && python -m compileall -q src
cd packages/tracecanary  && python -m unittest discover -s tests -v && python -m compileall -q src
```
