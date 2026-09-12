# Operator Labs program roadmap

Multi-cycle build program for Corridor Lab and TraceCanary. Working method:
one active task at a time, small vertical slices (library, CLI, desktop,
tests, documentation), full affected-package checks at milestones and both
suites at integration boundaries. Checkpoints live in [PROGRESS.md](PROGRESS.md).

Boundaries preserved throughout: two independent distributions, Python 3.11+,
standard-library runtime, offline synthetic-data-only operation, unchanged
entry points and licenses, deterministic exact-decimal calculations,
privacy-safe value-free reporting, and no silent file writes.

## Milestones

| # | Milestone | Status | Acceptance |
|---|---|---|---|
| 1 | Reusable local projects (both packages) | in progress | Save an investigation, close, move the self-contained directory, reopen, and rerun with clear handling of missing/modified inputs. |
| 2 | Corridor Lab scenario experimentation | pending | Derive named variants from a baseline, inspect exactly what changed, run saved experiments, explain tradeoffs across variants. |
| 3 | Corridor Lab target and constraint analysis | pending | Ask a constrained question, get reproducible qualified results over an explicitly evaluated bounded search space. |
| 4 | TraceCanary regression campaigns | pending | Run a reproducible campaign, distinguish control success from privacy success, compare saved value-free summaries with compatibility checks. |
| 5 | TraceCanary contract development and diagnosis | pending | Author, validate, test, revise, and explicitly save a synthetic contract with actionable, value-free diagnostics. |
| 6 | Explainable results and portable evidence | pending | Evidence exports another operator can read without the original operator's context. |
| 7 | Cross-platform reliability and performance | pending | Workflow-level tests across runner platforms; measured bounded workloads; honest GUI-verification record. |
| 8 | Product integration and release readiness | pending | Complete user journeys across new capabilities; release notes and checklist prepared for owner approval. |

Dependencies: M2 depends on M1 (variants live in projects). M4 campaigns
depend on M1 project structures. M3 is independent of M2/M4. M5 is
independent of M4. M6 builds on all prior result surfaces. M7 covers all.
M8 integrates everything.

## Deferred ideas (not scheduled)

- Zip-based evidence bundles with import validation (only if plain-file
  evidence exports prove insufficient; import must defend against
  traversal/link/resource attacks).
- Archived per-run history inside project manifests (M1 keeps result
  evidence out of settings by design).
- Corridor Lab scenario templates beyond the built-in demo (current starter
  plus example folder already cover onboarding).

## Program-level stop conditions

All eight milestone outcomes implemented or replaced by justified
equivalents; both integrated journeys work; tests and clean-install checks
pass; documentation accurate. Stop early only on user request, forced
environment termination, or blocked-by-authority work; continue independent
work around any single blocked milestone.
