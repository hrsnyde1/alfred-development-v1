"""handoff.24: the owner confirms a completion text they received although its delivery
record stayed `uncertain` with no receipt (demo-site T-0003). The poll then completes the
task. The uncertain record and every attempt and failure file stay exactly as they were,
and nothing is sent or resent."""

import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fresh_v1 import host
from fresh_v1.handoffs import Held, write_once
from fresh_v1.protected import protected_json
from ops import alfred_dev_ops as ops
from tests.test_fresh_v1 import OWNER, PROJECT, SIDE, save, world  # noqa: F401

CONFIRMED = {"completion-confirmed.json", "completion-confirmed.delivery.json"}


@pytest.fixture
def held(world, monkeypatch):
    """A task whose completion text went out but whose delivery record stayed uncertain."""
    monkeypatch.setattr(ops, "JOBS", Path(world.p["jobs"]))
    monkeypatch.setattr(ops, "DELIVERY", Path(world.p["completion_state"]))
    monkeypatch.setattr(ops, "delivery_uid", os.geteuid)
    world.submit()
    world.tick()
    world.approve_development()
    world.tick()
    world.approve_publication()
    world.transport_receipt = None
    assert world.tick() == {"state": "held",
                            "reason": "completion delivery requires reconciliation"}
    assert len(world.notifications) == 1
    return world


def as_failure(world):
    """The host's T-0003 shape: the acknowledgement timed out inside the worker, so the
    host recorded failure evidence instead of a result."""
    job = world.jobdir(world.job)
    (job / "completion.result.json").unlink()
    write_once(job / "completion.failure.json",
               {"stage": "completion", "phase": "python", "category": "python_failed"})


def name(world):
    return f"{PROJECT}/{world.job['task_id']}"


def files(world):
    return {p.name: p.read_bytes() for p in world.jobdir(world.job).iterdir() if p.is_file()}


def delivery(world):
    return (Path(world.p["completion_state"]) / "delivery.json").read_bytes()


def poll(world):
    save(world.gateway.gateway_dir / "v1-1-intake.json", {"owner_sender_id": OWNER})
    with (
        patch.object(host, "require_root"),
        patch.object(host, "root_directory"),
        patch.object(host, "protected_json", lambda p: protected_json(
            p, trusted_uid=os.geteuid(), trusted_root=world.root)),
        patch.object(host, "Host", return_value=world),
        patch.object(host.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=SIDE)),
    ):
        return host.poll(world.policy_path)


@pytest.mark.parametrize("failure", [True, False])
def test_owner_confirmation_completes_the_task_without_sending(held, failure):
    world = held
    if failure:
        as_failure(world)
    still_held = poll(world)
    assert still_held["state"] == "held"
    before, tracking = files(world), delivery(world)
    result = ops.confirm_delivered(name(world), 5.0)
    assert result["transport_state"] == "uncertain"
    after = files(world)
    assert set(after) - set(before) == CONFIRMED
    assert all(after[k] == v for k, v in before.items())
    assert after["completion-confirmed.delivery.json"] == tracking == delivery(world)
    record = json.loads(after["completion-confirmed.json"])
    assert record["receipt_id"] is None and record["resend_permitted"] is False
    published = json.loads(after["publisher.result.json"])

    assert poll(world) == {"state": "idle"}
    complete = json.loads((world.jobdir(world.job) / "complete.json").read_bytes())
    assert complete == {"state": "complete", "draft_pr_url": published["draft_pr_url"],
                        "notification": "owner_confirmed_received"}
    assert poll(world) == {"state": "idle"}
    # Nothing was sent or resent, and the uncertain record is still the duplicate guard.
    assert len(world.notifications) == 1 and len(world.pushes) == 1
    assert delivery(world) == tracking
    (state,) = [r for r in json.loads(tracking)["records"].values()
                if r["identity"][1] == world.job["task_id"]]
    assert state["state"] == "uncertain" and state["receipt_id"] is None
    assert {k: v for k, v in files(world).items() if k != "complete.json"} == after
    with pytest.raises(ops.Refused, match="already completed"):
        ops.confirm_delivered(name(world), 6.0)


def refuse(world, task, message):
    before, tracking = files(world), delivery(world)
    with pytest.raises(ops.Refused, match=message):
        ops.confirm_delivered(task, 5.0)
    assert files(world) == before and delivery(world) == tracking


@pytest.mark.parametrize("task,message", [
    ("dev-v1-accept/T-0099", "not found"),
    ("T-0003", "project/task"),
    ("demo-site/../T-0003", "project/task"),
])
def test_refuses_unknown_tasks(held, task, message):
    refuse(held, task, message)


def test_refuses_a_second_confirmation(held):
    ops.confirm_delivered(name(held), 5.0)
    refuse(held, name(held), "already confirmed")


def test_refuses_a_task_stopped_for_another_reason(held):
    write_once(held.jobdir(held.job) / "owner-abandoned.failure.json", {"stage": "owner-abandoned"})
    refuse(held, name(held), "stopped before")


def test_refuses_a_sent_completion(world, monkeypatch):
    monkeypatch.setattr(ops, "JOBS", Path(world.p["jobs"]))
    monkeypatch.setattr(ops, "DELIVERY", Path(world.p["completion_state"]))
    monkeypatch.setattr(ops, "delivery_uid", os.geteuid)
    world.submit()
    world.tick()
    world.approve_development()
    world.tick()
    world.approve_publication()
    assert world.tick()["state"] == "complete"
    refuse(world, name(world), "did not end uncertain")


def test_refuses_before_the_completion_text(world, monkeypatch):
    monkeypatch.setattr(ops, "JOBS", Path(world.p["jobs"]))
    world.submit()
    world.tick()
    refuse(world, name(world), "has not attempted")


def test_refuses_a_record_that_is_not_this_draft(held):
    config = held.jobdir(held.job) / "completion" / "config.json"
    value = json.loads(config.read_bytes())
    value["binding"]["final_revision"] = "0" * 40
    config.chmod(0o600)
    config.write_text(json.dumps(value))
    refuse(held, name(held), "does not match")


def test_refuses_a_record_that_was_sent(held):
    path = Path(held.p["completion_state"]) / "delivery.json"
    state = json.loads(path.read_bytes())
    for record in state["records"].values():
        if record["identity"][1] == held.job["task_id"]:
            record.update(state="sent", receipt_id="spc-msg-1")
    path.write_text(json.dumps(state))
    refuse(held, name(held), "is sent, not uncertain")


def test_refuses_unprotected_delivery_state(held):
    (Path(held.p["completion_state"]) / "delivery.json").chmod(0o640)
    refuse(held, name(held), "not protected")


def test_refuses_while_a_send_holds_the_tracker_lock(held):
    fd = os.open(Path(held.p["completion_state"]) / "delivery.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        refuse(held, name(held), "being sent")
    finally:
        os.close(fd)


@pytest.mark.parametrize("tamper", ["record", "snapshot"])
def test_a_tampered_confirmation_holds_instead_of_completing(held, tamper):
    ops.confirm_delivered(name(held), 5.0)
    job = held.jobdir(held.job)
    if tamper == "record":
        path = job / "completion-confirmed.json"
        value = json.loads(path.read_bytes())
        value["resend_permitted"] = True
    else:
        path = job / "completion-confirmed.delivery.json"
        value = json.loads(path.read_bytes())
        value["version"] = 1
        value["records"] = {}
    path.write_text(json.dumps(value))
    with pytest.raises(Held, match="confirmation invalid"):
        poll(held)
    assert not (job / "complete.json").exists()
    assert len(held.notifications) == 1


def test_the_owner_must_type_received(held, monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "AUDIT", tmp_path / "audit.jsonl")
    monkeypatch.setattr(ops.os, "geteuid", lambda: 0)
    monkeypatch.setattr("sys.argv", ["alfred-dev-ops", "confirm-delivered", name(held)])
    before = files(held)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    assert ops.main() == 1 and files(held) == before
    monkeypatch.setattr("builtins.input", lambda prompt: "RECEIVED")
    assert ops.main() == 0 and set(files(held)) - set(before) == CONFIRMED
    outcomes = [json.loads(line)["outcome"]
                for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert outcomes == ["refused_or_failed", "ok"]
