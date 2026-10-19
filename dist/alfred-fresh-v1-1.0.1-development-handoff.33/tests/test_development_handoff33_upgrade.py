"""handoff.33: the owner approves the CTO plan, only on disposable /tmp fixture roots."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from developer_v1 import owner_grants
from development_handoff33 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
# main after handoff.32 (and the passkey approvals): exactly the installed bytes of
# every file below, checked against BASE and DEPENDENCIES. The policy is handoff.31's.
BASE_COMMIT = "cc6263f"
SOURCES = {
    transaction.POLICY: "development_handoff31/delegation.json",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "developer_v1/trusted_intake_development.py",
}


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def base_bytes(name):
    source = SOURCES.get(name) or transaction.DESTINATIONS.get(name)
    if source is None:
        # A dependency: its path below the installed package root.
        for prefix, package in ((transaction.LIBRARY, "fresh_v1/"),
                                (transaction.DEVELOPER, "developer_v1/")):
            if name.startswith(prefix):
                source = package + name.removeprefix(prefix)
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
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    modes = {n: upgrade.target(root, n).stat().st_mode & 0o777 for n in transaction.BASE}
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD"
    assert result["service_action"] == "restart alfred-development-intake.service"
    for name, source in transaction.DESTINATIONS.items():
        assert upgrade.target(root, name).read_bytes() == (ROOT / source).read_bytes()
        assert upgrade.target(root, name).stat().st_mode & 0o777 == modes[name]
    transaction.rollback(root, backup)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_it_installs_only_on_the_live_handoff_32_bytes(fixture):
    root, release, pin, backup = fixture
    # The intake as installed before the passkey approvals.
    old = subprocess.run(["git", "-C", str(ROOT), "show",
                          "ce2f2e1:developer_v1/trusted_intake_development.py"],
                         capture_output=True, check=True).stdout
    write(upgrade.target(root, "/usr/local/lib/alfred-v1.1/trusted_intake.py"), old)
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_drift_in_a_dependency_refuses_before_any_change(fixture):
    root, release, pin, backup = fixture
    path = upgrade.target(root, transaction.DEVELOPER + "publication_approval.py")
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()
    assert upgrade.target(root, transaction.POLICY).read_bytes() == base_bytes(transaction.POLICY)


def test_a_fault_midway_restores_every_file(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    with pytest.raises(OSError, match="disposable fixture fault"):
        transaction.install(release, pin, root, backup, fail_after=4)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_the_new_policy_only_puts_development_in_owner_mode(tmp_path):
    old = json.loads((ROOT / "development_handoff31/delegation.json").read_text())
    new = json.loads((ROOT / "development_handoff33/delegation.json").read_text())
    assert new == {**old, "development_approval": {**old["development_approval"],
                                                    "mode": "owner"}}
    path = tmp_path / "delegation.json"
    path.write_bytes((ROOT / "development_handoff33/delegation.json").read_bytes())
    path.chmod(0o644)
    policy = owner_grants.load_delegation_policy(path, owner_uid=os.geteuid())
    for project in old["development_approval"]["projects"]:
        assert owner_grants.plan_approval_requested(policy, project)
        assert not owner_grants.delegation_permits(policy, project)
        assert owner_grants.merge_delegation_permits(policy, project)


def test_both_intake_copies_get_the_same_code():
    sources = {transaction.DESTINATIONS[n] for n in (
        transaction.DEVELOPER + "trusted_intake_development.py",
        "/usr/local/lib/alfred-v1.1/trusted_intake.py")}
    assert sources == {"developer_v1/trusted_intake_development.py"}


def test_installed_after_pins_are_the_release_files():
    lines = (ROOT / "development_handoff33/installed-after.sha256").read_text().splitlines()
    pins = dict(reversed(line.split("  ", 1)) for line in lines)
    assert set(pins) == set(transaction.DESTINATIONS)
    release = ROOT / "dist/alfred-fresh-v1-1.0.1-development-handoff.33"
    for name, source in transaction.DESTINATIONS.items():
        assert pins[name] == hashlib.sha256((release / source).read_bytes()).hexdigest()


def test_installed_before_pins_are_the_base():
    assert json.loads((ROOT / "development_handoff33/installed-sha256.json").read_text()) \
        == transaction.BASE
