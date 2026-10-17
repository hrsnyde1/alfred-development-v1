"""Run the protected-source staging copies with the pinned, read-only Gateway library."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "staging" / ".dev" / "bin"))
sys.path.insert(0, "/home/alfred/Git/alfred/src")
