"""handoff.18: one new sandbox drop-in, only on disposable /tmp fixture roots."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from development_handoff18 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
CONF = "development_handoff18/50-project-repos.conf"


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    drop_in = subprocess.run(
        ["git", "-C", str(ROOT), "show", "HEAD:fresh_v1/systemd/alfred-development-evidence.conf"],
        capture_output=True, check=True).stdout
    assert upgrade.digest(drop_in) == transaction.DEPENDENCIES[transaction.DROP_IN]
    write(upgrade.target(root, transaction.DROP_IN), drop_in)
    upgrade.target(root, transaction.DROP_IN).parent.chmod(0o755)
    write(upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE"), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    write(release / CONF, (ROOT / CONF).read_bytes())
    raw = (hashlib.sha256((ROOT / CONF).read_bytes()).hexdigest() + "  " + CONF + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def test_install_adds_only_the_new_drop_in_and_rollback_removes_it(fixture):
    root, release, pin, backup = fixture
    new = upgrade.target(root, transaction.PROJECT_REPOS)
    old = upgrade.target(root, transaction.DROP_IN).read_bytes()
    assert transaction.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    assert new.read_bytes() == (ROOT / CONF).read_bytes()
    assert oct(new.stat().st_mode & 0o777) == "0o644"
    assert upgrade.target(root, transaction.DROP_IN).read_bytes() == old
    transaction.rollback(root, backup)
    assert not new.exists()


def test_existing_drop_in_or_changed_sandbox_refuses(fixture):
    root, release, pin, backup = fixture
    upgrade.target(root, transaction.PROJECT_REPOS).write_text("[Service]\n")
    with pytest.raises(ValueError, match="already exists"):
        transaction.install(release, pin, root, backup)
    upgrade.target(root, transaction.PROJECT_REPOS).unlink()
    drop_in = upgrade.target(root, transaction.DROP_IN)
    drop_in.write_bytes(drop_in.read_bytes() + b"# drift\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_missing_pause_refuses(fixture):
    root, release, pin, backup = fixture
    upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE").unlink()
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)


def test_the_drop_in_lists_every_activated_project_repository():
    import json

    policy = json.loads((ROOT / "development_handoff12/policy.json").read_bytes())
    listed = {line.split("=", 1)[1].strip()
              for line in (ROOT / CONF).read_text().splitlines()
              if line.startswith("ReadWritePaths=")}
    calculator = policy["projects"]["dev-v1-accept"]["repository"]
    # The calculator's repository is already writable through the original unit.
    assert listed == {s["repository"] for s in policy["projects"].values()} - {calculator}
