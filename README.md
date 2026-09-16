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

## Worked cases

Both cases use fictional fixtures and run offline from a source checkout. They
show the question, the input, and the result a reviewer can inspect quickly.

### Corridor Lab

**Problem:** Route comparisons can hide the tradeoff between recipient value,
sender cost, timing, and explicit guardrails.

**Example:** The fictional Amber to Birch scenario sends `1000.00 AMR` across
four declared route files.

**Result:** The comparison ranks `fictional-tokenized-deposit` first under the
declared objective, with `1709.1291525 BRC` as its objective value and
`4.38 AMR` expected sender cost. `fictional-correspondent-style` fails both
declared guardrails. This is an ordering of synthetic assumptions, not a route
recommendation.

Run it from `packages/corridor-lab`:

```powershell
$env:PYTHONPATH = "src"
python -m corridor_lab compare examples/fictional-corridor/scenario.json --routes examples/fictional-corridor/routes --format markdown
```

See the [Corridor Lab worked case](packages/corridor-lab/docs/WORKED_EXAMPLE.md)
for the observed output excerpt and metric definitions.

### TraceCanary

**Problem:** A telemetry export can lose a required operational field even
when the privacy contract has no synthetic canary leak.

**Example:** The collector regression fixture compares a passing baseline with
a candidate whose event no longer retains `telemetry.event.class`.

**Result:** `diff` exits with status `1` and reports `TC004` for the missing
event field plus `TC005` for the baseline count regression. The report contains
no canary value.

Run it from `packages/tracecanary`:

```powershell
$env:PYTHONPATH = "src"
python -m tracecanary diff --contract fixtures/v1/contract.json --baseline examples/collector-regression/baseline.json --candidate examples/collector-regression/candidate.json
```

See the [TraceCanary collector regression case](packages/tracecanary/examples/collector-regression/README.md)
for the observed output and exit status.

## Documentation map

- Start with a package README (quick starts, command catalogs, GUI tours).
- [ROADMAP.md](ROADMAP.md): program milestones and deferred ideas.
- [PROGRESS.md](PROGRESS.md): current state, verification evidence, and the
  next action.
- [RELEASE-NOTES.md](RELEASE-NOTES.md) and
  [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md): draft release material
  awaiting owner approval.
