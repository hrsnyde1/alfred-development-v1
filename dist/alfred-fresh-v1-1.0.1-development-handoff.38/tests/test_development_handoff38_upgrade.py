"""handoff.38: diagnostics, host and both intake copies replaced, on disposable /tmp roots."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from development_handoff38 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
BASE_COMMIT = "2abfd88"  # main after handoff.37: today's bytes, plus 37's role.py
SOURCES = {
    transaction.LIBRARY + "diagnostics.py": "fresh_v1/diagnostics.py",
    transaction.LIBRARY + "host.py": "fresh_v1/host.py",
    transaction.DEVELOPER + "trusted_intake_development.py":
        "developer_v1/trusted_intake_development.py",
    transaction.INTAKE: "developer_v1/trusted_intake_development.py",
    transaction.LIBRARY + "role.py": "fresh_v1/role.py",
}


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def at_base(source, commit=BASE_COMMIT):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{source}"],
                          capture_output=True, check=True).stdout


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    pins = {**transaction.BASE, **transaction.DEPENDENCIES}
    for name, source in SOURCES.items():
        raw = at_base(source)
        assert upgrade.digest(raw) == pins[name], name
        write(upgrade.target(root, name), raw)
    write(upgrade.target(root, transaction.LIBRARY + "upgrade.py"),
          (ROOT / "fresh_v1/upgrade.py").read_bytes())
    for name in pins:
        upgrade.target(root, name).parent.chmod(0o755)
    write(upgrade.target(root, PAUSE), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    lines = []
    for source in sorted(set(transaction.DESTINATIONS.values())):
        write(release / source, (ROOT / source).read_bytes())
        lines.append(hashlib.sha256((ROOT / source).read_bytes()).hexdigest() + "  " + source)
    raw = ("\n".join(lines) + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def test_install_replaces_all_four_and_rollback_restores_them(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD"
    assert result["service_action"] == "restart alfred-development-intake.service"
    for name, source in transaction.DESTINATIONS.items():
        assert upgrade.target(root, name).read_bytes() == (ROOT / source).read_bytes()
    assert transaction.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_it_refuses_before_handoff_37(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, transaction.LIBRARY + "role.py"),
          at_base("fresh_v1/role.py", "21a5787"))
    with pytest.raises(ValueError):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


@pytest.mark.parametrize("name", list(transaction.BASE))
def test_it_refuses_a_file_that_is_not_the_installed_one(fixture, name):
    root, release, pin, backup = fixture
    write(upgrade.target(root, name), b"# not the installed file\n")
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


def test_pins_agree_with_handoff_37_and_this_release():
    after37 = (ROOT / "development_handoff37/installed-after.sha256").read_text()
    assert transaction.DEPENDENCIES[transaction.LIBRARY + "role.py"] in after37
    before = json.loads((ROOT / "development_handoff38/installed-sha256.json").read_bytes())
    assert before == transaction.BASE
    after = (ROOT / "development_handoff38/installed-after.sha256").read_text().splitlines()
    assert sorted(after) == sorted(
        upgrade.digest((ROOT / source).read_bytes()) + "  " + name
        for name, source in transaction.DESTINATIONS.items())
