"""Pinned inventory, isolated installation/rollback, and existing-unit contracts."""

import json
import os
import shutil
import socket
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from fresh_v1 import host, release, upgrade

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def candidate(tmp_path):
    result = release.build(ROOT, tmp_path / "candidate")
    directory = Path(result["archive"]).parent / ("alfred-fresh-v1-" + release.VERSION)
    return directory, result


def fake_host(tmp_path, candidate):
    directory, _result = candidate
    root = tmp_path / "host"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    contract = json.loads((directory / "host-contract.json").read_bytes())
    for name in contract["installed_sha256"]:
        path = root / name.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(name, path)
    installed = Path("/opt/alfred-developer-v1")
    for line in (installed / "developer_v1/release.sha256").read_text().splitlines():
        _, name = line.split("  ", 1)
        path = root / "opt/alfred-developer-v1" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(installed / name, path)
    marker = root / upgrade.MARKER.lstrip("/")
    marker.write_bytes(b"existing activation\n")
    marker.chmod(0o644)
    config = root / upgrade.INTAKE_CONFIG.lstrip("/")
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        '{"sidecar_token":"mock-only", "owner_sender_id":"mock-owner", "existing":42}\n'
    )
    config.chmod(0o600)
    (config.parent / "PAUSE").touch(mode=0o600)
    preserved = []
    for name in (
        "var/lib/alfred-development-grants/grant-old.json",
        "var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-result.json",
        "var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-plan.json",
        "var/lib/alfred-draft-pr-authorizations/T-0002.json",
        "var/lib/alfred-draft-pr-private/github-token",
        "var/lib/alfred-qa-state/dev-v1-accept/T-0002/qa-report.json",
        "var/lib/alfred-reviewer-state/dev-v1-accept/T-0002/review-report.json",
        "home/alfred/Alfred/completion-delivery/delivery.json",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PRESERVE ORIGINAL " + name.encode())
        preserved.append(path)
    return root, preserved


def files(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode & 0o777)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_release_pinned_inventory_and_repeatable_archive(candidate, tmp_path):
    directory, result = candidate
    inventory = upgrade.verify(directory, result["manifest_sha256"])
    assert len(inventory) == result["files"]
    again = release.build(ROOT, tmp_path / "again")
    assert again["sha256"] == result["sha256"]
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(result["archive"]) as archive:
        archive.extractall(extracted, filter="data")
    upgrade.verify(extracted / directory.name, result["manifest_sha256"])
    (directory / "unlisted.txt").write_text("unexpected")
    with pytest.raises(ValueError):
        upgrade.verify(directory, result["manifest_sha256"])


def test_digest_and_manifest_tamper_are_rejected(candidate):
    directory, result = candidate
    with pytest.raises(ValueError):
        upgrade.verify(directory, "0" * 64)
    (directory / "fresh_v1/host.py").write_text("tampered")
    with pytest.raises(ValueError):
        upgrade.verify(directory, result["manifest_sha256"])


def test_install_rollback_preserve_marker_and_all_historical_evidence(
    candidate, tmp_path
):
    root, preserved = fake_host(tmp_path, candidate)
    before = files(root)
    directory, result = candidate
    backup = tmp_path / "backup"
    assert (
        upgrade.install(directory, result["manifest_sha256"], root, backup)["status"]
        == "INSTALLED_DISABLED"
    )
    assert (
        json.loads((root / upgrade.POLICY.lstrip("/")).read_bytes())["enabled"] is False
    )
    assert (root / upgrade.MARKER.lstrip("/")).read_bytes() == b"existing activation\n"
    assert all(p.read_bytes() == before[str(p.relative_to(root))][0] for p in preserved)
    assert upgrade.rollback(root, backup)["status"] == "ROLLED_BACK"
    assert files(root) == before
    assert (
        json.loads((root / upgrade.INTAKE_CONFIG.lstrip("/")).read_bytes())["existing"]
        == 42
    )


@pytest.mark.parametrize("failed_entry", [0, 5, 15, -1])
def test_partial_failure_automatically_restores_code_without_moving_marker(
    candidate, tmp_path, failed_entry
):
    root, _ = fake_host(tmp_path, candidate)
    before = files(root)
    directory, result = candidate
    if failed_entry == -1:
        failed_entry = len(
            upgrade.mapping(directory)
        )  # + private Intake config, zero-indexed
    with pytest.raises(OSError):
        upgrade.install(
            directory,
            result["manifest_sha256"],
            root,
            tmp_path / "backup",
            fail_after=failed_entry,
        )
    assert files(root) == before


def test_interrupted_recovery_can_be_repeated_without_touching_evidence(
    candidate, tmp_path
):
    root, _ = fake_host(tmp_path, candidate)
    before = files(root)
    directory, result = candidate
    backup = tmp_path / "backup"
    with (
        patch.object(
            upgrade, "rollback", side_effect=OSError("simulated failed recovery")
        ),
        pytest.raises(OSError),
    ):
        upgrade.install(
            directory, result["manifest_sha256"], root, backup, fail_after=10
        )
    assert (root / upgrade.MARKER.lstrip("/")).read_bytes() == b"existing activation\n"
    upgrade.rollback(root, backup)
    assert files(root) == before
    upgrade.rollback(root, backup)  # Idempotent explicit recovery, no worker execution.
    assert files(root) == before


def test_installed_contract_mismatch_does_not_begin_mutation(candidate, tmp_path):
    root, _ = fake_host(tmp_path, candidate)
    (root / "usr/local/lib/alfred-v1.1/trusted_intake.py").write_text("unexpected")
    before = files(root)
    directory, result = candidate
    backup = tmp_path / "backup"
    with pytest.raises(ValueError):
        upgrade.install(directory, result["manifest_sha256"], root, backup)
    assert files(root) == before and not backup.exists()


def test_no_new_units_or_service_actions_in_file_transaction(candidate):
    directory, _ = candidate
    targets = upgrade.mapping(directory)
    units = {p for p in targets if p.startswith("/etc/systemd/")}
    assert units == {
        f"/etc/systemd/system/alfred-development-{name}.service.d/40-fresh-v1.conf"
        for name in ("intake", "gateway", "evidence")
    }
    assert not any(".timer" in name or name.endswith(".service") for name in targets)
    assert (
        b"--prepare-only"
        in targets[
            "/etc/systemd/system/alfred-development-gateway.service.d/40-fresh-v1.conf"
        ]
    )
    source = (ROOT / "fresh_v1/upgrade.py").read_text()
    assert "subprocess" not in source and "systemctl" not in source
    assert not any(
        "T-0002" in name or "github-token" in name or "delivery.json" in name
        for name in targets
    )


def test_worker_dispatch_clears_environment_and_selects_existing_uid():
    adapter = host.Host({"jobs": "/var/lib/alfred-v1-handoffs"})
    calls = []

    def capture(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"stdout": b'{"decision":"PASS"}\n'})()

    with patch.object(host, "command", capture), patch.object(adapter, "guard"):
        assert (
            adapter.worker(
                {"project": "dev-v1-accept", "task_id": "T-0038"}, "qa", "alfredqa"
            )["decision"]
            == "PASS"
        )
    args = calls[0]
    assert args[:4] == ["/usr/sbin/runuser", "-u", "alfredqa", "--"]
    assert "-i" in args and "--ambient-caps=-all" in args and "--inh-caps=-all" in args
    assert "/usr/bin/python3" in args and "-I" in args


def test_poll_refuses_unprivileged_caller():
    if os.geteuid() != 0:
        with pytest.raises(PermissionError):
            host.poll(Path("/does/not/exist"))


def test_socket_inherits_exact_root_acl_without_broadening_service_capabilities(
    tmp_path,
):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o710)
    subprocess.run(
        ["/usr/bin/setfacl", "-d", "-m", "u:root:rw-", str(runtime)], check=True
    )
    path = runtime / "intake.sock"
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        path.chmod(0o660)
        acl = subprocess.check_output(["/usr/bin/getfacl", "-cp", str(path)]).decode()
    assert "user:root:rw-" in acl
    intake = (ROOT / "fresh_v1/systemd/alfred-development-intake.conf").read_text()
    assert "u:root:rw-" in intake
    evidence = (ROOT / "fresh_v1/systemd/alfred-development-evidence.conf").read_text()
    assert (
        "CapabilityBoundingSet" not in evidence
        and "SupplementaryGroups" not in evidence
    )
