"""handoff.37: the plan step's role.py replaced, on disposable /tmp fixture roots."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from development_handoff37 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
BASE_COMMIT = "21a5787"  # main after handoff.36: exactly the bytes installed today
SOURCES = {
    transaction.LIBRARY + "role.py": "fresh_v1/role.py",
    transaction.LIBRARY + "host.py": "fresh_v1/host.py",
    transaction.DEVELOPER + "agent_profiles.json": "developer_v1/agent_profiles.json",
}


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    pins = {**transaction.BASE, **transaction.DEPENDENCIES}
    for name, source in SOURCES.items():
        raw = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{source}"],
                             capture_output=True, check=True).stdout
        assert upgrade.digest(raw) == pins[name], name
        write(upgrade.target(root, name), raw)
    write(upgrade.target(root, transaction.LIBRARY + "upgrade.py"),
          (ROOT / "fresh_v1/upgrade.py").read_bytes())
    for name in pins:
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


def test_install_replaces_role_and_rollback_restores_it(fixture):
    root, release, pin, backup = fixture
    name = transaction.LIBRARY + "role.py"
    before = upgrade.target(root, name).read_bytes()
    assert transaction.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    assert upgrade.target(root, name).read_bytes() == (ROOT / "fresh_v1/role.py").read_bytes()
    transaction.rollback(root, backup)
    assert upgrade.target(root, name).read_bytes() == before


def test_it_refuses_before_handoff_36(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, transaction.DEVELOPER + "agent_profiles.json"), b"{}\n")
    with pytest.raises(ValueError):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_it_refuses_a_different_host_py(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, transaction.LIBRARY + "host.py"), b"# another host.py\n")
    with pytest.raises(ValueError):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_the_handoff_36_pin_is_its_installed_after_hash():
    after = (ROOT / "development_handoff36/installed-after.sha256").read_text()
    assert transaction.DEPENDENCIES[transaction.DEVELOPER + "agent_profiles.json"] in after
