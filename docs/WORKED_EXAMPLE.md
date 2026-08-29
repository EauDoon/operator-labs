# Worked example

The fictional Amber to Birch example sends `1000.00 AMR` and receives `BRC`.
It uses deliberately invented values and must not be read as a market quote.

The `scenario.json` file supplies the transaction and an explicit objective.
The `routes/` directory supplies four fictional route templates. Run:

```text
python -m corridor_lab compare examples/fictional-corridor/scenario.json --routes examples/fictional-corridor/routes --format markdown
```

The objective in this example ranks only routes that meet its stated deadline
probability and tail-time guardrails. Delete `objective` from a scenario to
obtain a comparison with no ranking.

`embedded-scenario.json` contains two of the same fictional templates so it can
exercise `evaluate`, `sensitivity`, `stress-grid`, and `pareto` without
external route paths.

In the GUI, load the built-in fictional demo and choose **Explain Report** to
see the same distinctions in text: recipient versus expected recipient,
sender-cost components, successful-by-deadline probability, discrete timing,
guardrails, ranking, and break-even volume. The explanation describes declared
assumptions only and does not recommend a route.
