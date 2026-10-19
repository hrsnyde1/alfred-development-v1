"""handoff.36: loader and identity bundle replaced, on disposable /tmp fixture roots."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from developer_v1 import agent_profiles
from development_handoff36 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
BASE_COMMIT = "8ba82cb"  # main after handoff.35: exactly the bytes installed today
SNAPSHOT = transaction.DEVELOPER + "team_snapshot.py"


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def at_base(name):
    return subprocess.run(["git", "-C", str(ROOT), "show",
                           f"{BASE_COMMIT}:developer_v1/{Path(name).name}"],
                          capture_output=True, check=True).stdout


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name, sha in {**transaction.BASE, SNAPSHOT: transaction.DEPENDENCIES[SNAPSHOT]}.items():
        raw = at_base(name)
        assert upgrade.digest(raw) == sha, name
        write(upgrade.target(root, name), raw)
    write(upgrade.target(root, transaction.LIBRARY + "upgrade.py"),
          (ROOT / "fresh_v1/upgrade.py").read_bytes())
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


def test_install_replaces_loader_and_bundle_and_rollback_restores_them(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    assert transaction.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    for name, source in transaction.DESTINATIONS.items():
        assert upgrade.target(root, name).read_bytes() == (ROOT / source).read_bytes()
    transaction.rollback(root, backup)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_the_installed_bundle_gives_every_agent_the_charter_once(fixture):
    root, release, pin, backup = fixture
    transaction.install(release, pin, root, backup)
    bundle = upgrade.target(root, transaction.DEVELOPER + "agent_profiles.json")
    for agent in json.loads(bundle.read_text())["agents"]:
        text = agent_profiles.identity(agent, bundle)
        assert text.startswith("# Workforce charter") and text.count("# Workforce charter") == 1


def test_it_refuses_without_handoff_35(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, SNAPSHOT), b"# not handoff.35's team_snapshot.py\n")
    with pytest.raises(ValueError):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_it_refuses_a_bundle_that_is_not_the_installed_one(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, transaction.DEVELOPER + "agent_profiles.json"), b"{}\n")
    with pytest.raises(ValueError):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_a_failure_midway_rolls_both_files_back(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    with pytest.raises(OSError):
        transaction.install(release, pin, root, backup, fail_after=1)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw
