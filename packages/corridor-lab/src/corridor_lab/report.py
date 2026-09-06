"""Deterministic JSON, CSV, and Markdown report renderers."""

from __future__ import annotations

import csv
import io
import html

from .canonical import MAX_REPORT_BYTES, canonical_dumps


def _safe_csv_cell(value: object) -> object:
    """Prefix text that spreadsheet software can treat as a formula."""
    if not isinstance(value, str):
        return value
    for character in value:
        if character in "=+-@\t\r":
            return "'" + value
        if character.isspace():
            continue
        break
    return value


def _csv_text(rows: list[dict[str, object]], fields: list[str]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows([{key: _safe_csv_cell(value) for key, value in row.items()} for row in rows])
    return stream.getvalue()


def render_csv(report: dict[str, object]) -> str:
    if report.get("report_version") == "corridor-lab.pareto/v1":
        frontier = report.get("frontier")
        if not isinstance(frontier, list):
            raise ValueError("Pareto report has no frontier rows")
        return _csv_text(
            [dict(item) for item in frontier],
            ["route_id", "expected_recipient_amount", "expected_sender_cost"],
        )
    if "rows" in report:
        rows = report["rows"]
        assert isinstance(rows, list)
        if report.get("report_version") == "corridor-lab.workload/v1":
            return _csv_text(
                [dict(row) for row in rows],
                [
                    "workload_id",
                    "route_id",
                    "transactions_per_period",
                    "fee_basis",
                    "explicit_fee_transaction_send",
                    "explicit_fee_period_amortized_send",
                    "explicit_fee_send",
                    "liquidity_carry_cost_send",
                    "expected_failure_recovery_cost_send",
                    "expected_sender_cost",
                    "period_explicit_fee_send",
                    "period_expected_sender_cost_send",
                    "recipient_amount",
                    "expected_recipient_amount",
                    "probability_by_deadline",
                ],
            )
        if report.get("report_version") == "corridor-lab.funding/v1":
            return _csv_text(
                [dict(row) for row in rows],
                [
                    "route_id",
                    "recovery_delay_periods",
                    "required_prefunding_send",
                    "declared_opening_balance_send",
                    "shortfall_send",
                    "shortfall_periods",
                    "average_tied_up_capital_send",
                    "peak_settlement_exposure_send",
                    "carrying_cost_send",
                    "expected_loss_send",
                    "total_disbursements_send",
                    "total_recoveries_send",
                    "recoveries_after_horizon_send",
                ],
            )
        if report.get("report_version") == "corridor-lab.stress-grid/v1":
            return _csv_text(
                [dict(row) for row in rows],
                [
                    "route_id",
                    "parameter_a",
                    "value_a",
                    "parameter_b",
                    "value_b",
                    "expected_recipient_amount",
                    "expected_sender_cost",
                    "probability_by_deadline",
                ],
            )
        return _csv_text(
            [dict(row) for row in rows],
            [
                "route_id",
                "parameter",
                "value",
                "expected_recipient_amount",
                "expected_sender_cost",
                "probability_by_deadline",
                "probability_by_deadline_definition",
                "tail_completion_time_hours",
            ],
        )
    routes = report.get("routes")
    if not isinstance(routes, list):
        raise ValueError("report has no tabular rows")
    rows: list[dict[str, object]] = []
    for route in routes:
        item = dict(route)
        currency = item.pop("currency")
        declared_inputs = item.pop("declared_inputs")
        declared_transaction = declared_inputs["transaction"]
        declared_route = declared_inputs["route"]
        item["send_currency"] = currency["send"]
        item["receive_currency"] = currency["receive"]
        item["send_precision"] = declared_transaction["send_precision"]
        item["receive_precision"] = declared_transaction["receive_precision"]
        item["fx_rate"] = declared_route["fx_rate"]
        item["fixed_fee_send_declared"] = declared_route["fixed_fee_send"]
        item["percent_fee_bps"] = declared_route["percent_fee_bps"]
        item["fx_spread_bps"] = declared_route["fx_spread_bps"]
        item["prefunding_amount_send"] = declared_route["liquidity"]["prefunding_amount_send"]
        item["annual_cost_of_capital_bps"] = declared_route["liquidity"]["annual_cost_of_capital_bps"]
        item["holding_days"] = declared_route["liquidity"]["holding_days"]
        item["volume_per_period"] = declared_transaction["volume_per_period"]
        rows.append(item)
    return _csv_text(
        rows,
        [
            "route_id",
            "label",
            "send_currency",
            "receive_currency",
            "send_precision",
            "receive_precision",
            "recipient_amount",
            "expected_recipient_amount",
            "explicit_fee_send",
            "fx_spread_cost_receive",
            "liquidity_carry_cost_send",
            "expected_failure_recovery_cost_send",
            "expected_sender_cost",
            "probability_by_deadline",
            "probability_by_deadline_definition",
            "expected_completion_time_hours",
            "median_completion_time_hours",
            "tail_completion_time_hours",
            "fx_rate",
            "fixed_fee_send_declared",
            "percent_fee_bps",
            "fx_spread_bps",
            "prefunding_amount_send",
            "annual_cost_of_capital_bps",
            "holding_days",
            "volume_per_period",
        ],
    )


def _cell(value: object) -> str:
    text = html.escape(str(value).replace("\n", " ").replace("\r", " "), quote=True)
    for character in "\\[]()!":
        text = text.replace(character, "\\" + character)
    return text.replace("|", "\\|").replace("`", "&#96;")


def _currency(report: dict[str, object], key: str, fallback: str) -> str:
    for source in (report.get("transaction"), report):
        if isinstance(source, dict) and isinstance(source.get(key), str):
            return source[key]
    return fallback


def _batch_item_error(item: dict[str, object]) -> str:
    nested = item.get("report")
    if isinstance(nested, dict):
        error = nested.get("error")
        if isinstance(error, str):
            return error
    return ""


def _objective_summary(report: dict[str, object]) -> str:
    objective = report.get("objective")
    if not isinstance(objective, dict):
        return ""
    metric = objective.get("metric")
    metric_text = {
        "maximize_expected_recipient_amount": "maximize expected recipient amount",
        "minimize_expected_sender_cost": "minimize expected sender cost",
    }.get(metric, _cell(metric))
    guardrails = objective.get("guardrails")
    if not isinstance(guardrails, dict) or not guardrails:
        return f"The explicit objective is to {metric_text}."
    conditions: list[str] = []
    if "minimum_probability_by_deadline" in guardrails:
        conditions.append(f"minimum successful-by-deadline probability `{_cell(guardrails['minimum_probability_by_deadline'])}`")
    if "maximum_tail_hours" in guardrails:
        conditions.append(f"maximum tail time `{_cell(guardrails['maximum_tail_hours'])}` hours")
    return f"The explicit objective is to {metric_text}, with guardrails: {'; '.join(conditions)}."


def _comparison_explanation(report: dict[str, object]) -> list[str]:
    send_currency = _currency(report, "send_currency", "send currency")
    receive_currency = _currency(report, "receive_currency", "receive currency")
    lines = [
        "",
        "## How to read this report",
        "",
        f"Recipient figures are in `{receive_currency}` and sender-cost figures are in `{send_currency}`.",
        "`Recipient` is conditional on success; `Expected recipient` assigns zero recipient value to failure outcomes.",
        "`Expected sender cost` combines declared explicit fees, liquidity carrying cost, and expected unreturned principal after failure and recovery.",
        "`Successful by deadline probability` counts success states only when their declared delay is no greater than the stated deadline.",
        "Completion-time metrics are discrete outcome percentiles: median is the 50th percentile and tail time is the 95th percentile of time to a final state.",
    ]
    ranking = report.get("ranking")
    if isinstance(ranking, dict):
        lines.append(f"{_objective_summary(report)} The displayed ranking is an ordering under those declared conditions, not a recommendation.")
    else:
        lines.append("No ranking is displayed because this scenario has no explicit objective and guardrails; this report does not recommend a route.")
    break_even = report.get("break_even_volumes")
    if isinstance(break_even, list) and break_even:
        lines.extend(["", "### Break-even volume", ""])
        for item in break_even:
            left = _cell(item.get("left_route_id", "left route"))
            right = _cell(item.get("right_route_id", "right route"))
            status = item.get("status")
            if status == "computed":
                volume = _cell(item.get("volume_transactions_per_period", ""))
                lines.append(f"- `{left}` and `{right}` break even at `{volume}` transactions per period under the declared expected sender costs.")
            elif status == "no_finite_break_even":
                lines.append(f"- `{left}` and `{right}` have no finite break-even volume under the declared sender-cost model.")
            else:
                lines.append(f"- `{left}` and `{right}` have no positive break-even volume under the declared sender-cost model.")
    return lines


def _funding_explanation(report: dict[str, object]) -> list[str]:
    send_currency = _currency(report, "send_currency", "send currency")
    schedule = report.get("declared_schedule")
    lines = [
        "",
        "## How to read this funding report",
        "",
        f"Every figure is in `{send_currency}` and is driven only by the declared schedule. No arrival distribution, financing availability, or forecast is modelled.",
        "`Required prefunding` is the peak funding that must be available so that no declared period falls below zero. It does not depend on the declared opening balance.",
        "`Average tied-up capital` is a holding statistic given the declared opening balance. It is not a loss.",
        "`Expected loss` applies the route's declared per-transaction unrecovered-principal rate to the declared total disbursements. Loss is not capital tied up, and capital tied up is not loss.",
        "`Shortfall` is the gap between the required prefunding and the declared opening balance; `Shortfall periods` names the periods that fall below zero.",
        "`Recoveries after horizon` counts declared recoveries whose arrival period falls beyond the last declared period. It is reported rather than dropped, so the end of a schedule is not a claim of full recovery.",
        "In the period detail, `Recoveries declared` is what the schedule says that period recovers and `Recoveries arriving` is what actually arrives after the declared recovery delay, available for disbursement from the following period.",
    ]
    if isinstance(schedule, dict):
        lines.append(
            f"Declared schedule: `{_cell(schedule.get('days_per_period', ''))}`-day periods, "
            f"settlement delay `{_cell(schedule.get('settlement_delay_periods', ''))}` periods, "
            f"declared recovery delay `{_cell(schedule.get('recovery_delay_periods', ''))}` periods, "
            f"opening balance `{_cell(schedule.get('opening_balance_send', ''))}`."
        )
    detail = report.get("period_detail")
    if isinstance(detail, list) and detail:
        lines.extend(["", "### Declared period detail", ""])
        for block in detail:
            lines.append(
                f"`{_cell(block.get('route_id', ''))}` with a recovery delay of "
                f"`{_cell(block.get('recovery_delay_periods', ''))}` periods:"
            )
            lines.extend(
                [
                    "",
                    "| Period | Balance start | Disbursements | Recoveries declared | Recoveries arriving | Trough | Unsettled exposure |",
                    "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            for period in block.get("periods", []):
                lines.append(
                    "| "
                    + " | ".join(
                        _cell(period[name])
                        for name in (
                            "period_index",
                            "balance_start_send",
                            "disbursements_send",
                            "recoveries_declared_send",
                            "recoveries_arriving_send",
                            "trough_send",
                            "unsettled_exposure_send",
                        )
                    )
                    + " |"
                )
            lines.append("")
    return lines


def _workload_explanation(report: dict[str, object]) -> list[str]:
    send_currency = _currency(report, "send_currency", "send currency")
    receive_currency = _currency(report, "receive_currency", "receive currency")
    return [
        "",
        "## How to read this workload report",
        "",
        f"Sender-cost and fee figures are in `{send_currency}`; recipient figures are in `{receive_currency}`.",
        "Each row pairs one declared workload with one route. A workload is an author-declared number of transactions per period; it is not measured or forecast.",
        "`Transaction fee` is the per-transaction tiered or flat fee. `Amortized period charge` spreads declared period charges across the workload's transactions.",
        "`Period sender cost` is the per-transaction expected sender cost multiplied by the declared transactions per period.",
        "Recipient amount changes across workloads only when a period charge is amortized over the scenario volume, because that charge reduces the per-transaction deduction. It is otherwise constant for the same route.",
        "Successful-by-deadline probability does not depend on volume.",
        f"The scenario's own reference volume is `{_cell(report.get('reference_volume_per_period', ''))}` transactions per period.",
    ]


def _sensitivity_explanation() -> list[str]:
    return [
        "",
        "## How to read this sensitivity report",
        "",
        "Each row changes exactly one declared route parameter while holding the remaining scenario assumptions fixed.",
        "Expected recipient assigns zero recipient value to failure outcomes. Expected sender cost combines declared fees, liquidity carry, and expected unreturned principal.",
        "Successful by deadline probability counts only success states with delay no greater than the declared deadline. This is a deterministic what-if calculation, not a forecast or recommendation.",
    ]


def render_markdown(report: dict[str, object]) -> str:
    scenario_id = _cell(report.get("scenario_id", "ad-hoc"))
    lines = ["# Corridor Lab report", "", f"Synthetic scenario: `{scenario_id}`", ""]
    if report.get("report_version") == "corridor-lab.batch/v1":
        items = report.get("items", [])
        include_paths = any("path" in item for item in items)
        include_errors = any(_batch_item_error(item) for item in items)
        headers = ["Item", "Status"]
        if include_paths:
            headers.append("Path")
        if include_errors:
            headers.append("Error")
        lines = [
            "# Corridor Lab batch report",
            "",
            f"Status: `{_cell(report.get('status', 'unresolved'))}`",
            "",
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for item in items:
            values = [item.get("id", ""), item.get("status", "unresolved")]
            if include_paths:
                values.append(item.get("path", ""))
            if include_errors:
                values.append(_batch_item_error(item))
            lines.append("| " + " | ".join(_cell(value) for value in values) + " |")
        return "\n".join(lines) + "\n"
    if report.get("report_version") == "corridor-lab.pareto/v1":
        lines = ["# Corridor Lab Pareto frontier", "", f"Synthetic scenario: `{scenario_id}`", "", "| Route | Expected recipient | Expected sender cost |", "| --- | ---: | ---: |"]
        for item in report.get("frontier", []):
            lines.append(f"| {_cell(item.get('route_id', ''))} | {_cell(item.get('expected_recipient_amount', ''))} | {_cell(item.get('expected_sender_cost', ''))} |")
        lines.extend(["", "Both explicit metrics remain visible. No composite score is calculated."])
        return "\n".join(lines) + "\n"
    if report.get("report_version") == "corridor-lab.break-even-workload/v1":
        status = _cell(report.get("status", ""))
        lines = [
            "# Corridor Lab break-even workload exploration",
            "",
            f"Synthetic scenario: `{scenario_id}`",
            "",
            f"Routes: `{_cell(report.get('left_route_id', ''))}` versus `{_cell(report.get('right_route_id', ''))}`.",
            f"Outcome: `{status}`.",
            "",
            "| Workload | Transactions per period | Left expected sender cost | Right expected sender cost | Difference |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for point in report.get("points", []):
            lines.append(
                "| "
                + " | ".join(
                    _cell(point[name])
                    for name in (
                        "workload_id",
                        "transactions_per_period",
                        "left_expected_sender_cost",
                        "right_expected_sender_cost",
                        "difference_send",
                    )
                )
                + " |"
            )
        if "note" in report:
            lines.extend(["", _cell(report["note"])])
        elif "lower_workload_id" in report:
            lines.extend(
                [
                    "",
                    f"The ordering reverses between `{_cell(report['lower_workload_id'])}` and "
                    f"`{_cell(report['upper_workload_id'])}`. Corridor Lab does not interpolate "
                    "between declared workloads, so no volume between them is claimed.",
                ]
            )
        lines.extend(["", "This is an ordering comparison under declared assumptions, not a recommendation."])
        return "\n".join(lines) + "\n"
    if report.get("report_version") == "corridor-lab.funding/v1":
        lines = [
            "# Corridor Lab funding and liquidity report",
            "",
            f"Synthetic scenario: `{scenario_id}`",
            "",
            "| Route | Recovery delay (periods) | Required prefunding | Declared opening balance | Shortfall | Shortfall periods | Average tied-up capital | Carrying cost | Expected loss |",
            "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
        ]
        for row in report.get("rows", []):
            lines.append(
                "| "
                + " | ".join(
                    _cell(row[name])
                    for name in (
                        "route_id",
                        "recovery_delay_periods",
                        "required_prefunding_send",
                        "declared_opening_balance_send",
                        "shortfall_send",
                        "shortfall_periods",
                        "average_tied_up_capital_send",
                        "carrying_cost_send",
                        "expected_loss_send",
                    )
                )
                + " |"
            )
        lines.extend(_funding_explanation(report))
        return "\n".join(lines) + "\n"
    if "rows" in report:
        if report.get("report_version") == "corridor-lab.workload/v1":
            lines[0] = "# Corridor Lab workload report"
            lines.extend(
                [
                    "| Workload | Route | Transactions per period | Fee basis | Transaction fee | Amortized period charge | Explicit fee | Liquidity carry | Expected sender cost | Period sender cost |",
                    "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            for row in report["rows"]:
                lines.append(
                    "| "
                    + " | ".join(
                        _cell(row[name])
                        for name in (
                            "workload_id",
                            "route_id",
                            "transactions_per_period",
                            "fee_basis",
                            "explicit_fee_transaction_send",
                            "explicit_fee_period_amortized_send",
                            "explicit_fee_send",
                            "liquidity_carry_cost_send",
                            "expected_sender_cost",
                            "period_expected_sender_cost_send",
                        )
                    )
                    + " |"
                )
            lines.extend(_workload_explanation(report))
            return "\n".join(lines) + "\n"
        if report.get("report_version") == "corridor-lab.stress-grid/v1":
            lines.extend(
                [
                    f"| Route | {_cell(report.get('parameter_a', 'Parameter A'))} | {_cell(report.get('parameter_b', 'Parameter B'))} | Expected recipient | Expected sender cost | Successful by deadline probability |",
                    "| --- | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            for row in report["rows"]:
                lines.append(
                    "| " + " | ".join(_cell(row[name]) for name in ("route_id", "value_a", "value_b", "expected_recipient_amount", "expected_sender_cost", "probability_by_deadline")) + " |"
                )
            lines.extend(["", "This is an explicit two-parameter stress grid. No composite score is calculated."])
            return "\n".join(lines) + "\n"
        lines.extend(
            [
                "| Route | Parameter | Value | Expected recipient | Expected sender cost | Successful by deadline probability | Tail hours |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in report["rows"]:
            lines.append(
                "| "
                + " | ".join(
                    _cell(row[name])
                    for name in (
                        "route_id",
                        "parameter",
                        "value",
                        "expected_recipient_amount",
                        "expected_sender_cost",
                        "probability_by_deadline",
                        "tail_completion_time_hours",
                    )
                )
                + " |"
            )
        lines.extend(_sensitivity_explanation())
        return "\n".join(lines) + "\n"
    send_currency = _currency(report, "send_currency", "send currency")
    receive_currency = _currency(report, "receive_currency", "receive currency")
    lines.extend(
        [
            f"| Route | Recipient ({_cell(receive_currency)}) | Expected recipient ({_cell(receive_currency)}) | Expected sender cost ({_cell(send_currency)}) | Successful by deadline probability | Tail hours |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for route in report["routes"]:
        lines.append(
            "| "
            + " | ".join(
                _cell(route[name])
                for name in (
                    "route_id",
                    "recipient_amount",
                    "expected_recipient_amount",
                    "expected_sender_cost",
                    "probability_by_deadline",
                    "tail_completion_time_hours",
                )
            )
            + " |"
        )
    if "ranking" in report:
        ranking = report["ranking"]
        lines.extend(["", "## Explicit objective ranking", ""])
        lines.append(f"Metric: `{_cell(ranking['objective_metric'])}`")
        lines.append("")
        lines.append("| Rank | Route | Objective value |")
        lines.append("| ---: | --- | ---: |")
        for item in ranking["eligible_routes"]:
            lines.append(f"| {_cell(item['rank'])} | {_cell(item['route_id'])} | {_cell(item['objective_value'])} |")
        rejections = ranking.get("guardrail_rejections", [])
        if rejections:
            if not ranking["eligible_routes"]:
                lines.extend(["", "No routes met every declared guardrail."])
            guardrail_labels = {
                "minimum_probability_by_deadline": "Minimum successful-by-deadline probability",
                "maximum_tail_hours": "Maximum tail time",
            }
            lines.extend(["", "### Guardrail rejections", "", "| Route | Failed guardrails |", "| --- | --- |"])
            for item in rejections:
                failures = "; ".join(
                    guardrail_labels.get(name, _cell(name)) for name in item["failed_guardrails"]
                )
                lines.append(f"| {_cell(item['route_id'])} | {failures} |")
    frontier = report.get("pareto_frontier")
    if isinstance(frontier, list):
        lines.extend(["", "## Pareto frontier", "", "The frontier keeps both explicit metrics visible: expected recipient amount is maximized and expected sender cost is minimized.", "", "| Route | Expected recipient | Expected sender cost |", "| --- | ---: | ---: |"])
        for item in frontier:
            lines.append(f"| {_cell(item.get('route_id', ''))} | {_cell(item.get('expected_recipient_amount', ''))} | {_cell(item.get('expected_sender_cost', ''))} |")
    lines.extend(_comparison_explanation(report))
    return "\n".join(lines) + "\n"


def render_report(report: dict[str, object], output_format: str) -> str:
    if output_format == "json":
        text = canonical_dumps(report)
    elif output_format == "csv":
        text = render_csv(report)
    elif output_format == "markdown":
        text = render_markdown(report)
    else:
        raise ValueError(f"unsupported report format: {output_format}")
    if len(text.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError(f"report exceeds the {MAX_REPORT_BYTES}-byte budget")
    return text
