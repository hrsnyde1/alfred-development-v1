"""Only /tmp disposable fixture roots; no services or protected state touched."""

import hashlib
import shutil
from pathlib import Path

import pytest

import fresh_v1_development_diagnostics_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "dist/alfred-fresh-v1-1.0.1"


@pytest.fixture
def fixture(tmp_path):
    host = tmp_path / "host"
    host.mkdir()
    (host / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for line in (ORIGINAL / transaction.MANIFEST).read_text().splitlines():
        _, name = line.split("  ", 1)
        dest = upgrade.target(host, "/opt/alfred-developer-v1/" + name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ORIGINAL / name, dest)
    for dest, name in transaction.DESTINATIONS.items():
        path = upgrade.target(host, dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ORIGINAL / name, path)
        path.chmod(0o644)
    for name, raw in {
        upgrade.MARKER: b"original activation marker\n",
        "/home/alfred/Alfred/gateway/PAUSE": b"operator pause\n",
        "/etc/alfred-fresh-v1/policy.json": b"protected policy unchanged\n",
        "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/development-challenge.attempt.json": b'{"stage":"development-challenge","status":"uncertain_until_result"}\n',
        "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/context.json": b"original frozen context\n",
        "/home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json": b"original frozen plan\n",
        "/var/lib/alfred-development-grants/historical.json": b"historical approvals\n",
        "/tmp/historical-T-0001-T-0002-evidence": b"unchanged historical fixture\n",
    }.items():
        path = upgrade.target(host, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o644 if name == upgrade.MARKER else 0o600)
    release = tmp_path / "release"
    for name in {transaction.SOURCE, transaction.MANIFEST}:
        dest = release / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    manifest = "".join(
        hashlib.sha256((release / n).read_bytes()).hexdigest() + "  " + n + "\n"
        for n in sorted({transaction.SOURCE, transaction.MANIFEST})
    ).encode()
    (release / "MANIFEST.sha256").write_bytes(manifest)
    pin = upgrade.digest(manifest)
    return host, release, pin, tmp_path / "backup"


def snapshot(host):
    return {
        str(p.relative_to(host)): (p.read_bytes(), p.stat().st_mode)
        for p in host.rglob("*")
        if p.is_file()
    }


def test_install_and_code_only_rollback_preserve_all_evidence_and_activation(fixture):
    host, release, pin, backup = fixture
    before = snapshot(host)
    assert transaction.install(release, pin, host, backup)["retry_authorized"] is False
    after = snapshot(host)
    changed = {n for n in before if before[n] != after[n]}
    assert changed == {n.lstrip("/") for n in transaction.DESTINATIONS}
    assert transaction.rollback(host, backup)["status"] == "ROLLED_BACK_HELD"
    assert snapshot(host) == before


@pytest.mark.parametrize("fail_after", [0, 1, 2])
def test_partial_failure_restores_all_code_without_touching_evidence(
    fixture, fail_after
):
    host, release, pin, backup = fixture
    before = snapshot(host)
    with pytest.raises(OSError, match="disposable fixture fault"):
        transaction.install(release, pin, host, backup, fail_after=fail_after)
    assert snapshot(host) == before
    assert (backup / "index.json").exists()


@pytest.mark.parametrize("condition", ["pin", "base", "pause", "other_developer_file"])
def test_preflight_fails_closed_before_backups_or_installation(fixture, condition):
    host, release, pin, backup = fixture
    if condition == "pin":
        pin = "0" * 64
    elif condition == "base":
        upgrade.target(host, next(iter(transaction.DESTINATIONS))).write_bytes(
            b"unexpected"
        )
    elif condition == "pause":
        upgrade.target(host, "/home/alfred/Alfred/gateway/PAUSE").unlink()
    else:
        upgrade.target(
            host, "/opt/alfred-developer-v1/developer_v1/router.py"
        ).write_bytes(b"unexpected")
    before = snapshot(host)
    with pytest.raises(ValueError):
        transaction.install(release, pin, host, backup)
    assert snapshot(host) == before and not backup.exists()


def test_runtime_inventory_changes_only_the_intake_source():
    old = transaction.inventory((ORIGINAL / transaction.MANIFEST).read_bytes())
    new = transaction.inventory((ROOT / transaction.MANIFEST).read_bytes())
    assert new == {
        **old,
        transaction.SOURCE: upgrade.digest((ROOT / transaction.SOURCE).read_bytes()),
    }
