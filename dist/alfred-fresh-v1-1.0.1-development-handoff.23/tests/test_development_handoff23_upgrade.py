"""handoff.23: the agents' own Claude token, only on disposable /tmp fixture roots."""

import grp
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from development_handoff23 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
# main with handoffs 21 and 22: exactly the installed base.
BASE_COMMIT = "73db588"
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
SOURCES = {
    transaction.DROP_IN: "fresh_v1/systemd/alfred-development-evidence.conf",
    transaction.DROP_INS + "50-project-repos.conf": "development_handoff18/50-project-repos.conf",
    transaction.CLAUDE_LOGIN: "development_handoff21/60-claude-agents.conf",
    "/usr/local/sbin/alfred-dev-ops": "ops/alfred_dev_ops.py",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py": "fresh_v1/handoffs.py",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py": "fresh_v1/host.py",
}


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def committed(name):
    return subprocess.run(["git", "-C", str(ROOT), "show", BASE_COMMIT + ":" + name],
                          capture_output=True, check=True).stdout


def mode_of(name):
    return 0o755 if name.endswith("alfred-dev-ops") else 0o644


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name, sha in {**transaction.BASE, **transaction.DEPENDENCIES}.items():
        raw = committed(SOURCES.get(name, "developer_v1/" + Path(name).name))
        assert upgrade.digest(raw) == sha, name
        write(upgrade.target(root, name), raw, mode_of(name))
    for directory in (transaction.DEVELOPER, transaction.DROP_INS, "/usr/local/sbin/"):
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


def test_install_replaces_three_files_keeping_modes_and_rollback_restores(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD"
    assert result["service_action"] == "systemctl daemon-reload"
    for name, source in transaction.DESTINATIONS.items():
        target = upgrade.target(root, name)
        assert target.read_bytes() == (ROOT / source).read_bytes()
        assert target.stat().st_mode & 0o777 == mode_of(name)
    transaction.rollback(root, backup)
    for name in transaction.BASE:
        assert upgrade.target(root, name).read_bytes() == before[name]


def test_drift_refuses_before_any_change(fixture):
    root, release, pin, backup = fixture
    router = upgrade.target(root, transaction.DEVELOPER + "router.py")
    router.write_bytes(router.read_bytes() + b"# drift\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_missing_pause_refuses(fixture):
    root, release, pin, backup = fixture
    upgrade.target(root, PAUSE).unlink()
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)


def test_claude_token_is_saved_root_owned_group_readable_and_never_echoed(tmp_path, monkeypatch):
    from ops import alfred_dev_ops as ops

    target = tmp_path / "claude-agents.token"
    monkeypatch.setattr(ops, "CLAUDE_TOKEN", target)
    monkeypatch.setattr(ops.os, "fchown", lambda fd, uid, gid: None)
    monkeypatch.setattr(ops.grp, "getgrnam",
                        lambda name: grp.struct_group(("alfred", "x", 1000, [])))
    token = "sk-ant-oat01-" + "a" * 50
    result = ops.claude_token("  " + token + "\n")
    assert target.read_text() == token + "\n"
    assert target.stat().st_mode & 0o777 == 0o640
    assert token not in json.dumps(result) and len(result["fingerprint"]) == 12
    with pytest.raises(ops.Refused):
        ops.claude_token("not a token with spaces")
    assert target.read_text() == token + "\n"
