"""Explicit, bounded report output with atomic replacement."""
import os
import tempfile
from pathlib import Path

from .canonical import InputError

MAX_REPORT_BYTES = 32 * 1024 * 1024

def protect_inputs(output: Path | None, inputs: list[Path], input_dir: Path | None = None) -> None:
    if output is None:
        return
    target = output.resolve()
    for source in inputs:
        if target == source.resolve() or (output.exists() and source.exists() and os.path.samefile(output, source)):
            raise InputError("report output must not replace an input file")
    if input_dir is not None and target.is_relative_to(input_dir.resolve()):
        raise InputError("report output must be outside the input directory")

def write_report(path: Path, text: str) -> None:
    raw = text.encode("utf-8")
    if len(raw) > MAX_REPORT_BYTES:
        raise InputError("report exceeds the output byte budget")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tracecanary-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
