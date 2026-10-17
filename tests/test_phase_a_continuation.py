"""Phase A operator aid: all writes and service observations use disposable fixtures."""

import json
import os
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_development_handoff_upgrade import original, write

from development_challenge import phase_a_continue as preparation

LAB = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(preparation, "ROOT", tmp_path)
    monkeypatch.setattr(
        preparation.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.geteuid())
    )
    target = preparation.host
    archive = LAB / "dist" / (preparation.NAME + ".tar.gz")
    write(target("/root/" + archive.name), archive.read_bytes(), 0o600)
    review = target(preparation.REVIEW)
    review.mkdir(mode=0o700)
    with tarfile.open(archive) as package:
        for member in package.getmembers():
            assert member.isfile() and ".." not in Path(member.name).parts
            write(review / member.name, package.extractfile(member).read())
    write(
        target("/root/alfred-fresh-v1-phase-a-prepare.sh"),
        (LAB / "development_challenge/PHASE_A_PREPARE.sh").read_bytes(),
        0o600,
    )
    release = review / preparation.NAME
    pins = json.loads(
        (release / "development_challenge/installed-sha256.json").read_bytes()
    )
    for name, sha in pins.items():
        write(target(name), original(name, sha))
    developer = "/opt/alfred-developer-v1/"
    for line in (
        target(developer + "developer_v1/release.sha256").read_text().splitlines()
    ):
        sha, name = line.split("  ", 1)
        write(target(developer + name), original(developer + name, sha))
    # Only these three readable, already pinned files are copied from the host.
    context = Path(preparation.TASK + "/context.json").read_bytes()
    ctx = json.loads(context)
    write(target(preparation.TASK + "/context.json"), context)
    for name in (preparation.PLAN, ctx["spec_path"]):
        write(target(name), Path(name).read_bytes(), 0o600)
    # All private attempts, approvals, policy and tokens below are mock bytes.
    for name, stage, mtime in (
        ("plan.attempt.json", "plan", 1792181749323796085),
        (
            "development-challenge.attempt.json",
            "development-challenge",
            1792187986367039147,
        ),
    ):
        p = target(preparation.TASK + "/" + name)
        raw = (
            json.dumps(
                {"stage": stage, "status": "uncertain_until_result"},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        write(p, raw.encode(), 0o600)
        os.utime(p, ns=(mtime, mtime))
    write(target(preparation.TASK + "/plan-recovery-1.result.json"), context, 0o600)
    grants = target(preparation.GRANTS)
    grants.mkdir(mode=0o700)
    for name, task in (
        ("grant-history.json", "T-0002"),
        ("request-route-fixture.json", "T-0003"),
    ):
        write(
            grants / name,
            json.dumps({"project": "dev-v1-accept", "task_id": task}).encode(),
            0o600,
        )
    for project, task in (("dev-001", "T-0001"), ("dev-v1-accept", "T-0002")):
        write(
            target(f"/var/lib/alfred-v1-handoffs/{project}/{task}/history.json"),
            b"historical fixture\n",
            0o600,
        )
    write(target(developer + "active"), b"ACTIVE FIXTURE\n")
    write(
        target("/etc/alfred-fresh-v1/policy.json"),
        json.dumps(
            {
                "enabled": True,
                "project": "dev-v1-accept",
                "destination": "hrsnyde1/alfred-dev-v1-acceptance",
            }
        ).encode(),
        0o600,
    )
    write(
        target("/home/alfred/Alfred/gateway/v1-1-intake.json"),
        b'{"fixture":true}\n',
        0o600,
    )
    write(target("/home/alfred/Alfred/gateway/PAUSE"), b"", 0o664)
    for p in tmp_path.rglob("*"):
        if p.is_dir():
            p.chmod(p.stat().st_mode & ~0o022)

    def show(args, **kwargs):
        assert args[:2] == ["systemctl", "show"]
        assert args[2:8] == list(preparation.UNITS)
        assert kwargs == {
            "check": True,
            "capture_output": True,
            "text": True,
            "timeout": 15,
        }
        output = "\n\n".join(
            f"Id={unit}\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0"
            for unit in preparation.UNITS
        )
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(preparation.subprocess, "run", show)
    return tmp_path


def snapshot(root):
    return {
        str(p.relative_to(root)): (
            p.read_bytes(),
            p.stat().st_mode,
            p.stat().st_mtime_ns,
            p.stat().st_ino,
        )
        for p in root.rglob("*")
        if p.is_file()
    }


def test_complete_then_resume_preserves_every_existing_byte_and_metadata(fixture):
    before = snapshot(fixture)
    baseline = preparation.host(preparation.REVIEW + "/preserved.sha256")
    result = preparation.continue_phase_a()
    assert result == {
        "status": "PHASE_A_PREPARED_HELD",
        "preservation": "created",
        "installation": "not_executed",
        "service_actions": "none",
        "T0003": "held",
    }
    after = snapshot(fixture)
    assert {key: after[key] for key in before} == before
    assert set(after) - set(before) == {str(baseline.relative_to(fixture))}
    assert baseline.stat().st_mode & 0o777 == 0o600
    for line in baseline.read_text().splitlines():
        sha, name = line.split("  ", 1)
        assert preparation.digest(preparation.host(name).read_bytes()) == sha
    assert len(baseline.read_text().splitlines()) == 13
    assert preparation.continue_phase_a()["preservation"] == "existing_verified"
    assert snapshot(fixture) == after


@pytest.mark.parametrize(
    "name",
    [
        "/root/alfred-fresh-v1-phase-a-prepare.sh",
        "/root/" + preparation.NAME + ".tar.gz",
        preparation.REVIEW + "/" + preparation.NAME + "/MANIFEST.sha256",
        preparation.REVIEW
        + "/"
        + preparation.NAME
        + "/development_challenge/install_patch.py",
        "/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py",
        "/opt/alfred-developer-v1/developer_v1/router.py",
        preparation.TASK + "/context.json",
        preparation.TASK + "/development-challenge.attempt.json",
        preparation.PLAN,
    ],
)
def test_any_pinned_drift_stops_without_writes(fixture, name):
    preparation.host(name).write_bytes(b"drift fixture\n")
    before = snapshot(fixture)
    with pytest.raises(preparation.Blocked):
        preparation.continue_phase_a()
    assert snapshot(fixture) == before


@pytest.mark.parametrize(
    "bad",
    [
        "pause",
        "pending",
        "publication_pending",
        "approval",
        "result",
        "backup",
        "inventory",
        "policy",
        "review_mode",
        "root_ownership",
        "symlink",
        "attempt_metadata",
    ],
)
def test_preflight_rejects_unsafe_state_without_writes(fixture, monkeypatch, bad):
    target = preparation.host
    if bad == "pause":
        target("/home/alfred/Alfred/gateway/PAUSE").unlink()
    elif bad in ("pending", "publication_pending", "approval"):
        name = {
            "pending": "pending-fixture.json",
            "publication_pending": "publication-pending-fixture.json",
            "approval": "decision-fixture.json",
        }[bad]
        write(
            target(preparation.GRANTS + "/" + name),
            b'{"project":"dev-v1-accept","task_id":"T-0003"}',
            0o600,
        )
    elif bad == "result":
        write(
            target(preparation.TASK + "/development-challenge.result.json"),
            b"{}",
            0o600,
        )
    elif bad == "backup":
        target("/root/alfred-fresh-v1-development-handoff-1-backup").mkdir()
    elif bad == "inventory":
        write(
            target(preparation.REVIEW + "/" + preparation.NAME + "/extra"),
            b"unexpected fixture",
        )
    elif bad == "policy":
        target("/etc/alfred-fresh-v1/policy.json").chmod(0o644)
    elif bad == "review_mode":
        target(preparation.REVIEW).chmod(0o755)
    elif bad == "root_ownership":
        monkeypatch.setattr(preparation.os, "geteuid", lambda: 123456)
    elif bad == "attempt_metadata":
        os.utime(target(preparation.TASK + "/plan.attempt.json"), ns=(1, 1))
    else:
        p = target(preparation.REVIEW + "/" + preparation.NAME + "/MANIFEST.sha256")
        p.rename(p.with_suffix(".moved"))
        p.symlink_to(p.with_suffix(".moved"))
    before = snapshot(fixture)
    with pytest.raises((preparation.Blocked, OSError)):
        preparation.continue_phase_a()
    assert snapshot(fixture) == before


def test_active_worker_reports_exact_unit_without_writes(fixture, monkeypatch):
    show = preparation.subprocess.run

    def active(args, **kwargs):
        result = show(args, **kwargs)
        result.stdout = result.stdout.replace(
            "ActiveState=inactive", "ActiveState=active", 1
        )
        return result

    monkeypatch.setattr(preparation.subprocess, "run", active)
    before = snapshot(fixture)
    with pytest.raises(
        preparation.Blocked, match="worker_not_idle: alfred-development-gateway.service"
    ):
        preparation.continue_phase_a()
    assert snapshot(fixture) == before


def test_conflicting_existing_baseline_is_never_rewritten(fixture):
    write(
        preparation.host(preparation.REVIEW + "/preserved.sha256"),
        b"original conflicting fixture\n",
        0o600,
    )
    before = snapshot(fixture)
    with pytest.raises(
        preparation.Blocked, match="existing_preservation_baseline_differs"
    ):
        preparation.continue_phase_a()
    assert snapshot(fixture) == before


def test_interruption_before_publication_leaves_no_partial_baseline(
    fixture, monkeypatch
):
    # An unrelated old temporary must never be cleaned up by the continuation.
    old = preparation.host(preparation.REVIEW + "/.preserved-old.tmp")
    write(old, b"prior interrupted fixture", 0o600)
    before = snapshot(fixture)

    def interrupted(_):
        raise OSError("isolated fsync interruption")

    monkeypatch.setattr(preparation.os, "fsync", interrupted)
    with pytest.raises(OSError):
        preparation.continue_phase_a()
    assert snapshot(fixture) == before


def test_interruption_after_atomic_publication_can_resume_without_rewriting(
    fixture, monkeypatch
):
    inspect = preparation.inspect
    count = 0

    def interrupted():
        nonlocal count
        count += 1
        if count == 3:
            raise OSError("isolated post-publication interruption")
        return inspect()

    monkeypatch.setattr(preparation, "inspect", interrupted)
    with pytest.raises(OSError):
        preparation.continue_phase_a()
    before = snapshot(fixture)
    monkeypatch.setattr(preparation, "inspect", inspect)
    assert preparation.continue_phase_a()["preservation"] == "existing_verified"
    assert snapshot(fixture) == before


def test_changing_evidence_blocks_before_first_write(fixture, monkeypatch):
    inspect = preparation.inspect
    count = 0

    def unstable():
        nonlocal count
        count += 1
        return inspect() + (b"changed" if count == 2 else b"")

    monkeypatch.setattr(preparation, "inspect", unstable)
    before = snapshot(fixture)
    with pytest.raises(preparation.Blocked, match="evidence_changed_during_preflight"):
        preparation.continue_phase_a()
    assert snapshot(fixture) == before


def test_atomic_publication_never_replaces_concurrent_baseline(fixture, monkeypatch):
    baseline = preparation.host(preparation.REVIEW + "/preserved.sha256")
    loader = preparation.ctypes.CDLL

    def race(*args, **kwargs):
        write(baseline, b"concurrent original fixture", 0o600)
        return loader(*args, **kwargs)

    monkeypatch.setattr(preparation.ctypes, "CDLL", race)
    with pytest.raises(FileExistsError):
        preparation.continue_phase_a()
    assert baseline.read_bytes() == b"concurrent original fixture"


def test_missing_file_diagnostic_includes_checkpoint_not_private_content(fixture):
    with pytest.raises(
        preparation.Blocked, match=r"read_failed: .*missing: FileNotFoundError: errno=2"
    ):
        preparation.read(fixture / "missing")


@pytest.mark.parametrize(
    "uid,args,reason",
    [
        (1000, ["--operator-quiescence-confirmed"], "root_operator_required"),
        (0, [], "operator_messaging_quiescence_required"),
    ],
)
def test_cli_requires_root_and_independent_quiescence_confirmation(
    fixture, monkeypatch, uid, args, reason
):
    monkeypatch.setattr(preparation.os, "geteuid", lambda: uid)
    monkeypatch.setattr(preparation.sys, "argv", ["phase_a_continue.py", *args])
    before = snapshot(fixture)
    with pytest.raises(preparation.Blocked, match=reason):
        preparation.main()
    assert snapshot(fixture) == before
