"""handoff.27: three new files only, on disposable /tmp fixture roots."""

import hashlib
from pathlib import Path

import pytest

from development_handoff27 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    write(upgrade.target(root, transaction.LIBRARY + "upgrade.py"),
          (ROOT / "fresh_v1/upgrade.py").read_bytes())
    for directory in (transaction.LIBRARY, transaction.UNITS):
        upgrade.target(root, directory).mkdir(parents=True, exist_ok=True)
        upgrade.target(root, directory).chmod(0o755)
    write(upgrade.target(root, PAUSE), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    lines = []
    for source in transaction.DESTINATIONS.values():
        write(release / source, (ROOT / source).read_bytes())
        lines.append(hashlib.sha256((ROOT / source).read_bytes()).hexdigest() + "  " + source)
    raw = ("\n".join(sorted(lines, key=lambda l: l.split("  ")[1])) + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def test_install_adds_three_files_and_rollback_removes_them(fixture):
    root, release, pin, backup = fixture
    if upgrade.digest((ROOT / "fresh_v1/upgrade.py").read_bytes()) != \
            transaction.DEPENDENCIES[transaction.LIBRARY + "upgrade.py"]:
        pytest.skip("checkout upgrade.py differs from the installed pin")
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD"
    for name, source in transaction.DESTINATIONS.items():
        target = upgrade.target(root, name)
        assert target.read_bytes() == (ROOT / source).read_bytes()
        assert target.stat().st_mode & 0o777 == 0o644
    transaction.rollback(root, backup)
    assert not any(upgrade.target(root, n).exists() for n in transaction.DESTINATIONS)


def test_an_existing_file_or_missing_pause_refuses(fixture):
    root, release, pin, backup = fixture
    timer = upgrade.target(root, transaction.UNITS + "alfred-dev-squads.timer")
    timer.write_text("[Timer]\n")
    with pytest.raises(ValueError, match="already exists"):
        transaction.install(release, pin, root, backup)
    timer.unlink()
    upgrade.target(root, PAUSE).unlink()
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()
