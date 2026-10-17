from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil

import pytest

from task_a.release import ReleaseError, StagingTransaction, sha256
from task_a.promote import promote_lab_copy, promote_full_tracked_tree, rollback_lab_copy


def _marked(path: Path) -> Path:
    path.mkdir()
    (path / ".task-a-isolated-root").write_text("TASK_A_LAB_ONLY\n")
    return path


@pytest.fixture
def release_world(lab_root):
    target = _marked(lab_root / "target")
    payload = _marked(lab_root / "payload")
    (target / "etc/systemd/system").mkdir(parents=True)
    (target / "opt/alfred-hermes").mkdir(parents=True)
    (payload / "etc/systemd/system").mkdir(parents=True)
    (payload / "opt/alfred-hermes").mkdir(parents=True)
    old = target / "etc/systemd/system/alfred-hermes.service"
    old.write_bytes(b"old unit\n")
    old.chmod(0o644)
    new_unit = payload / "etc/systemd/system/alfred-hermes.service"
    new_unit.write_bytes(b"new unit\n")
    new_code = payload / "opt/alfred-hermes/version.txt"
    new_code.write_bytes(b"pinned\n")
    manifest = {"schema": "task-a-staging-release/1", "files": {
        "etc/systemd/system/alfred-hermes.service": {
            "payload_sha256": sha256(new_unit.read_bytes()), "baseline_sha256": sha256(old.read_bytes()),
            "mode": 0o644, "baseline_mode": 0o644},
        "opt/alfred-hermes/version.txt": {
            "payload_sha256": sha256(new_code.read_bytes()), "baseline_sha256": None,
            "mode": 0o640, "baseline_mode": None},
    }}
    return target, payload, manifest


def test_install_verify_rollback_preserves_previous_bytes_and_modes(release_world):
    target, payload, manifest = release_world
    transaction = StagingTransaction(target, payload, manifest)
    transaction.verify()
    record = transaction.install()
    assert (target / "etc/systemd/system/alfred-hermes.service").read_bytes() == b"new unit\n"
    assert (target / "opt/alfred-hermes/version.txt").read_bytes() == b"pinned\n"
    transaction.rollback(record)
    assert (target / "etc/systemd/system/alfred-hermes.service").read_bytes() == b"old unit\n"
    assert (target / "etc/systemd/system/alfred-hermes.service").stat().st_mode & 0o777 == 0o644
    assert not (target / "opt/alfred-hermes/version.txt").exists()
    assert json.loads((record / "state.json").read_text())["status"] == "rolled_back"
    assert (record / "backup/0.bak").read_bytes() == b"old unit\n"


@pytest.mark.parametrize("stage", ["after_transaction", "after_backup_file_0", "after_backup_file_1", "after_backup", "after_file_0", "after_file_1"])
def test_interrupted_install_requires_explicit_checksum_recovery(release_world, stage):
    target, payload, manifest = release_world
    installer = StagingTransaction(target, payload, manifest)
    with pytest.raises(RuntimeError):
        installer.install(fail_at=stage)
    record = next((target / ".task-a-transactions").iterdir())
    with pytest.raises(ReleaseError, match="interrupted"):
        installer.install()
    installer.recover(record)
    assert (target / "etc/systemd/system/alfred-hermes.service").read_bytes() == b"old unit\n"
    assert not (target / "opt/alfred-hermes/version.txt").exists()
    assert json.loads((record / "state.json").read_text())["status"] == "rolled_back"


def test_tampered_baseline_payload_backup_and_post_install_target_refused(release_world):
    target, payload, manifest = release_world
    installer = StagingTransaction(target, payload, manifest)
    unit = target / "etc/systemd/system/alfred-hermes.service"
    unit.write_bytes(b"unauthorized edit\n")
    with pytest.raises(ReleaseError, match="baseline"):
        installer.install()
    unit.write_bytes(b"old unit\n")
    source = payload / "opt/alfred-hermes/version.txt"
    source.write_bytes(b"payload tampered\n")
    with pytest.raises(ReleaseError, match="payload"):
        installer.install()
    source.write_bytes(b"pinned\n")
    record = installer.install()
    unit.write_bytes(b"post-install edit\n")
    with pytest.raises(ReleaseError, match="target changed"):
        installer.rollback(record)
    unit.write_bytes(b"new unit\n")
    (record / "backup/0.bak").write_bytes(b"tampered backup\n")
    with pytest.raises(ReleaseError, match="backup"):
        installer.rollback(record)


def test_rollback_refuses_parent_symlink_after_install(release_world):
    target, payload, manifest = release_world
    installer = StagingTransaction(target, payload, manifest)
    record = installer.install()
    moved = target / "etc/systemd/saved"
    (target / "etc/systemd/system").rename(moved)
    (target / "etc/systemd/system").symlink_to(moved, target_is_directory=True)
    with pytest.raises(ReleaseError, match="symlink"):
        installer.rollback(record)


def test_non_temp_or_unmarked_root_refused(tmp_path):
    from task_a.transport import isolated_root, TransportError
    with pytest.raises(TransportError):
        isolated_root(Path("/home/alfred"))
    with pytest.raises(TransportError):
        isolated_root(tmp_path)


def test_promote_pinned_clean_source_and_rollback(lab_root):
    repo = _marked(lab_root / "repo")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Staging Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "staging@example.invalid"], check=True)
    (repo / "gateway.py").write_bytes(b"trusted source v1\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    runtime = _marked(lab_root / "runtime")
    expected = {"gateway.py": sha256((repo / "gateway.py").read_bytes())}
    version = promote_lab_copy(repo, commit, expected, runtime)
    assert (runtime / "current/gateway.py").read_bytes() == b"trusted source v1\n"
    assert version.name == commit
    (repo / "gateway.py").write_bytes(b"unapproved edit\n")
    with pytest.raises(ReleaseError, match="clean-tree"):
        promote_lab_copy(repo, commit, expected, runtime)
    rollback_lab_copy(runtime)
    assert not (runtime / "current").exists()


def test_full_tracked_runtime_copy_has_exact_commit_manifest(lab_root):
    repo = _marked(lab_root / "full-source")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Staging Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "staging@example.invalid"], check=True)
    (repo / "runtime.py").write_text("# pinned\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    runtime = _marked(lab_root / "full-runtime")
    version = promote_full_tracked_tree(repo, commit, runtime)
    manifest = json.loads((version / "manifest.json").read_text())
    assert manifest["commit"] == commit
    assert set(manifest["files"]) == {".task-a-isolated-root", "runtime.py"}


def test_unit_and_permissions_templates_have_narrow_identity():
    base = Path(__file__).resolve().parents[1] / "templates"
    manifest = json.loads((base / "permissions/paths.json").read_text())
    assert manifest["identities"]["alfredhermes"]["supplementary_gids"] == [978]
    assert {i["uid"] for i in manifest["identities"].values()} == {31011, 31012, 31014}
    hermes = (base / "systemd/alfred-hermes.service").read_text()
    for line in ("User=alfredhermes", "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes",
                 "RestrictNamespaces=yes", "SupplementaryGroups=alfredevidencero", "BindReadOnlyPaths="):
        assert line in hermes
    broker = (base / "systemd/alfred-photon-intake.service").read_text()
    assert "User=alfredphoton" in broker and "UMask=0027" in broker
    gateway = (base / "systemd/alfred-dev-gateway-lab.service").read_text()
    assert "User=alfreddevlab" in gateway and "IPAddressDeny=any" in gateway
    for text in (hermes, broker, gateway):
        assert "User=alfred\n" not in text
        assert "User=root\n" not in text


def test_candidate_systemd_units_parse_in_disposable_root(lab_root):
    if not shutil.which("systemd-analyze"):
        pytest.skip("systemd-analyze unavailable")
    source = Path(__file__).resolve().parents[1] / "templates/systemd"
    directory = lab_root / "etc/systemd/system"
    directory.mkdir(parents=True)
    for unit in source.iterdir():
        shutil.copyfile(unit, directory / unit.name)
    for target in ("sysinit.target", "basic.target", "network-online.target", "multi-user.target", "sockets.target"):
        (directory / target).write_text("[Unit]\nDescription=Disposable parser fixture\n")
    for binary in (
        "opt/alfred-hermes/agent/.hermes/bin/hermes",
        "opt/alfred-photon-intake/venv/bin/python",
        "opt/alfred-dev-gateway-lab-venv/bin/python",
    ):
        path = lab_root / binary
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    command = ["systemd-analyze", f"--root={lab_root}", "verify"]
    command += [f"/etc/systemd/system/{unit.name}" for unit in source.iterdir()]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
