"""handoff.21: the Claude route and agent identities, only on disposable /tmp fixture roots."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from development_handoff21 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
# The commit handoff.21 was built on: its installed base.
BASE_COMMIT = "abc35f0"


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def committed(name):
    return subprocess.run(["git", "-C", str(ROOT), "show", BASE_COMMIT + ":" + name],
                          capture_output=True, check=True).stdout


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    # The installed base is the code this branch started from.
    for name, sha in transaction.BASE.items():
        if sha is not None:
            raw = committed("developer_v1/" + Path(name).name)
            assert upgrade.digest(raw) == sha
            write(upgrade.target(root, name), raw)
    for name, sha in transaction.DEPENDENCIES.items():
        if name.startswith(transaction.DEVELOPER):
            raw = committed("developer_v1/" + Path(name).name)
        elif name == transaction.DROP_IN:
            raw = committed("fresh_v1/systemd/alfred-development-evidence.conf")
        else:
            raw = committed("development_handoff18/50-project-repos.conf")
        assert upgrade.digest(raw) == sha, name
        write(upgrade.target(root, name), raw)
    for directory in (transaction.DEVELOPER, transaction.DROP_INS):
        upgrade.target(root, directory).chmod(0o755)
    write(upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE"), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    lines = []
    for source in transaction.DESTINATIONS.values():
        write(release / source, (ROOT / source).read_bytes())
        lines.append(hashlib.sha256((ROOT / source).read_bytes()).hexdigest() + "  " + source)
    raw = ("\n".join(sorted(lines, key=lambda l: l.split("  ")[1])) + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def test_install_replaces_two_files_adds_three_and_rollback_restores(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n, sha in transaction.BASE.items() if sha}
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD"
    assert result["service_action"] == "systemctl daemon-reload"
    for name, source in transaction.DESTINATIONS.items():
        target = upgrade.target(root, name)
        assert target.read_bytes() == (ROOT / source).read_bytes()
        assert oct(target.stat().st_mode & 0o777) == "0o644"
    transaction.rollback(root, backup)
    for name, sha in transaction.BASE.items():
        target = upgrade.target(root, name)
        assert target.read_bytes() == before[name] if sha else not target.exists()


def test_drift_or_an_existing_new_file_refuses_before_any_change(fixture):
    root, release, pin, backup = fixture
    login = upgrade.target(root, transaction.CLAUDE_LOGIN)
    login.write_text("[Service]\n")
    with pytest.raises(ValueError, match="already exists"):
        transaction.install(release, pin, root, backup)
    login.unlink()
    router = upgrade.target(root, transaction.DEVELOPER + "router.py")
    router.write_bytes(router.read_bytes() + b"# drift\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_missing_pause_refuses(fixture):
    root, release, pin, backup = fixture
    upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE").unlink()
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)


def test_the_drop_in_only_opens_the_claude_login():
    lines = [line for line in (ROOT / transaction.DESTINATIONS[transaction.CLAUDE_LOGIN])
             .read_text().splitlines() if line and not line.startswith("#")]
    home = "/home/alfred/." + "claude"
    assert lines == ["[Service]", f"ReadWritePaths=-{home} -{home}.json"]
