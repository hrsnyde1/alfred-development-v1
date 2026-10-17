"""handoff.6 four-file installation/rollback, only on disposable /tmp fixture roots."""

import hashlib
import json
from pathlib import Path

import pytest

from development_handoff6 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
# Install and compare against the pinned handoff.6 payload, not the live source tree,
# which later handoffs change (handoff.8 updates developer_v1/release.sha256).
PAYLOAD = DIST / "alfred-fresh-v1-1.0.1-development-handoff.6"
REVIEWER_V4 = ROOT / "independent_reviewer/host-candidate-v4/independent_reviewer"
PRESERVED = (
    "/home/alfred/Alfred/gateway/PAUSE",
    "/etc/alfred-fresh-v1/policy.json",
    "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0007/developer.failure.json",
    "/var/lib/alfred-development-grants/grant-ref.json",
    "/opt/alfred-reviewer-v1/bin/codex",
)


def candidates(name):
    if name.startswith(transaction.REVIEWER):
        return [REVIEWER_V4 / name.removeprefix(transaction.REVIEWER)]
    if name.startswith("/opt/alfred-developer-v1/"):
        relative = name.removeprefix("/opt/alfred-developer-v1/")
        return [DIST / r / relative for r in (
            "alfred-fresh-v1-1.0.1-development-handoff.2", "alfred-fresh-v1-1.0.1")]
    return [DIST / r / "fresh_v1" / Path(name).name for r in (
        "alfred-fresh-v1-1.0.1-development-handoff.5",
        "alfred-fresh-v1-1.0.1-development-handoff.4",
        "alfred-fresh-v1-1.0.1-development-handoff.2",
        "alfred-fresh-v1-1.0.1")]


def original(name, expected):
    for p in candidates(name):
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
        write(upgrade.target(root, name), original(name, sha))
    # Every other file the two installed inventories list, at its recorded bytes.
    for inventory, (base, _changed) in transaction.INVENTORIES.items():
        rows = transaction.inventory_lines(upgrade.target(root, inventory).read_bytes())
        for name, sha in rows.items():
            path = upgrade.target(root, base + name)
            if not path.exists():
                write(path, original(base + name, sha))
    for name in transaction.DESTINATIONS.values():
        write(release / name, (PAYLOAD / name).read_bytes())
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


def test_install_replaces_exactly_four_files_with_consistent_inventories(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD" and result["retry_authorized"] is False
    after = snapshot(root)
    changed = {k for k in after if before.get(k) != after[k]}
    assert changed == {name.lstrip("/") for name in transaction.DESTINATIONS}
    for name, source in transaction.DESTINATIONS.items():
        assert after[name.lstrip("/")][0] == (PAYLOAD / source).read_bytes()
        assert after[name.lstrip("/")][1] == before[name.lstrip("/")][1]  # Mode kept.
    for inventory, (base, _changed) in transaction.INVENTORIES.items():
        rows = transaction.inventory_lines(upgrade.target(root, inventory).read_bytes())
        for name, sha in rows.items():
            assert upgrade.digest(upgrade.target(root, base + name).read_bytes()) == sha
    index = json.loads((backup / "index.json").read_bytes())
    assert [e["sha256"] for e in index["files"]] == list(transaction.BASE.values())


def test_rollback_restores_the_previous_developer_and_reviewer(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    transaction.install(release, pin, root, backup)
    assert transaction.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    assert snapshot(root) == before


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
        transaction.DEVELOPER + "real_worker.py",
        transaction.REVIEWER + "worker.py",
        transaction.LIBRARY + "role.py",
        transaction.DEVELOPER + "pipeline.py",  # Listed in the Developer inventory.
        transaction.REVIEWER + "config.json",  # Listed in the Reviewer inventory.
    ],
)
def test_unexpected_installed_bytes_refuse_before_any_change(fixture, name):
    root, release, pin, backup = fixture
    path = upgrade.target(root, name)
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b"\n# drift\n")
    before = snapshot(root)
    with pytest.raises(ValueError, match="mismatch"):
        transaction.install(release, pin, root, backup)
    assert snapshot(root) == before and not backup.exists()


def test_inventory_that_changes_another_line_refuses(fixture, tmp_path):
    root, release, _pin, backup = fixture
    inventory = release / "developer_v1/release.sha256"
    lines = inventory.read_text().splitlines()
    lines = [("0" * 64 + l[64:]) if l.endswith("developer_v1/pipeline.py") else l for l in lines]
    inventory.write_text("\n".join(lines) + "\n")
    raw = "".join(
        hashlib.sha256((release / n).read_bytes()).hexdigest() + "  " + n + "\n"
        for n in sorted(transaction.DESTINATIONS.values())
    ).encode()
    write(release / "MANIFEST.sha256", raw)
    before = snapshot(root)
    with pytest.raises(ValueError, match="inventory delta"):
        transaction.install(release, upgrade.digest(raw), root, backup)
    assert snapshot(root) == before


def test_wrong_manifest_pin_and_second_install_refuse(fixture):
    root, release, pin, backup = fixture
    with pytest.raises(ValueError, match="manifest pin"):
        transaction.install(release, "0" * 64, root, backup)
    transaction.install(release, pin, root, backup)
    after = snapshot(root)
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup.with_name("backup-2"))
    assert snapshot(root) == after
