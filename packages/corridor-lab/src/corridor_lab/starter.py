"""Create one self-contained fictional scenario without overwriting files."""
from pathlib import Path
from .canonical import canonical_dumps
from .gui_controller import BUILTIN_DEMO_SCENARIO
from .scenario import parse_scenario


def write_starter(destination: Path) -> None:
    parse_scenario(BUILTIN_DEMO_SCENARIO)
    text = canonical_dumps(BUILTIN_DEMO_SCENARIO)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
