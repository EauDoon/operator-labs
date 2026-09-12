# Operator Labs

Operator Labs contains two independent, offline Python 3.11+ tools. Each keeps
its original distribution name, command-line and desktop entry points,
documentation, tests, and Apache-2.0 license.

| Package | Purpose |
|---|---|
| [Corridor Lab](packages/corridor-lab/README.md) | Compare declared, fictional cross-border payment routes. |
| [TraceCanary](packages/tracecanary/README.md) | Detect privacy regressions in synthetic OTLP trace exports. |

Install either package directly from its directory:

```text
python -m pip install ./packages/corridor-lab
python -m pip install ./packages/tracecanary
```

The packages remain independent; there is no shared runtime or root Python
distribution.

## Documentation map

- Start with a package README (quick starts, command catalogs, GUI tours).
- [ROADMAP.md](ROADMAP.md) — program milestones and deferred ideas.
- [PROGRESS.md](PROGRESS.md) — current state, verification evidence, and the
  next action.
- [RELEASE-NOTES.md](RELEASE-NOTES.md) and
  [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md) — draft release material
  awaiting owner approval.
