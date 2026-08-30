# Collector regression example

This fictional example compares a contract-satisfying baseline with a candidate export that no longer retains the required event field. It contains only synthetic values and does not run, configure, or connect to an OpenTelemetry Collector.

```text
python -m tracecanary diff --contract contract.json --baseline baseline.json --candidate candidate.json
```

The command exits `1`, reports the missing retained field, and reports the baseline-to-candidate count regression. It does not print attribute values.
