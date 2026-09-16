# Worked example

## Question

What do four declared route templates show for a fictional `1000.00 AMR`
transfer to `BRC`? The names, currencies, rates, fees, probabilities, and
timings are invented and must not be read as a market quote.

## Run

The `scenario.json` file supplies the transaction and an explicit objective.
The `routes/` directory supplies four fictional route templates. From
`packages/corridor-lab`, run:

```powershell
$env:PYTHONPATH = "src"
python -m corridor_lab compare examples/fictional-corridor/scenario.json --routes examples/fictional-corridor/routes --format markdown
```

The objective ranks only routes that meet its declared deadline probability and
tail-time guardrails. Remove `objective` from a scenario to obtain a comparison
with no ranking.

## Observed output

This excerpt was captured by running the command above against the checkout's
fixtures:

```text
Synthetic scenario: `fictional-amber-to-birch`

| Route | Recipient (BRC) | Expected recipient (BRC) | Expected sender cost (AMR) | Successful by deadline probability | Tail hours |
| --- | ---: | ---: | ---: | ---: | ---: |
| fictional-correspondent-style | 1713.44 | 1610.63 | 12.69 | 0 | 84 |
| fictional-fiat-token-bridge | 1731.67 | 1679.72 | 6.21 | 0.97 | 4 |
| fictional-linked-instant | 1726.45 | 1691.92 | 6.42 | 0.98 | 8 |
| fictional-tokenized-deposit | 1735.16 | 1709.13 | 4.38 | 0.985 | 0.5 |

Metric: `maximize_expected_recipient_amount`
| Rank | Route | Objective value |
| ---: | --- | ---: |
| 1 | fictional-tokenized-deposit | 1709.1291525 |
| 2 | fictional-linked-instant | 1691.924675 |
| 3 | fictional-fiat-token-bridge | 1679.72293125 |

### Guardrail rejections

| Route | Failed guardrails |
| --- | --- |
| fictional-correspondent-style | Minimum successful-by-deadline probability; Maximum tail time |
```

The report keeps currencies and metrics explicit. It orders the declared
assumptions under the stated objective and does not recommend a route.

`embedded-scenario.json` contains two of the same fictional templates for
`evaluate`, `sensitivity`, `stress-grid`, and `pareto` without external route
paths. In the GUI, load the built-in fictional demo and choose **Explain
Report** to see the same metric definitions in text.
