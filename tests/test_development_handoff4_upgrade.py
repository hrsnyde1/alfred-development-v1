"""handoff.4 four-file installation/rollback, only on disposable /tmp fixture roots."""

import hashlib
import json
from pathlib import Path

import pytest

from development_handoff4 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
BASELINES = (
    "alfred-fresh-v1-1.0.1-development-handoff.3",
    "alfred-fresh-v1-1.0.1-development-handoff.2",
    "alfred-fresh-v1-1.0.1-T0003-recovery.1",
    "alfred-fresh-v1-1.0.1-planning-fix.1",
    "alfred-fresh-v1-1.0.1",
)
NEW = transaction.LIBRARY + "qa_recovery.py"
PRESERVED = (
    "/home/alfred/Alfred/gateway/PAUSE",
    "/etc/alfred-fresh-v1/policy.json",
    "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0005/qa.attempt.json",
    "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0004/developer.failure.json",
    "/var/lib/alfred-development-grants/grant-ref.json",
    "/etc/systemd/system/alfred-development-evidence.service",
)


def original(name, expected):
    relative = (
        "fresh_v1/systemd/alfred-development-evidence.conf"
        if name == transaction.DROP_IN
        else "fresh_v1/" + Path(name).name
    )
    for release in BASELINES:
        p = ROOT / "dist" / release / relative
        if p.is_file() and upgrade.digest(p.read_bytes()) == expected:
            return p.read_bytes()
    raise AssertionError("pinned baseline fixture absent: " + name)


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name, sha in {**transaction.BASE, **transaction.DEPENDENCIES}.items():
        if sha is not None:
            write(upgrade.target(root, name), original(name, sha))
    for name in transaction.DESTINATIONS.values():
        write(release / name, (ROOT / name).read_bytes())
    raw = "".join(
        hashlib.sha256((release / n).read_bytes()).hexdigest() + "  " + n + "\n"
        for n in sorted(transaction.DESTINATIONS.values())
    ).encode()
    write(release / "MANIFEST.sha256", raw)
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    for name in PRESERVED:
        write(upgrade.target(root, name), b"PRESERVE: " + name.encode(), mode=0o600)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_install_writes_exactly_four_files_and_preserves_everything_else(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD" and result["retry_authorized"] is False
    after = snapshot(root)
    changed = {k for k in after if before.get(k) != after[k]}
    assert changed == {name.lstrip("/") for name in transaction.DESTINATIONS}
    for name, source in transaction.DESTINATIONS.items():
        assert after[name.lstrip("/")][0] == (ROOT / source).read_bytes()
    assert after[NEW.lstrip("/")][1] & 0o777 == 0o644
    drop_in = upgrade.target(root, transaction.DROP_IN).read_text()
    assert (
        "ReadWritePaths=/home/alfred/alfred-development-lab/milestone2/task-a/"
        "live-acceptance/repo\n" in drop_in
    )
    assert "ReadWritePaths=/var/lib/alfred-development-grants" in drop_in
    index = json.loads((backup / "index.json").read_bytes())
    assert [e["sha256"] for e in index["files"]] == list(transaction.BASE.values())


def test_rollback_restores_handoff3_and_removes_the_new_file(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    transaction.install(release, pin, root, backup)
    assert transaction.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    assert snapshot(root) == before
    assert not upgrade.target(root, NEW).exists()


@pytest.mark.parametrize("fail_after", [1, 2, 3])
def test_fault_mid_install_rolls_back(fixture, fail_after):
    root, release, pin, backup = fixture
    before = snapshot(root)
    with pytest.raises(OSError):
        transaction.install(release, pin, root, backup, fail_after=fail_after)
    assert snapshot(root) == before


def test_missing_pause_refuses_before_any_change(fixture):
    root, release, pin, backup = fixture
    upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE").unlink()
    before = snapshot(root)
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)
    assert snapshot(root) == before and not backup.exists()


@pytest.mark.parametrize(
    "name",
    [
        transaction.LIBRARY + "host.py",
        transaction.LIBRARY + "handoffs.py",
        transaction.DROP_IN,
        transaction.LIBRARY + "role.py",
    ],
)
def test_unexpected_installed_bytes_refuse_before_any_change(fixture, name):
    root, release, pin, backup = fixture
    path = upgrade.target(root, name)
    path.write_bytes(path.read_bytes() + b"\n# drift\n")
    before = snapshot(root)
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert snapshot(root) == before and not backup.exists()


def test_existing_new_file_refuses(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, NEW), b"unexpected")
    before = snapshot(root)
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert snapshot(root) == before and not backup.exists()


def test_wrong_manifest_pin_and_second_install_refuse(fixture):
    root, release, pin, backup = fixture
    with pytest.raises(ValueError, match="manifest pin"):
        transaction.install(release, "0" * 64, root, backup)
    transaction.install(release, pin, root, backup)
    after = snapshot(root)
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup.with_name("backup-2"))
    assert snapshot(root) == after


def test_host_root_requires_root_privilege(fixture, monkeypatch):
    _, release, pin, backup = fixture
    monkeypatch.setattr(upgrade.os, "geteuid", lambda: 1000)
    with pytest.raises(PermissionError):
        transaction.install(release, pin, Path("/"), backup)
