"""Synthetic fixture bundle used by the CLI and repository tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from tracecanary.canonical import canonical_json

PROMPT = "TCANARY_PROMPT_71f0e04f"
TOOL_ARGUMENTS = "TCANARY_TOOL_ARGUMENTS_b26dc3a1"
TOOL_RESULT = "TCANARY_TOOL_RESULT_5aa72e93"
USER_IDENTIFIER = "TCANARY_USER_IDENTIFIER_4a8d8ce7"


def bundle() -> dict[str, Any]:
    """Return only fictional OTLP data and its version-pinned contract."""
    contract = {
        "contract_version": "tracecanary/v1",
        "semantic_conventions_version": "opentelemetry/semconv/1.43.0",
        "canaries": [
            {"label": "synthetic-prompt", "category": "prompt", "value": PROMPT},
            {"label": "synthetic-tool-arguments", "category": "tool_arguments", "value": TOOL_ARGUMENTS},
            {"label": "synthetic-tool-result", "category": "tool_result", "value": TOOL_RESULT},
            {"label": "synthetic-user-identifier", "category": "user_identifier", "value": USER_IDENTIFIER},
        ],
        "forbidden_attribute_keys": ["gen_ai.prompt", "gen_ai.tool.call.arguments", "gen_ai.tool.call.result"],
        "forbidden_attribute_key_prefixes": ["enduser."],
        "forbidden_path_prefixes": ["/resourceSpans/*/scopeSpans/*/spans/*/attributes/*/value/bytesValue"],
        "required_retained_fields": [
            {"scope": "resource", "key": "service.name"},
            {"scope": "span", "key": "gen_ai.operation.name"},
            {"scope": "event", "key": "telemetry.event.class"},
        ],
        "limits": {"max_input_bytes": 5000000, "max_nesting": 100, "max_batch_files": 256},
    }
    safe = _safe_trace()
    prompt = _with_attribute(safe, "gen_ai.prompt", PROMPT)
    arguments = _with_attribute(safe, "gen_ai.tool.call.arguments", TOOL_ARGUMENTS)
    result = _with_attribute(safe, "gen_ai.tool.call.result", TOOL_RESULT)
    identifier = _with_attribute(safe, "enduser.id", USER_IDENTIFIER)
    positive = _with_attribute(_with_attribute(_with_attribute(_with_attribute(safe, "gen_ai.prompt", PROMPT), "gen_ai.tool.call.arguments", TOOL_ARGUMENTS), "gen_ai.tool.call.result", TOOL_RESULT), "enduser.id", USER_IDENTIFIER)
    missing = deepcopy(safe)
    missing["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["events"] = []
    forbidden_path = _with_attribute(safe, "synthetic.binary", "not-a-canary", value_kind="bytesValue")
    sparse = deepcopy(safe)
    sparse_spans = sparse["resourceSpans"][0]["scopeSpans"][0]["spans"]
    sparse_spans.append(
        {
            "name": "synthetic.gen_ai.request.sparse",
            "attributes": [_attribute("server.address", "offline.test")],
            "events": [{"name": "telemetry.exported", "attributes": [_attribute("telemetry.event.class", "synthetic")]}],
        }
    )
    invalid = {"resourceSpans": {"unexpected": True}}
    return {
        "contract.json": contract,
        "safe-export.json": safe,
        "positive-control.json": positive,
        "leaked-prompt.json": prompt,
        "leaked-tool-arguments.json": arguments,
        "leaked-tool-result.json": result,
        "leaked-user-identifier.json": identifier,
        "missing-operational-fields.json": missing,
        "forbidden-path.json": forbidden_path,
        "sparse-retention.json": sparse,
        "invalid-export.json": invalid,
    }


def write_bundle(output: Path) -> None:
    """Write the synthetic bundle into an empty destination directory."""
    try:
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("fixture output directory must be empty")
        output.mkdir(parents=True, exist_ok=True)
        for name, data in bundle().items():
            (output / name).write_text(canonical_json(data), encoding="utf-8", newline="\n")
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError("fixture output directory could not be written") from exc


def _safe_trace() -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attribute("service.name", "fictional-agent-service"), _attribute("deployment.environment.name", "test")]},
                "scopeSpans": [
                    {
                        "scope": {"name": "fictional.instrumentation"},
                        "spans": [
                            {
                                "name": "synthetic.gen_ai.request",
                                "attributes": [_attribute("gen_ai.operation.name", "chat"), _attribute("server.address", "offline.test")],
                                "events": [{"name": "telemetry.exported", "attributes": [_attribute("telemetry.event.class", "synthetic")]}],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _with_attribute(trace: dict[str, Any], key: str, value: str, *, value_kind: str = "stringValue") -> dict[str, Any]:
    result = deepcopy(trace)
    result["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"].append(_attribute(key, value, value_kind))
    return result


def _attribute(key: str, value: str, value_kind: str = "stringValue") -> dict[str, Any]:
    return {"key": key, "value": {value_kind: value}}
