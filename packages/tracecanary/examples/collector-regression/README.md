# Collector regression example

## Question

Did a candidate trace export preserve the required operational event field?
This fictional case contains only synthetic values. It does not run, configure,
or connect to an OpenTelemetry Collector.

## Run

From `packages/tracecanary`, use the pinned contract with the passing baseline
and candidate export:

```powershell
$env:PYTHONPATH = "src"
python -m tracecanary diff --contract fixtures/v1/contract.json --baseline examples/collector-regression/baseline.json --candidate examples/collector-regression/candidate.json
```

## Observed output

The command produced this output and exited with status `1`:

```text
TraceCanary: REGRESSION (2 finding(s))
- TC004 required operational field is absent [key=telemetry.event.class; scope=event]
- TC005 candidate retained fewer required operational fields than baseline [key=telemetry.event.class; scope=event]
```

`TC004` identifies the missing field. `TC005` compares its retained-field count
with the passing baseline. The report does not print attribute values or
synthetic canary values.
