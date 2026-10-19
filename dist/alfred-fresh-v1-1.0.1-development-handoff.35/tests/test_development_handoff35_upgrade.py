"""handoff.35: both identity loaders replaced, on disposable /tmp fixture roots."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from development_handoff35 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
BASE_COMMIT = "027971b"  # main before this release: both loaders as installed
HANDOFF34 = transaction.DEVELOPER + "repo_intelligence.py"


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name, sha in transaction.BASE.items():
        raw = subprocess.run(["git", "-C", str(ROOT), "show",
                              f"{BASE_COMMIT}:developer_v1/{Path(name).name}"],
                             capture_output=True, check=True).stdout
        assert upgrade.digest(raw) == sha, name
        write(upgrade.target(root, name), raw)
    write(upgrade.target(root, transaction.LIBRARY + "upgrade.py"),
          (ROOT / "fresh_v1/upgrade.py").read_bytes())
    # handoff.34's installed file stands in by digest; its real bytes are not on main yet.
    stand_in = b"# handoff.34 repo_intelligence.py stand-in\n"
    write(upgrade.target(root, HANDOFF34), stand_in)
    monkeypatch.setitem(transaction.DEPENDENCIES, HANDOFF34, upgrade.digest(stand_in))
    for name in (*transaction.BASE, *transaction.DEPENDENCIES):
        upgrade.target(root, name).parent.chmod(0o755)
    write(upgrade.target(root, PAUSE), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    lines = []
    for source in transaction.DESTINATIONS.values():
        write(release / source, (ROOT / source).read_bytes())
        lines.append(hashlib.sha256((ROOT / source).read_bytes()).hexdigest() + "  " + source)
    raw = ("\n".join(sorted(lines, key=lambda l: l.split("  ")[1])) + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def test_install_replaces_both_loaders_and_rollback_restores_them(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    assert transaction.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    for name, source in transaction.DESTINATIONS.items():
        assert upgrade.target(root, name).read_bytes() == (ROOT / source).read_bytes()
    transaction.rollback(root, backup)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_it_refuses_before_handoff_34(fixture):
    root, release, pin, backup = fixture
    upgrade.target(root, HANDOFF34).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_the_handoff_34_pin_is_its_installed_after_hash():
    assert transaction.DEPENDENCIES[HANDOFF34] == (
        "fec05e8bf3ddc9594fd9cf0e07640da5b296523abc15db19ccbd7d0f79112064")
