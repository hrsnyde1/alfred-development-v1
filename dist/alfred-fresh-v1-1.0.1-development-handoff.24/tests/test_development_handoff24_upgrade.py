"""handoff.24 (owner-confirmed completion delivery) installation/rollback, only on disposable /tmp fixture roots."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from development_handoff24 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
BASELINES = (
    "alfred-fresh-v1-1.0.1-development-handoff.23",
    "alfred-fresh-v1-1.0.1-development-handoff.22",
    "alfred-fresh-v1-1.0.1-development-handoff.21",
    "alfred-fresh-v1-1.0.1-development-handoff.11",
    "alfred-fresh-v1-1.0.1-development-handoff.10",
    "alfred-fresh-v1-1.0.1-development-handoff.9",
    "alfred-fresh-v1-1.0.1-development-handoff.8",
    "alfred-fresh-v1-1.0.1-development-handoff.7",
    "alfred-fresh-v1-1.0.1-development-handoff.5",
    "alfred-fresh-v1-1.0.1-development-handoff.4",
    "alfred-fresh-v1-1.0.1-development-handoff.2",
    "alfred-fresh-v1-1.0.1-T0003-recovery.1",
    "alfred-fresh-v1-1.0.1-planning-fix.1",
    "alfred-fresh-v1-1.0.1",
)
PRESERVED = (
    "/home/alfred/Alfred/gateway/PAUSE",
    "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0004/developer.failure.json",
    "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/development-challenge.attempt.json",
    "/var/lib/alfred-development-grants/grant-ref.json",
    "/etc/systemd/system/alfred-development-evidence.service",
)


# The source commit whose bytes are installed before handoff.8 (handoff.7 itself).
BASE_COMMIT = "f308811"
# Where each pinned installed file's bytes live in the source tree or a release payload.
SOURCES = {
    **transaction.DESTINATIONS,
    transaction.DEVELOPER + "publication_approval.py": "developer_v1/publication_approval.py",
    transaction.DEVELOPER + "real_worker.py": "developer_v1/real_worker.py",
    transaction.DEVELOPER + "team_skills.py": "developer_v1/team_skills.py",
    transaction.DEVELOPER + "router.py": "developer_v1/router.py",
    transaction.DEVELOPER + "gateway_adapter.py": "developer_v1/gateway_adapter.py",
    transaction.DEVELOPER + "schemas/publication-plan.schema.json":
        "developer_v1/schemas/publication-plan.schema.json",
    transaction.LIBRARY.replace("fresh_v1/", "v1_cto/") + "plan.schema.json": "v1_cto/plan.schema.json",
    transaction.LIBRARY.replace("fresh_v1/", "v1_cto/") + "cto.py": "v1_cto/cto.py",
    "/home/alfred/Git/alfred/.dev/bin/plan.schema.json": "v1_cto/plan.schema.json",
    "/home/alfred/Git/alfred/.dev/bin/cto.py": "v1_cto/cto.py",
    "/opt/alfred-draft-pr-publisher-v1/worker.py": "draft_pr_publisher/worker.py",
    "/usr/local/lib/alfred-completion-v1/completion_integration/completion.py":
        "completion_integration/completion.py",
    "/etc/alfred-development/delegation.json": "development_handoff12/delegation.json",
    "/etc/alfred-fresh-v1/policy.json": "development_handoff12/policy.json",
    "/etc/systemd/system/alfred-development-evidence.service.d/50-project-repos.conf":
        "development_handoff18/50-project-repos.conf",
    "/etc/systemd/system/alfred-development-evidence.service.d/60-claude-agents.conf":
        "development_handoff21/60-claude-agents.conf",
    transaction.DEVELOPER + "agent_profiles.py": "developer_v1/agent_profiles.py",
    transaction.DEVELOPER + "agent_profiles.json": "developer_v1/agent_profiles.json",
    transaction.LIBRARY + "handoffs.py": "fresh_v1/handoffs.py",
    transaction.COMPLETION + "delivery.py": "completion_integration/delivery.py",
    transaction.COMPLETION + "runtime.py": "completion_integration/runtime.py",
    transaction.DEVELOPER + "pipeline.py": "developer_v1/pipeline.py",
    transaction.DEVELOPER + "run_task.py": "developer_v1/run_task.py",
    transaction.DEVELOPER + "owner_grants.py": "developer_v1/owner_grants.py",
    transaction.DEVELOPER + "execution.py": "developer_v1/execution.py",
    transaction.INTAKE: "developer_v1/trusted_intake_development.py",
    transaction.DEVELOPER + "trusted_intake_development.py": "developer_v1/trusted_intake_development.py",
    transaction.QA + "worker.py": "independent_qa/worker.py",
    transaction.QA + "config.json": "independent_qa/config.json",
}


def original(name, expected):
    relative = (
        "fresh_v1/systemd/alfred-development-evidence.conf"
        if name == transaction.DROP_IN
        else SOURCES.get(name, "fresh_v1/" + Path(name).name)
    )
    for release in BASELINES:
        p = ROOT / "dist" / release / relative
        if p.is_file() and upgrade.digest(p.read_bytes()) == expected:
            return p.read_bytes()
    raw = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{relative}"],
                         capture_output=True, check=False).stdout
    if upgrade.digest(raw) == expected:
        return raw
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
        if name in transaction.SEMANTIC:
            # Root-only and unreadable to staging: its content is what is pinned.
            raw = (ROOT / transaction.SEMANTIC[name]).read_bytes()
            write(upgrade.target(root, name), raw.replace(b"\n", b"\r\n"), mode=0o600)
        else:
            write(upgrade.target(root, name), original(name, sha))
    for name in transaction.DESTINATIONS.values():
        write(release / name, (ROOT / name).read_bytes())
    raw = "".join(
        hashlib.sha256((release / n).read_bytes()).hexdigest() + "  " + n + "\n"
        for n in sorted(set(transaction.DESTINATIONS.values()))
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


def installed(root):
    return {
        name: upgrade.digest(upgrade.target(root, name).read_bytes())
        for name in transaction.DESTINATIONS
    }


def test_install_replaces_only_its_files_and_preserves_everything_else(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD" and result["retry_authorized"] is False
    after = snapshot(root)
    changed = {k for k in after if before.get(k) != after[k]}
    assert changed == {name.lstrip("/") for name in transaction.DESTINATIONS}
    assert installed(root) == {
        name: upgrade.digest((ROOT / source).read_bytes())
        for name, source in transaction.DESTINATIONS.items()
    }
    drop_in = upgrade.target(root, transaction.DROP_IN).read_text()
    assert "ReadWritePaths=/var/lib/alfred-development-grants" in drop_in
    assert (
        "BindReadOnlyPaths=/home/alfred/Alfred/gateway:/run/alfred-fresh-v1-gateway"
        in drop_in.splitlines()
    )
    for name in transaction.DESTINATIONS:
        assert after[name.lstrip("/")][1] == before[name.lstrip("/")][1]
    index = json.loads((backup / "index.json").read_bytes())
    assert index["schema"] == transaction.BACKUP_SCHEMA
    recorded = {e["path"]: e["sha256"] for e in index["files"]}
    assert list(recorded) == list(transaction.BASE)
    for name, sha in transaction.BASE.items():
        # A content-pinned file records the exact bytes it had before install.
        assert recorded[name] == (sha or upgrade.digest(before[name.lstrip("/")][0]))


def test_rollback_restores_the_handoff23_baseline(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    transaction.install(release, pin, root, backup)
    assert transaction.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    assert snapshot(root) == before


def test_fault_mid_install_rolls_back(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    with pytest.raises(OSError):
        transaction.install(release, pin, root, backup, fail_after=0)
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
        transaction.LIBRARY + "role.py",
        transaction.DROP_IN,
        transaction.LIBRARY + "host.py",
        transaction.LIBRARY + "qa_recovery.py",
        transaction.DEVELOPER + "owner_grants.py",
        transaction.DEVELOPER + "pipeline.py",
        transaction.QA + "worker.py",
        transaction.COMPLETION + "runtime.py",
        transaction.COMPLETION + "delivery.py",
        transaction.COMPLETION + "completion.py",
        "/usr/local/sbin/alfred-dev-ops",
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


def test_wrong_manifest_pin_refuses(fixture):
    root, release, _, backup = fixture
    before = snapshot(root)
    with pytest.raises(ValueError, match="manifest pin"):
        transaction.install(release, "0" * 64, root, backup)
    assert snapshot(root) == before


def test_existing_backup_refuses_and_second_install_is_impossible(fixture):
    root, release, pin, backup = fixture
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



def test_gateway_owned_files_are_not_pinned():
    # handoff.15 checked the Gateway's own files as root-owned and refused on the host.
    from development_handoff16 import install_patch as team_skills

    pinned = set(transaction.BASE) | set(transaction.DEPENDENCIES)
    assert not any(name.startswith(team_skills.GATEWAY_BIN) for name in pinned)
