"""handoff.39: role.py, router.py and the plan schema replaced, on /tmp fixture roots."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from development_handoff39 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
BASE_COMMIT = "ccc0510"  # main after handoff.37 and .38: the bytes installed today
SOURCES = {
    transaction.LIBRARY + "role.py": "fresh_v1/role.py",
    transaction.DEVELOPER + "router.py": "developer_v1/router.py",
    transaction.CTO + "plan.schema.json": "v1_cto/plan.schema.json",
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


def test_install_replaces_all_three_and_rollback_restores_them(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    assert transaction.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    for name, source in transaction.DESTINATIONS.items():
        assert upgrade.target(root, name).read_bytes() == (ROOT / source).read_bytes()
    transaction.rollback(root, backup)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_it_refuses_before_handoff_37(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, transaction.LIBRARY + "role.py"), b"# handoff.34 role.py\n")
    with pytest.raises(ValueError):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_a_failure_midway_rolls_every_file_back(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    with pytest.raises(OSError):
        transaction.install(release, pin, root, backup, fail_after=2)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_the_handoff_37_pin_is_its_installed_after_hash():
    after = (ROOT / "development_handoff37/installed-after.sha256").read_text()
    assert transaction.BASE[transaction.LIBRARY + "role.py"] in after


def test_the_release_restarts_intake_which_loads_router_once():
    builder = (ROOT / "development_handoff39/build_release.py").read_text()
    assert '"restart": ["alfred-development-intake.service"]' in builder
