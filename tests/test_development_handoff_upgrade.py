"""Seven-file installation/rollback, only on disposable /tmp fixture roots."""

import hashlib
import json
from pathlib import Path

import pytest

from development_challenge import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
# The pinned handoff.2 payload; later releases change the live source tree.
HANDOFF2 = ROOT / "dist/alfred-fresh-v1-1.0.1-development-handoff.2"


def original(name, expected):
    if name.startswith(transaction.DEVELOPER):
        candidates = [
            ROOT
            / "dist/alfred-fresh-v1-1.0.1"
            / name.removeprefix(transaction.DEVELOPER)
        ]
    elif name.endswith("trusted_intake.py"):
        candidates = [
            ROOT
            / "dist/alfred-fresh-v1-1.0.1/developer_v1/trusted_intake_development.py"
        ]
    elif "/fresh_v1/" in name:
        candidates = [
            ROOT / "dist" / release / "fresh_v1" / Path(name).name
            for release in (
                "alfred-fresh-v1-1.0.1-T0003-recovery.1",
                "alfred-fresh-v1-1.0.1-planning-fix.1",
                "alfred-fresh-v1-1.0.1",
            )
        ]
    elif name.endswith("development-observe.mjs"):
        candidates = [ROOT / "v1_1b/staging/sidecar/development-observe.mjs"]
    else:
        # Unchanged Photon main is read only and pinned; never imported/executed.
        candidates = [Path(name)]
    for p in candidates:
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
    manifest = original(
        transaction.DEVELOPER + "developer_v1/release.sha256",
        transaction.BASE[transaction.DEVELOPER + "developer_v1/release.sha256"],
    )
    for name, sha in transaction.inventory(manifest).items():
        write(
            upgrade.target(root, transaction.DEVELOPER + name),
            original(transaction.DEVELOPER + name, sha),
        )
    for name in set(transaction.DESTINATIONS.values()):
        write(release / name, (HANDOFF2 / name).read_bytes())
    raw = "".join(
        hashlib.sha256((release / n).read_bytes()).hexdigest() + "  " + n + "\n"
        for n in sorted(transaction.DESTINATIONS.values())
        if n != "developer_v1/trusted_intake_development.py"
    ).encode()
    # The flat and package Intake mapping share exactly one payload file.
    raw += (
        hashlib.sha256(
            (release / "developer_v1/trusted_intake_development.py").read_bytes()
        ).hexdigest()
        + "  developer_v1/trusted_intake_development.py\n"
    ).encode()
    write(release / "MANIFEST.sha256", raw)
    for name in (
        upgrade.MARKER,
        "/home/alfred/Alfred/gateway/PAUSE",
        "/etc/alfred-fresh-v1/policy.json",
        "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/development-challenge.attempt.json",
        "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/context.json",
        "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/plan.recovery.json",
        "/home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json",
        "/var/lib/alfred-development-grants/T-0001.json",
        "/var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-result.json",
        "/var/lib/alfred-qa-state/T-0002.json",
        "/var/lib/alfred-reviewer-state/T-0002.json",
        "/var/lib/alfred-draft-pr-authorizations/T-0002.json",
        "/home/alfred/Alfred/completion-delivery/delivery.json",
        "/etc/alfred-v1.1/send-token",
    ):
        write(
            upgrade.target(root, name),
            b"PRESERVE ORIGINAL FIXTURE: " + name.encode(),
            mode=0o644 if name == upgrade.MARKER else 0o600,
        )
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_install_and_repeatable_rollback_touch_only_seven_mapped_files(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    assert transaction.install(release, pin, root, backup)["retry_authorized"] is False
    after = snapshot(root)
    assert {n for n in before if before[n] != after[n]} == {
        n.lstrip("/") for n in transaction.DESTINATIONS
    }
    assert transaction.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    assert snapshot(root) == before
    transaction.rollback(root, backup)
    assert snapshot(root) == before


@pytest.mark.parametrize("failed_entry", range(7))
def test_every_partial_install_failure_restores_code_and_preserves_evidence(
    fixture, failed_entry
):
    root, release, pin, backup = fixture
    before = snapshot(root)
    with pytest.raises(OSError, match="disposable fixture fault"):
        transaction.install(release, pin, root, backup, fail_after=failed_entry)
    assert snapshot(root) == before
    assert (backup / "index.json").exists()


@pytest.mark.parametrize(
    "bad", ["manifest", "base", "dependency", "other_developer", "pause"]
)
def test_preflight_stops_without_writing_or_broadening_permissions(fixture, bad):
    root, release, pin, backup = fixture
    if bad == "manifest":
        pin = "0" * 64
    elif bad == "base":
        upgrade.target(root, next(iter(transaction.BASE))).write_bytes(b"unexpected")
    elif bad == "dependency":
        upgrade.target(root, transaction.PHOTON + "index.mjs").write_bytes(
            b"unexpected"
        )
    elif bad == "other_developer":
        upgrade.target(
            root, transaction.DEVELOPER + "developer_v1/router.py"
        ).write_bytes(b"unexpected")
    else:
        upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE").unlink()
    before = snapshot(root)
    with pytest.raises(ValueError):
        transaction.install(release, pin, root, backup)
    assert snapshot(root) == before and not backup.exists()


def test_rollback_rejects_extra_destination_without_touching_anything(fixture):
    root, release, pin, backup = fixture
    transaction.install(release, pin, root, backup)
    index = json.loads((backup / "index.json").read_bytes())
    index["files"][0]["path"] = "/etc/alfred-fresh-v1/policy.json"
    (backup / "index.json").write_text(json.dumps(index))
    before = snapshot(root)
    with pytest.raises(ValueError, match="rollback inventory"):
        transaction.rollback(root, backup)
    assert snapshot(root) == before


def test_developer_inventory_delta_is_exactly_three_sources():
    old = transaction.inventory(
        (ROOT / "dist/alfred-fresh-v1-1.0.1/developer_v1/release.sha256").read_bytes()
    )
    new = transaction.inventory((HANDOFF2 / "developer_v1/release.sha256").read_bytes())
    assert old.keys() == new.keys()
    assert {n for n in old if old[n] != new[n]} == {
        "developer_v1/owner_grants.py",
        "developer_v1/trusted_intake_development.py",
        "developer_v1/stage_approval.py",
    }
