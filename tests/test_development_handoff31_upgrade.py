"""handoff.31: automatic squash merge and "undo" files, only on disposable /tmp fixture roots."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from development_handoff31 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
# main after handoff.29: exactly the installed bytes of every file below (checked
# against BASE), except QA's worker, which handoff.30 replaces first.
BASE_COMMIT = "8e385c9"
HANDOFF30_QA = "dist/alfred-fresh-v1-1.0.1-development-handoff.30/independent_qa/worker.py"
SOURCES = {
    transaction.POLICY: "development_handoff29/delegation.json",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "developer_v1/trusted_intake_development.py",
    transaction.LIBRARY + "upgrade.py": "fresh_v1/upgrade.py",
    transaction.LIBRARY + "protected.py": "fresh_v1/protected.py",
    transaction.DEVELOPER + "router.py": "developer_v1/router.py",
    transaction.COMPLETION + "delivery.py": "completion_integration/delivery.py",
    transaction.PUBLISHER + "askpass.py": "draft_pr_publisher/askpass.py",
}


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def base_bytes(name):
    if name == transaction.QA + "worker.py":
        return (ROOT / HANDOFF30_QA).read_bytes()
    source = SOURCES.get(name) or transaction.DESTINATIONS[name]
    if source.startswith("development_handoff"):
        return (ROOT / source).read_bytes()
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{source}"],
                          capture_output=True, check=True).stdout


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name, sha in {**transaction.BASE, **transaction.DEPENDENCIES}.items():
        if sha is None:
            upgrade.target(root, name).parent.mkdir(parents=True, exist_ok=True)
            continue
        raw = base_bytes(name)
        assert upgrade.digest(raw) == sha, name
        write(upgrade.target(root, name), raw)
    for name in {**transaction.BASE, **transaction.DEPENDENCIES}:
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


def test_install_replaces_every_file_and_rollback_restores_them(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n, sha in transaction.BASE.items() if sha}
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD"
    assert result["service_action"] == "restart alfred-development-intake.service"
    for name, source in transaction.DESTINATIONS.items():
        assert upgrade.target(root, name).read_bytes() == (ROOT / source).read_bytes()
    new = upgrade.target(root, transaction.DEVELOPER + "undo_approval.py")
    assert new.stat().st_mode & 0o777 == transaction.NEW_MODE
    transaction.rollback(root, backup)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw
    assert not new.exists()


def test_it_installs_only_after_handoff_30(fixture):
    root, release, pin, backup = fixture
    # QA's worker as installed before handoff.30 (the T-0007 bug).
    old = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:independent_qa/worker.py"],
                         capture_output=True, check=True).stdout
    write(upgrade.target(root, transaction.QA + "worker.py"), old)
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_drift_refuses_before_any_change(fixture):
    root, release, pin, backup = fixture
    policy = upgrade.target(root, transaction.POLICY)
    policy.write_bytes(policy.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_a_preexisting_undo_module_refuses(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, transaction.DEVELOPER + "undo_approval.py"), b"# planted\n")
    with pytest.raises(ValueError, match="new file already exists"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_the_new_policy_adds_only_merge_approval():
    old = json.loads((ROOT / "development_handoff29/delegation.json").read_text())
    new = json.loads((ROOT / "development_handoff31/delegation.json").read_text())
    assert new == {**old, "merge_approval": "delegated"}


def test_both_intake_copies_get_the_same_code():
    sources = {transaction.DESTINATIONS[n] for n in (
        transaction.DEVELOPER + "trusted_intake_development.py",
        "/usr/local/lib/alfred-v1.1/trusted_intake.py")}
    assert sources == {"developer_v1/trusted_intake_development.py"}


def test_installed_after_pins_are_the_release_files():
    lines = (ROOT / "development_handoff31/installed-after.sha256").read_text().splitlines()
    pins = dict(reversed(line.split("  ", 1)) for line in lines)
    assert set(pins) == set(transaction.DESTINATIONS)
    # The released tree, not the working copy: later changes (for example the
    # passkey approvals) move developer_v1 on without changing what handoff.31 installed.
    release = ROOT / "dist/alfred-fresh-v1-1.0.1-development-handoff.31"
    for name, source in transaction.DESTINATIONS.items():
        assert pins[name] == hashlib.sha256((release / source).read_bytes()).hexdigest()
