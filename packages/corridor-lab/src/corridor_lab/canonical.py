"""Strict JSON input and canonical output helpers."""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import AbstractContextManager
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, localcontext
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 1_000_000
MAX_NESTING = 64
MAX_DECIMAL_SIGNIFICANT_DIGITS = 18
MAX_DECIMAL_SCALE = 12
MAX_DECIMAL_ADJUSTED = 18
MAX_ROUTES = 64
MAX_OUTCOMES_PER_ROUTE = 64
MAX_SENSITIVITY_VALUES = 64
MAX_SENSITIVITY_ROWS = 512
MAX_ROUTE_PAIRS = 1024
MAX_BATCH_SCENARIOS = 64
MAX_REPORT_BYTES = 5_000_000
FIXED_DECIMAL_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
)


class InputError(ValueError):
    """Raised for malformed or hostile external inputs."""


def local_decimal_context() -> AbstractContextManager[Context]:
    """Return a fixed calculation context, never a copy of ambient state."""
    return localcontext(FIXED_DECIMAL_CONTEXT)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise InputError(f"JSON constant {value} is not permitted")


def _check_nesting(value: Any, depth: int = 0) -> None:
    if depth > MAX_NESTING:
        raise InputError(f"JSON nesting exceeds {MAX_NESTING}")
    if isinstance(value, dict):
        for item in value.values():
            _check_nesting(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_nesting(item, depth + 1)


def parse_json_bytes(raw: bytes) -> Any:
    """Parse bounded UTF-8 JSON while rejecting duplicate keys."""
    if len(raw) > MAX_INPUT_BYTES:
        raise InputError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, DecimalException) as exc:
        raise InputError(f"invalid JSON: {exc}") from exc
    _check_nesting(value)
    return value


def parse_json_text(text: str) -> Any:
    """Parse editor text under the same limits and checks as file input."""
    if not isinstance(text, str):
        raise InputError("JSON text must be a string")
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InputError("JSON text is not valid UTF-8") from exc
    return parse_json_bytes(raw)


def load_json(path: str | Path) -> Any:
    """Load a bounded JSON document while rejecting duplicate keys."""
    return parse_json_bytes(read_bounded_bytes(path))


def read_bounded_bytes(path: str | Path) -> bytes:
    """Read at most one byte beyond the input limit for fail-closed sizing."""
    input_path = Path(path)
    try:
        with input_path.open("rb") as input_file:
            raw = input_file.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise InputError(f"cannot read {input_path}: {exc}") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise InputError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    return raw


def decimal_text(value: Decimal) -> str:
    """Render Decimal without exponent notation or unnecessary trailing zeroes."""
    if not value.is_finite():
        raise InputError("decimal must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def canonical_dumps(value: Any) -> str:
    """Return byte-stable JSON with a terminating LF."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{path} must be an object")
    return value


def require_keys(
    value: dict[str, Any], required: set[str], optional: set[str], path: str
) -> None:
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required - optional)
    if missing:
        raise InputError(f"{path} missing required field(s): {', '.join(missing)}")
    if unknown:
        raise InputError(f"{path} has unsupported field(s): {', '.join(unknown)}")


def require_string(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise InputError(f"{path} must be a non-empty string")
    return value


def require_identifier(value: Any, path: str, *, maximum: int = 64) -> str:
    """Require a stable, non-markup identifier for report contexts."""
    text = require_string(value, path)
    if len(text) > maximum or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", text) is None:
        raise InputError(f"{path} must be an identifier using letters, numbers, dot, underscore, colon, slash, or hyphen")
    return text


def require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise InputError(f"{path} must be a boolean")
    return value


def require_decimal(
    value: Any,
    path: str,
    *,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    positive: bool = False,
) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise InputError(f"{path} must be a decimal string or integer")
    try:
        parsed = Decimal(value)
    except (DecimalException, ValueError) as exc:
        raise InputError(f"{path} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise InputError(f"{path} must be finite")
    tuple_value = parsed.as_tuple()
    if len(tuple_value.digits) > MAX_DECIMAL_SIGNIFICANT_DIGITS:
        raise InputError(f"{path} exceeds {MAX_DECIMAL_SIGNIFICANT_DIGITS} significant digits")
    if tuple_value.exponent < -MAX_DECIMAL_SCALE:
        raise InputError(f"{path} exceeds {MAX_DECIMAL_SCALE} decimal places")
    if parsed != 0 and parsed.adjusted() > MAX_DECIMAL_ADJUSTED:
        raise InputError(f"{path} exceeds supported magnitude")
    if positive and parsed <= 0:
        raise InputError(f"{path} must be greater than zero")
    if minimum is not None and parsed < minimum:
        raise InputError(f"{path} must be at least {decimal_text(minimum)}")
    if maximum is not None and parsed > maximum:
        raise InputError(f"{path} must be at most {decimal_text(maximum)}")
    return parsed


def require_decimal_values(values: Any, path: str) -> list[Decimal]:
    """Require a finite decimal list with no duplicate values."""
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise InputError(f"{path} must be a list of decimals")
    parsed = [require_decimal(value, f"{path} value") for value in values]
    if len(parsed) != len(set(parsed)):
        raise InputError(f"{path} must not contain duplicate values")
    return parsed


def require_integer(value: Any, path: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise InputError(f"{path} must be an integer")
    try:
        parsed = require_decimal(value, path)
        integer = int(parsed)
    except (DecimalException, ValueError) as exc:
        raise InputError(f"{path} must be an integer") from exc
    if Decimal(integer) != parsed or integer < minimum or integer > maximum:
        raise InputError(f"{path} must be an integer from {minimum} to {maximum}")
    return integer


def atomic_write_text(path: str | Path, text: str, *, max_bytes: int = MAX_REPORT_BYTES) -> None:
    """Write UTF-8 text using a same-directory replace after a bounded fsync."""
    raw = text.encode("utf-8")
    if len(raw) > max_bytes:
        raise InputError(f"output exceeds {max_bytes} bytes")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False) as handle:
            temporary = handle.name
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
