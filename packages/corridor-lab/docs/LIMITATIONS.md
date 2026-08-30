# Limitations

- All input is synthetic and user-declared. The engine does not validate it
  against a market, institution, network, regulator, or dataset.
- A route template is an abstract scenario pattern. It does not represent or
  describe a production network, product, provider, or corridor.
- The model treats supplied outcome states as mutually exclusive and complete.
  Correlations, seasonality, operational queues, and feedback effects are out
  of scope.
- The liquidity model uses a simple annualized capital-cost allocation. It does
  not model balance-sheet constraints, intraday liquidity, or accounting.
- Currency labels and precision are formatting inputs, not ISO validation.
- Ranking only orders assumptions under an explicit objective and guardrails.
  It is not advice or an automated route selection decision.
- The optional desktop interface requires a local Tcl/Tk graphical environment.
  Its smoke test exercises controller logic only and deliberately creates no
  window.
- The scenario editor intentionally edits raw JSON rather than inferring missing
  assumptions. It accepts only a strictly validated fictional scenario and does
  not edit separately selected external route files.
