# Fictional Amber to Birch corridor

Everything in this example is invented: names, currency codes, route types,
rates, costs, probabilities, and timings. It is a deterministic worked example,
not a quote, forecast, recommendation, or representation of any payment network.

From the repository root:

```text
python -m corridor_lab validate examples/fictional-corridor/scenario.json
python -m corridor_lab compare examples/fictional-corridor/scenario.json --routes examples/fictional-corridor/routes
python -m corridor_lab sensitivity examples/fictional-corridor/embedded-scenario.json --parameter fx_spread_bps --values 10,25,50,100
```
