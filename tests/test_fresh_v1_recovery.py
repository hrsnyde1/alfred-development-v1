"""Exact incident recovery on disposable tasks, real handoffs, mocked external IO."""

import json
import os
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from alfred.gateway.journal import Journal

import fresh_v1_recovery_patch as transaction
from fresh_v1 import recovery
from fresh_v1.handoffs import Held, write_once
from v1_cto import cto

ROOT = Path(__file__).resolve().parents[1]
pytest_plugins = ["tests.test_fresh_v1"]


@pytest.fixture
def incident(world):
    assert world.submit() == "T-0003"
    rows = [
        r
        for r in Journal(world.gateway.gateway_dir / "journal.jsonl").entries()
        if r.get("kind") == "outcome" and r.get("outcome") == "filed"
    ]
    repo, spec, name, raw = cto._task_for(rows[-1], world.registry)
    plan = cto._central_cto(
        spec, repo, cto._repo_evidence(repo, name), recovery.digest(raw)
    )
    plan_path = world.gateway.gateway_dir / "cto-plans/dev-v1-accept-T-0003.json"
    cto._atomic(plan_path, plan)
    root = world.jobdir(world.job)
    write_once(
        root / "plan.attempt.json",
        {"stage": "plan", "status": "uncertain_until_result"},
    )
    (world.gateway.gateway_dir / "PAUSE").touch(mode=0o600)
    library = world.root / "recovery-code"
    library.mkdir(mode=0o700)
    for name in recovery.RUNTIME:
        shutil.copyfile(ROOT / "fresh_v1" / name, library / name)
        (library / name).chmod(0o600)
    evidence = recovery.Evidence(
        world.policy_path,
        root,
        uid=os.geteuid(),
        trusted_root=world.root,
        alfred_uid=os.geteuid(),
        library=library,
    )
    yield world, evidence, plan_path


def approve_operator(incident, now=None):
    world, evidence, _ = incident
    report, _ = evidence.before()
    recovery.authorize(
        evidence,
        recovery.digest(recovery.canonical(report)),
        "fixture-operator-decision",
        now=now,
    )
    world.verify_plan_recovery = lambda job: (world.guard(), evidence.verify())[1]


def test_read_only_inspection_and_append_only_preparation_do_not_dispatch(incident):
    world, evidence, plan_path = incident
    root = evidence.directory
    before = {
        p: p.read_bytes()
        for p in (root / "job.json", root / "plan.attempt.json", plan_path)
    }
    assert evidence.before()[0] == evidence.before()[0]
    assert {p: p.read_bytes() for p in root.iterdir()} == {
        p: raw for p, raw in before.items() if p.parent == root
    }
    approve_operator(incident)
    assert {p.name for p in root.iterdir()} == {
        "job.json",
        "plan.attempt.json",
        recovery.COPY,
        recovery.DECISION,
    }
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert (root / recovery.COPY).read_bytes() == before[plan_path]
    assert not world.calls and len(world.messages) == 1  # request confirmation only
    with pytest.raises(Held, match="already exists"):
        recovery.authorize(evidence, "0" * 64, "fixture-second-decision")


def test_recovery_rejoins_full_automatic_pipeline_with_two_native_approvals(incident):
    world, evidence, plan_path = incident
    root = evidence.directory
    original_attempt = (root / "plan.attempt.json").read_bytes()
    original_plan = plan_path.read_bytes()
    approve_operator(incident)
    assert world.tick()["state"] == "held"  # PAUSE still wins
    assert not world.calls
    (world.gateway.gateway_dir / "PAUSE").unlink()  # disposable fixture only
    assert world.tick() == {"state": "awaiting_development_approval"}
    assert world.calls == [("plan", "alfred")]
    assert (root / recovery.RESULT).exists() and not (
        root / "plan.result.json"
    ).exists()
    assert (
        (root / recovery.COPY).read_bytes() == original_plan != plan_path.read_bytes()
    )
    assert (root / "plan.attempt.json").read_bytes() == original_attempt
    assert not list(world.grants.glob("grant-*.json"))
    world.approve_development()
    assert world.tick() == {"state": "awaiting_publication_approval"}
    assert not world.pushes and not world.notifications
    world.approve_publication()
    assert world.tick()["state"] == "complete"
    assert world.calls.count(("plan", "alfred")) == 1
    assert len(world.pushes) == len(world.notifications) == 1
    assert (root / "plan.attempt.json").read_bytes() == original_attempt
    assert (root / recovery.COPY).read_bytes() == original_plan
    for old in ("T-0001", "T-0002"):
        assert (
            world.repo / ".dev/tasks" / (old + "-historical.md")
        ).read_text() == "preserve " + old


def test_new_uncertain_attempt_is_never_retried_after_restart(incident):
    world, evidence, _ = incident
    approve_operator(incident)
    (world.gateway.gateway_dir / "PAUSE").unlink()
    with patch.object(world, "plan", side_effect=TimeoutError("ambiguous")) as plan:
        assert world.tick()["state"] == "held"
        assert world.tick()["state"] == "held"
        assert plan.call_count == 1
    fresh_reader = recovery.Evidence(
        evidence.policy_path,
        evidence.directory,
        uid=evidence.uid,
        trusted_root=evidence.trusted_root,
        alfred_uid=evidence.alfred_uid,
        library=evidence.library,
    )
    world.verify_plan_recovery = lambda job: fresh_reader.verify()
    with patch.object(world, "plan") as plan:
        assert "requires reconciliation" in world.tick()["reason"]
    plan.assert_not_called()
    assert not (evidence.directory / recovery.RESULT).exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "context",
        "original_result",
        "worker_input",
        "failure",
        "nested_challenge",
        "old_attempt",
        "delivered",
        "baseline",
        "spec",
        "policy_mode",
        "wrong_task",
    ],
)
def test_original_state_must_prove_before_plan_failure(incident, mutation):
    world, evidence, plan_path = incident
    if mutation in ("context", "original_result", "worker_input", "failure"):
        names = {
            "context": "context.json",
            "original_result": "plan.result.json",
            "worker_input": "worker-policy.json",
            "failure": "plan.failure.json",
        }
        write_once(evidence.directory / names[mutation], {})
    elif mutation == "nested_challenge":
        write_once(
            world.grants / "challenge-conflict.json",
            {
                "schema": "alfred.development-challenge/1",
                "request": {"project": "dev-v1-accept", "task_id": "T-0003"},
            },
        )
    elif mutation == "old_attempt":
        (evidence.directory / "plan.attempt.json").write_text('{"stage":"developer"}')
    elif mutation in ("delivered", "baseline"):
        plan = json.loads(plan_path.read_bytes())
        if mutation == "delivered":
            plan["delivery"]["state"] = "sent"
        else:
            plan["baseline_revision"] = "a" * 40
        cto._atomic(plan_path, plan)
    elif mutation == "spec":
        next((world.repo / ".dev/tasks").glob("T-0003-*.md")).write_text("changed")
    elif mutation == "policy_mode":
        world.policy_path.chmod(0o640)
    else:
        job = json.loads((evidence.directory / "job.json").read_bytes())
        job["task_id"] = "T-0002"
        (evidence.directory / "job.json").write_text(json.dumps(job))
    with pytest.raises((Held, ValueError)):
        evidence.before()
    assert not (evidence.directory / recovery.DECISION).exists() and not world.calls


@pytest.mark.parametrize(
    "mutation",
    [
        "job",
        "registry",
        "runtime",
        "copy",
        "decision_mode",
        "decision_symlink",
        "expiry",
        "future",
        "approval_later",
    ],
)
def test_stale_or_untrusted_recovery_decision_fails_closed(incident, mutation):
    world, evidence, _ = incident
    approve_operator(incident)
    if mutation == "job":
        p = evidence.directory / "job.json"
        v = json.loads(p.read_bytes())
        v["space_id"] = "changed"
        p.write_text(json.dumps(v))
    elif mutation == "registry":
        Path(world.p["registry"]).write_text("changed")
    elif mutation == "runtime":
        (evidence.library / "host.py").write_text("changed")
    elif mutation == "copy":
        (evidence.directory / recovery.COPY).write_text("{}")
    elif mutation == "decision_mode":
        (evidence.directory / recovery.DECISION).chmod(0o666)
    elif mutation == "decision_symlink":
        p = evidence.directory / recovery.DECISION
        raw = p.read_bytes()
        p.unlink()
        target = world.root / "untrusted.json"
        target.write_bytes(raw)
        p.symlink_to(target)
    elif mutation == "approval_later":
        write_once(
            world.grants / "grant-conflict.json",
            {"project": "dev-v1-accept", "task_id": "T-0003"},
        )
    (world.gateway.gateway_dir / "PAUSE").unlink()
    if mutation in ("expiry", "future"):
        record = json.loads((evidence.directory / recovery.DECISION).read_bytes())
        clock = (
            record["expires_at"] + 1
            if mutation == "expiry"
            else record["created_at"] - 1
        )
        with pytest.raises(Held):
            evidence.verify(now=clock)
    else:
        with pytest.raises((Held, ValueError, OSError)):
            evidence.verify()
    assert not (evidence.directory / recovery.ATTEMPT).exists() and not world.calls


def test_partial_preparation_without_decision_cannot_authorize_and_can_resume(incident):
    world, evidence, _ = incident
    with (
        patch.object(recovery, "write_once", side_effect=OSError("interrupted")),
        pytest.raises(OSError),
    ):
        approve_operator(incident)
    assert (evidence.directory / recovery.COPY).exists() and not (
        evidence.directory / recovery.DECISION
    ).exists()
    (world.gateway.gateway_dir / "PAUSE").unlink()
    assert "requires reconciliation" in world.tick()["reason"] and not world.calls
    (world.gateway.gateway_dir / "PAUSE").touch()
    approve_operator(incident)


def test_unprivileged_operator_cli_is_refused():
    with (
        patch.object(recovery.os, "geteuid", return_value=1000),
        pytest.raises(PermissionError),
    ):
        recovery.main()


def test_expiry_does_not_invalidate_a_completed_single_attempt(incident):
    world, evidence, _ = incident
    approve_operator(incident)
    (world.gateway.gateway_dir / "PAUSE").unlink()
    assert world.tick()["state"] == "awaiting_development_approval"
    assert evidence.verify(now=time.time() + 7200) is True


@pytest.mark.parametrize("target", ["context.json", recovery.RESULT])
def test_completed_recovery_rejects_conflicting_result_evidence(incident, target):
    world, evidence, _ = incident
    approve_operator(incident)
    (world.gateway.gateway_dir / "PAUSE").unlink()
    assert world.tick()["state"] == "awaiting_development_approval"
    (evidence.directory / target).write_text("{}")
    with pytest.raises(Held):
        evidence.verify()


@pytest.fixture
def installation(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name in transaction.BASE:
        dest = root / (transaction.PREFIX + name).lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        # The live host may already have this extension; model its pinned
        # pre-upgrade contract from staged releases, never installed files.
        source = ROOT / "dist/alfred-fresh-v1-1.0.1-planning-fix.1/fresh_v1" / name
        if not source.is_file():
            source = ROOT / "dist/alfred-fresh-v1-1.0.1/fresh_v1" / name
        assert recovery.digest(source.read_bytes()) == transaction.BASE[name]
        shutil.copyfile(source, dest)
        dest.chmod(0o644)
    for name in transaction.FILES:
        dest = release / "fresh_v1" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "fresh_v1" / name, dest)
    manifest = "".join(
        f"{recovery.digest(p.read_bytes())}  {p.relative_to(release)}\n"
        for p in sorted(release.rglob("*"))
        if p.is_file()
    ).encode()
    (release / "MANIFEST.sha256").write_bytes(manifest)
    for name in (
        "home/alfred/Alfred/gateway/PAUSE",
        "opt/alfred-developer-v1/active",
        "etc/alfred-fresh-v1/policy.json",
        "var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/plan.attempt.json",
        "var/lib/alfred-development-grants/T-0001.json",
        "var/lib/alfred-draft-pr-state/T-0002/publication-plan.json",
        "var/lib/alfred-draft-pr-authorizations/T-0002.json",
        "var/lib/alfred-qa-state/T-0002.json",
        "var/lib/alfred-reviewer-state/T-0002.json",
        "var/lib/alfred-draft-pr-private/github-token",
    ):
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("preserve original fixture")
        dest.chmod(0o600)
    (root / "opt/alfred-developer-v1/active").chmod(0o644)
    return root, release, recovery.digest(manifest), tmp_path / "backup"


def contents(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode & 0o777)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_recovery_extension_install_rollback_preserves_all_evidence(installation):
    root, release, pin, backup = installation
    before = contents(root)
    assert transaction.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    after = contents(root)
    assert {
        p for p in before.keys() | after.keys() if before.get(p) != after.get(p)
    } == {(transaction.PREFIX + n).lstrip("/") for n in transaction.FILES}
    record = root / "var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/plan.recovery.json"
    record.write_text("preserve subsequently authorized fixture decision")
    assert transaction.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    assert contents(root) == {
        **before,
        str(record.relative_to(root)): (
            record.read_bytes(),
            record.stat().st_mode & 0o777,
        ),
    }
    transaction.rollback(root, backup)


@pytest.mark.parametrize("position", range(3))
def test_partial_recovery_extension_install_restores_code_without_evidence_changes(
    installation, position
):
    root, release, pin, backup = installation
    before = contents(root)
    with pytest.raises(OSError):
        transaction.install(release, pin, root, backup, fail_after=position)
    assert contents(root) == before
