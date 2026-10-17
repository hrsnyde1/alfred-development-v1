"""Run the existing Intake regression suite against the currently staged source."""

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from developer_v1.install_config import EXPECTED_INTAKE_SHA256

STAGED = ROOT / "developer_v1" / "trusted_intake_development.py"
INSTALLED = Path("/usr/local/lib/alfred-v1.1/trusted_intake.py")


def main() -> int:
    staged = STAGED.read_bytes()
    installed = INSTALLED.read_bytes()
    if staged != installed or hashlib.sha256(installed).hexdigest() != EXPECTED_INTAKE_SHA256:
        raise RuntimeError("installed Intake differs from reviewed staged source")
    spec = importlib.util.spec_from_file_location("trusted_intake", STAGED)
    module = importlib.util.module_from_spec(spec)
    sys.modules["trusted_intake"] = module
    spec.loader.exec_module(module)
    return pytest.main([str(ROOT / "v1_1b" / "tests" / "test_intake.py"),
                        str(ROOT / "v1_1b" / "tests" / "test_turn_binding.py"),
                        "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
