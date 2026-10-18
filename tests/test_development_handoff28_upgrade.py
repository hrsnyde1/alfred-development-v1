"""handoff.28: one file replaced, on disposable /tmp fixture roots."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from development_handoff28 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
SQUADS = transaction.LIBRARY + "squads.py"


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    installed = (ROOT / "dist/alfred-fresh-v1-1.0.1-development-handoff.27/fresh_v1/squads.py").read_bytes()
    assert upgrade.digest(installed) == transaction.BASE[SQUADS]
    write(upgrade.target(root, SQUADS), installed)
    write(upgrade.target(root, transaction.LIBRARY + "upgrade.py"),
          (ROOT / "fresh_v1/upgrade.py").read_bytes())
    upgrade.target(root, transaction.LIBRARY).chmod(0o755)
    write(upgrade.target(root, PAUSE), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    source = transaction.DESTINATIONS[SQUADS]
    write(release / source, (ROOT / source).read_bytes())
    raw = (hashlib.sha256((ROOT / source).read_bytes()).hexdigest() + "  " + source + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def test_install_replaces_the_announcer_and_rollback_restores_it(fixture):
    root, release, pin, backup = fixture
    before = upgrade.target(root, SQUADS).read_bytes()
    assert transaction.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    assert upgrade.target(root, SQUADS).read_bytes() == (ROOT / "fresh_v1/squads.py").read_bytes()
    transaction.rollback(root, backup)
    assert upgrade.target(root, SQUADS).read_bytes() == before


def test_drift_or_missing_pause_refuses(fixture):
    root, release, pin, backup = fixture
    target = upgrade.target(root, SQUADS)
    target.write_bytes(target.read_bytes() + b"# drift\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    upgrade.target(root, PAUSE).unlink()
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()
