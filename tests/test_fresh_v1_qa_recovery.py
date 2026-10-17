"""handoff.4: pre-dispatch host failures are recorded, and the one T-0005 QA
recovery rejoins the automatic pipeline. Disposable tasks, real handoffs."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fresh_v1 import qa_recovery
from fresh_v1.handoffs import Held

ROOT = Path(__file__).resolve().parents[1]
pytest_plugins = ["tests.test_fresh_v1"]
EROFS = b"setfacl: calculator.py: Read-only file system"


def failing_share(world):
    def share(path, users):
        if path == world.repo:
            raise subprocess.CalledProcessError(1, ["/usr/bin/setfacl"], stderr=EROFS)

    return share


@pytest.fixture
def held_qa(world, monkeypatch):
    """Developer done; QA preparation hit the sandbox before any QA dispatch."""
    task = world.submit()
    monkeypatch.setattr(qa_recovery, "TARGET", (world.job["project"], task))
    assert world.tick() == {"state": "awaiting_development_approval"}
    world.approve_development()
    with patch.object(world, "share", failing_share(world)):
        result = world.tick()
    assert result["state"] == "held", result
    return world, world.jobdir(world.job)


@pytest.fixture
def incident(held_qa):
    """The exact pre-handoff.4 host shape: held QA attempt, no failure evidence."""
    world, root = held_qa
    (root / "qa.failure.json").unlink()  # Disposable fixture: the old host wrote none.
    # Host.worker seals this before the first role; the fixture's worker stands in.
    world.freeze_json(root / "worker-policy.json", world.p)
    (world.gateway.gateway_dir / "PAUSE").touch(mode=0o600)
    library = world.root / "qa-recovery-code"
    library.mkdir(mode=0o700)
    for name in qa_recovery.RUNTIME:
        shutil.copyfile(ROOT / "fresh_v1" / name, library / name)
        (library / name).chmod(0o600)
    evidence = qa_recovery.Evidence(
        world.policy_path,
        root,
        uid=os.geteuid(),
        trusted_root=world.root,
        alfred_uid=os.geteuid(),
        library=library,
    )
    return world, evidence


def approve_operator(incident, now=None):
    world, evidence = incident
    report = evidence.before()
    qa_recovery.authorize(
        evidence,
        qa_recovery.digest(qa_recovery.canonical(report)),
        "fixture-operator-decision",
        now=now,
    )
    world.verify_qa_recovery = lambda job: (world.guard(), evidence.verify())[1]


def test_target_is_the_held_t0005_task():
    assert qa_recovery.TARGET == ("dev-v1-accept", "T-0005")


def test_predispatch_host_failure_is_recorded_without_dispatch(held_qa):
    world, root = held_qa
    failure = json.loads((root / "qa.failure.json").read_bytes())
    assert failure["stage"] == "qa" and failure["phase"] == "host_prepare"
    assert failure["category"] == "read_only_filesystem"
    assert ("qa", "alfredqa") not in world.calls
    assert not (root / "qa-output").exists() and not (root / "qa.result.json").exists()
    # Recorded, so the poll's skip rule holds this task instead of blocking later ones.
    assert sorted(p.name for p in root.glob("*.failure.json")) == ["qa.failure.json"]


def test_dispatched_worker_failure_is_not_relabelled_as_predispatch(world):
    world.submit()
    world.tick()
    world.approve_development()
    with patch.object(
        world, "worker", side_effect=lambda *a: (
            setattr(world, "dispatched", True),
            (_ for _ in ()).throw(subprocess.TimeoutExpired("qa", 1)),
        )
    ):
        assert world.tick()["state"] == "held"
    assert not (world.jobdir(world.job) / "qa.failure.json").exists()


def test_inspection_and_decision_are_read_only_then_append_only(incident):
    _world, evidence = incident
    root = evidence.directory
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert evidence.before() == evidence.before()
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before
    approve_operator(incident)
    after = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert set(after) - set(before) == {qa_recovery.DECISION}
    assert all(after[name] == raw for name, raw in before.items())
    with pytest.raises(Held, match="already exists"):
        qa_recovery.authorize(evidence, "0" * 64, "fixture-second-decision")


def test_recovery_runs_qa_once_and_reaches_draft_pr_without_new_approval(incident):
    world, evidence = incident
    root = evidence.directory
    original = (root / "qa.attempt.json").read_bytes()
    approvals = sorted(p.name for p in world.grants.glob("grant-*.json"))
    approve_operator(incident)
    assert world.tick()["state"] == "held"  # PAUSE still wins
    assert ("qa", "alfredqa") not in world.calls
    (world.gateway.gateway_dir / "PAUSE").unlink()  # Disposable fixture only.
    assert world.tick() == {"state": "awaiting_publication_approval"}
    assert world.calls.count(("qa", "alfredqa")) == 1
    assert world.calls.count(("developer", "alfred")) == 1
    assert (root / qa_recovery.ATTEMPT).exists()
    assert (root / "qa-recovery-1.result.json").exists()
    assert not (root / "qa.result.json").exists()
    assert (root / "qa.attempt.json").read_bytes() == original
    assert sorted(p.name for p in world.grants.glob("grant-*.json")) == approvals
    world.approve_publication()
    assert world.tick()["state"] == "complete"
    assert world.calls.count(("qa", "alfredqa")) == 1
    assert len(world.pushes) == len(world.notifications) == 1


def test_new_qa_attempt_is_never_retried(incident):
    world, evidence = incident
    approve_operator(incident)
    (world.gateway.gateway_dir / "PAUSE").unlink()
    real = world.worker

    def ambiguous(job, stage, user):
        if stage == "qa":
            world.dispatched = True
            raise TimeoutError("ambiguous QA result")
        return real(job, stage, user)

    with patch.object(world, "worker", side_effect=ambiguous) as worker:
        assert world.tick()["state"] == "held"
        assert "requires reconciliation" in world.tick()["reason"]
        assert [c.args[1] for c in worker.call_args_list] == ["qa"]
    assert not (evidence.directory / "qa-recovery-1.result.json").exists()
    assert not (evidence.directory / "qa-recovery-1.failure.json").exists()


def test_dispatched_original_qa_cannot_be_recovered(incident):
    _world, evidence = incident
    (evidence.directory / "qa-output").mkdir()
    with pytest.raises(Held, match="additional handoff evidence"):
        evidence.before()


def test_changed_qa_input_after_decision_refuses(incident):
    world, evidence = incident
    approve_operator(incident)
    config = evidence.directory / "qa-input" / "config.json"
    config.chmod(0o600)
    config.write_bytes(config.read_bytes() + b" ")
    (world.gateway.gateway_dir / "PAUSE").unlink()
    result = world.tick()
    assert result["state"] == "held" and ("qa", "alfredqa") not in world.calls


def test_decision_requires_pause_and_expires_unused(incident):
    world, evidence = incident
    (world.gateway.gateway_dir / "PAUSE").unlink()
    with pytest.raises(Held, match="PAUSE"):
        approve_operator(incident)
    (world.gateway.gateway_dir / "PAUSE").touch(mode=0o600)
    approve_operator(incident, now=1)  # Created long ago, so already expired.
    with pytest.raises(Held, match="expired"):
        evidence.verify()


def test_failed_developer_claim_is_not_recoverable(incident):
    world, evidence = incident
    claim = next(world.grants.glob("execution-result-*.json"))
    record = json.loads(claim.read_bytes())
    claim.chmod(0o600)
    claim.write_text(json.dumps({**record, "status": "failed"}))
    with pytest.raises(Held, match="claimed and completed"):
        evidence.before()


def test_operator_cli_requires_root():
    with (
        patch.object(qa_recovery.os, "geteuid", return_value=1000),
        pytest.raises(PermissionError),
    ):
        qa_recovery.main()
