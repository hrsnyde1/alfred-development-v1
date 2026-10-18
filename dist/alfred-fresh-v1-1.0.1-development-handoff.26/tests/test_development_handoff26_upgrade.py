"""handoff.26: the agents' own Claude token, only on disposable /tmp fixture roots."""

import grp
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from development_handoff26 import install_patch as transaction
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
# handoff.23 (merged after 73db588) installed this.
AFTER_23 = {"/usr/local/lib/alfred-completion-v1/completion_integration/runtime.py":
            ("71e5fc0", "completion_integration/runtime.py")}


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
        if name in AFTER_23:
            commit, source = AFTER_23[name]
            raw = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{source}"],
                                 capture_output=True, check=True).stdout
        else:
            raw = committed(SOURCES.get(name, "developer_v1/" + Path(name).name))
        assert upgrade.digest(raw) == sha, name
        write(upgrade.target(root, name), raw, mode_of(name))
    for directory in (transaction.DEVELOPER, transaction.DROP_INS, "/usr/local/sbin/",
                      "/usr/local/lib/alfred-completion-v1/completion_integration/"):
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


def test_handoff_23_must_be_installed_first(fixture):
    root, release, pin, backup = fixture
    runtime = upgrade.target(root, "/usr/local/lib/alfred-completion-v1/completion_integration/runtime.py")
    runtime.write_bytes(committed("completion_integration/runtime.py"))  # before handoff.23
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_the_release_copy_is_the_installed_worker_plus_this_fix_only():
    installed = committed("developer_v1/real_worker.py")
    shipped = (ROOT / "development_handoff26/real_worker.py").read_bytes()
    assert upgrade.digest(installed) == transaction.BASE[transaction.DEVELOPER + "real_worker.py"]
    assert b"team_profile" not in shipped  # unreleased team-snapshot work stays out
    assert b"CLAUDE_CODE_OAUTH_TOKEN" in shipped and b"CLAUDE_CODE_OAUTH_TOKEN" not in installed
