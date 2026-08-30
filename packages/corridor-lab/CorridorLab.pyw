"""Double-click launcher for a checkout of Corridor Lab."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from corridor_lab.gui import main


if __name__ == "__main__":
    raise SystemExit(main())
