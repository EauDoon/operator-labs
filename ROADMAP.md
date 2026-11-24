# Operator Labs roadmap

The eight development milestones are implemented: saved projects, Corridor Lab
variants and target analysis, TraceCanary campaigns and contract authoring,
evidence exports, cross-platform checks, and integrated journeys. See
[CHANGELOG.md](CHANGELOG.md) for behavior and fixes. Historical development
checkpoints remain in PROGRESS.md; implementation does not imply a release.

## Next release candidate

Corridor Lab robustness summaries distinguish observed constraint failures, full-case passes and partial scenario coverage. Verify JSON, CSV and Markdown exports together; do not infer a pass for a route missing in a declared case.

## Remaining verification and release gates

- Run both package workflows on the exact release candidate, including the
  installed saved-project journeys with source imports excluded.
- Run both portable Windows workflows and verify the built executable smoke
  checks and archive hashes. A headless smoke pass does not verify a window.
- Record a real-window Windows journey for each exact portable artifact:
  launch without a separate Python installation, create synthetic starters,
  run an investigation, save/reopen, export evidence, and close during work.
- Obtain separate owner approval before tags, releases, or package publication.
  Follow [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md).

## Deferred ideas

- ZIP evidence import only if plain-file evidence proves insufficient, with
  traversal, link, and resource validation before extraction.
- Per-run history in manifests only if keeping evidence separate is inadequate.
- Additional scenario templates only when existing starters miss a concrete case.

Preserve independent distributions, standard-library runtime, offline synthetic
inputs, bounded exact-decimal calculations, value-free TraceCanary reports, and
explicit saves. No new analysis mode is scheduled.
