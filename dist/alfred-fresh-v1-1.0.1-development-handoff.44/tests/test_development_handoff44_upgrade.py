"""handoff.44: two handoff.43 files change and seven are new, on disposable /tmp fixture roots."""

import hashlib
import json
from pathlib import Path

import pytest

from development_handoff44 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
SERVICE43 = ROOT / "development_handoff43/alfred-photon-watchdog.service"


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def handoff43_watchdog():
    release = ROOT / "dist/alfred-fresh-v1-1.0.1-development-handoff.43/fresh_v1/photon_watchdog.py"
    return release.read_bytes()


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name in transaction.DEPENDENCIES:
        write(upgrade.target(root, name), (ROOT / "fresh_v1" / Path(name).name).read_bytes())
    for directory in {str(Path(n).parent) + "/" for n in transaction.DESTINATIONS}:
        upgrade.target(root, directory).mkdir(parents=True, exist_ok=True)
        upgrade.target(root, directory).chmod(0o755)
    write(upgrade.target(root, transaction.LIBRARY + "photon_watchdog.py"), handoff43_watchdog())
    write(upgrade.target(root, transaction.UNITS + "alfred-photon-watchdog.service"),
          SERVICE43.read_bytes())
    write(upgrade.target(root, PAUSE), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    lines = []
    for source in transaction.DESTINATIONS.values():
        write(release / source, (ROOT / source).read_bytes())
        lines.append(hashlib.sha256((ROOT / source).read_bytes()).hexdigest() + "  " + source)
    raw = ("\n".join(sorted(lines, key=lambda l: l.split("  ")[1])) + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def pinned():
    return all(upgrade.digest((ROOT / "fresh_v1" / Path(n).name).read_bytes()) == sha
               for n, sha in transaction.DEPENDENCIES.items())


def test_install_then_rollback_restores_handoff43(fixture):
    root, release, pin, backup = fixture
    if not pinned():
        pytest.skip("checkout dependencies differ from the installed pins")
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD"
    for name, source in transaction.DESTINATIONS.items():
        target = upgrade.target(root, name)
        assert target.read_bytes() == (ROOT / source).read_bytes()
        assert target.stat().st_mode & 0o777 == transaction.MODES.get(name, 0o644)
    transaction.rollback(root, backup)
    for name, sha in transaction.BASE.items():
        target = upgrade.target(root, name)
        assert (upgrade.digest(target.read_bytes()) == sha) if sha else not target.exists()


def test_refuses_without_handoff43_or_pause(fixture):
    root, release, pin, backup = fixture
    upgrade.target(root, transaction.LIBRARY + "photon_watchdog.py").write_text("# other\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    upgrade.target(root, PAUSE).unlink()
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_pins_agree_with_this_release():
    before = json.loads((ROOT / "development_handoff44/installed-sha256.json").read_bytes())
    assert before == transaction.BASE
    assert transaction.BASE[transaction.LIBRARY + "photon_watchdog.py"] == \
        upgrade.digest(handoff43_watchdog())
    after43 = (ROOT / "development_handoff43/installed-after.sha256").read_text()
    for name, sha in transaction.BASE.items():
        if sha:
            assert f"{sha}  {name}" in after43
    after = (ROOT / "development_handoff44/installed-after.sha256").read_text().splitlines()
    assert sorted(after) == sorted(
        upgrade.digest((ROOT / source).read_bytes()) + "  " + name
        for name, source in transaction.DESTINATIONS.items())


def test_units_spool_and_group():
    unit = (ROOT / "development_handoff44/alfred-photon-watchdog.service").read_text()
    assert "StateDirectoryMode=0711" in unit
    assert "ReadWritePaths=-/var/lib/alfred-photon-requests" in unit
    path = (ROOT / "development_handoff44/alfred-photon-requests.path").read_text()
    assert "PathExistsGlob=/var/lib/alfred-photon-requests/*.json" in path
    assert "Unit=alfred-photon-watchdog.service" in path
    tmpfiles = (ROOT / "development_handoff44/alfred-photon.tmpfiles.conf").read_text()
    assert "d /var/lib/alfred-photon-requests 1770 root alfredphoton -" in tmpfiles
    sysusers = (ROOT / "development_handoff44/alfred-photon.sysusers.conf").read_text()
    assert "m alfredos alfredphoton" in sysusers and "m alfredmsg alfredphoton" in sysusers
    board = (ROOT / "development_handoff44/alfred-dev-board.service").read_text()
    assert "from fresh_v1.dev_board import main" in board and "PrivateNetwork=yes" in board
    timer = (ROOT / "development_handoff44/alfred-dev-board.timer").read_text()
    assert "OnUnitInactiveSec=20s" in timer
