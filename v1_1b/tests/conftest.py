import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v1_1a" / "staging" / ".dev" / "bin"))
sys.path.insert(0, "/home/alfred/Git/alfred/src")
sys.path.insert(0, str(ROOT / "v1_1b"))
