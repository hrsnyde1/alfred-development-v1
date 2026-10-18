"""handoff.11: plain-language owner texts, "yes" approvals and owner-run resend.

The owner is the only person on this Photon line. Approvals stay bound to the exact
sealed plan by the native in-thread reply, the owner's number, the same DM, no
forwarding and single use; the technical binding stays out of the text."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from developer_v1 import publication_approval
from fresh_v1 import host
from fresh_v1.protected import protected_json
from ops import alfred_dev_ops as ops
from tests.test_fresh_v1 import (DRAFT, HERMES, PROJECT, SIDE, IntakeRefused, event, intake,
                                 run_once, world)  # noqa: F401 (pytest fixture)

NAME = "Development Lab 001"  # the fixture registry's display name for the project


def file_request(world, confirm="yes"):
    request = event("owner-request", f"Please add a backend multiply helper in {PROJECT}.")
    world.gate.dispatch({"op": "observe", "event": request}, SIDE)
    response = world.gate.dispatch({
        "op": "submit", "event_id": request["messageId"],
        "text_digest": hashlib.sha256(request["content"]["text"].encode()).hexdigest(),
        "draft": DRAFT}, HERMES)
    assert response["state"] == "awaiting_confirmation"
    preview = world.messages[-1][1]
    world.gate.dispatch({"op": "observe", "event": event(
        "owner-confirm", confirm, world.gate._active.preview_id)}, SIDE)
    report = run_once(world.registry, intake.IntakeFiler(), world.gateway)
    task = report.filed[0]
    root = Path(world.p["jobs"]) / PROJECT / task
    world.directory(root)
    world.job = {"project": PROJECT, "task_id": task, "request_id": response["request_id"],
                 "owner_id": "mock-owner", "space_id": "mock-dm"}
    world.freeze_json(root / "job.json", world.job)
    return task, preview


def to_publication(world):
    task, _ = file_request(world)
    world.tick()
    world.approve_development()
    assert world.tick() == {"state": "awaiting_publication_approval"}
    return task


def latest_challenge(world):
    results = sorted(world.jobdir(world.job).glob("publication-challenge*.result.json"),
                     key=lambda p: p.stat().st_mtime_ns)
    return json.loads(results[-1].read_bytes())


def reply(world, text, identifier="owner-yes", **changes):
    challenge = latest_challenge(world)
    world.gate.dispatch({"op": "observe", "event": event(
        identifier, text, challenge["message_id"], **changes)}, SIDE)


# --- The request preview ------------------------------------------------------------------

def test_preview_is_plain_language_and_yes_confirms(world):
    task, preview = file_request(world, confirm="yes")
    assert preview.startswith(f"Here's what I'll hand to the development team for {NAME}:")
    assert DRAFT["objective"] in preview and 'Reply "yes"' in preview
    assert "SHA-256" not in preview and "{" not in preview and PROJECT not in preview
    assert task


@pytest.mark.parametrize("text", ["Yes", "yes.", "Go ahead", "Yes, go ahead"])
def test_preview_accepts_natural_yes(world, text):
    file_request(world, confirm=text)


@pytest.mark.parametrize("text", ["no", "maybe", "yes but change the colour"])
def test_preview_refuses_anything_but_yes(world, text):
    with pytest.raises(IntakeRefused):
        file_request(world, confirm=text)


# --- The publication approval -------------------------------------------------------------

def test_publication_text_is_plain_and_yes_publishes(world):
    task = to_publication(world)
    text = world.messages[-1][1]
    assert text.startswith("Ready to publish: ") and f"({NAME})" in text
    assert 'Reply "yes" to this message' in text and "Nothing goes live without you" in text
    for technical in (task, "SHA-256", "Final revision", "Approve GitHub Draft PR"):
        assert technical not in text
    reply(world, "Yes!")
    result = world.tick()
    assert result["state"] == "complete", result
    notice = world.notifications[0]
    assert notice.startswith(f"All done with {PROJECT}.") and task not in notice
    assert "ready for you to push" in notice


@pytest.mark.parametrize("changes", [
    {"nativeReplyTargetGuid": None},
    {"nativeReplyTargetGuid": "some-other-message"},
    {"sender": {"id": "someone-else"}},
    {"space": {"id": "other-dm", "type": "dm"}},
    {"nativeIsForward": True},
])
def test_yes_must_be_the_owners_direct_in_thread_reply(world, changes):
    to_publication(world)
    try:
        reply(world, "yes", **changes)
    except IntakeRefused:
        pass
    assert not list(world.grants.glob("publication-decision-*.json"))


@pytest.mark.parametrize("text", ["no", "not yet", "yes please change it first", ""])
def test_anything_but_yes_does_not_approve(world, text):
    to_publication(world)
    with pytest.raises(IntakeRefused):
        reply(world, text or " ")
    assert not list(world.grants.glob("publication-decision-*.json"))


def test_yes_is_single_use_and_expires_after_12_hours(world):
    to_publication(world)
    later = world.publication_issuer.clock() + publication_approval.SIMPLE_MAX_AGE + 1
    with patch.object(world.publication_issuer, "clock", return_value=later), \
            pytest.raises(IntakeRefused):
        reply(world, "yes")
    assert not list(world.grants.glob("publication-decision-*.json"))


def test_legacy_exact_phrase_still_approves(world):
    to_publication(world)
    world.approve_publication()
    assert world.tick()["state"] == "complete"


# --- Owner-run resend -----------------------------------------------------------------------

def owner_resend(world, n):
    path = world.jobdir(world.job) / f"publication-resend-{n}.json"
    path.write_text(json.dumps({"schema": "alfred.publication-resend/1", "project": PROJECT,
                                "task_id": world.job["task_id"], "n": n,
                                "authorized_by": "owner", "authorized_at": 1.0}))
    path.chmod(0o600)


def tick_at(world, now):
    trusted = lambda path: protected_json(path, trusted_uid=host.os.geteuid(),  # noqa: E731
                                          trusted_root=world.root)
    with patch.object(host, "protected_json", trusted), \
            patch.object(host.time, "time", return_value=now), \
            patch.object(world.publication_issuer, "clock", return_value=now):
        return world.tick()


def test_expired_approval_waits_for_the_owner_then_resends_once(world):
    to_publication(world)
    sent = len(world.messages)
    expired = world.publication_issuer.clock() + publication_approval.SIMPLE_MAX_AGE + 5
    # Expired but no resend asked for: nothing is sent on its own.
    assert tick_at(world, expired) == {"state": "awaiting_publication_approval"}
    assert len(world.messages) == sent
    owner_resend(world, 1)
    assert tick_at(world, expired) == {"state": "awaiting_publication_approval"}
    assert len(world.messages) == sent + 1
    assert world.messages[-1][1].startswith("Ready to publish: ")
    # The same authorization never sends twice.
    assert tick_at(world, expired) == {"state": "awaiting_publication_approval"}
    assert len(world.messages) == sent + 1
    import datetime as dt
    stamp = dt.datetime.fromtimestamp(expired + 10, dt.timezone.utc).isoformat()
    with patch.object(world.publication_issuer, "clock", return_value=expired + 10):
        reply(world, "yes", identifier="owner-yes-2", timestamp=stamp)
    assert tick_at(world, expired + 20)["state"] == "complete"


def test_resend_never_fires_while_the_approval_is_still_open(world):
    to_publication(world)
    sent = len(world.messages)
    owner_resend(world, 1)
    assert tick_at(world, world.publication_issuer.clock() + 60) == {
        "state": "awaiting_publication_approval"}
    assert len(world.messages) == sent


# --- The ops helper's resend command --------------------------------------------------------

@pytest.fixture
def jobs(tmp_path, monkeypatch):
    jobs, grants = tmp_path / "jobs", tmp_path / "grants"
    task = jobs / PROJECT / "T-0009"
    task.mkdir(parents=True)
    grants.mkdir()
    (task / "publication-challenge.result.json").write_text(json.dumps({"challenge": "abc"}))
    (grants / "publication-challenge-abc.json").write_text(json.dumps({"expires_at": 100.0}))
    monkeypatch.setattr(ops, "JOBS", jobs)
    monkeypatch.setattr(ops, "GRANTS", grants)
    return task, grants


def test_helper_resend_writes_one_owner_authorization(jobs):
    task, _ = jobs
    assert ops.resend("T-0009", 200.0)["resend"] == 1
    record = json.loads((task / "publication-resend-1.json").read_text())
    assert record["schema"] == "alfred.publication-resend/1" and record["n"] == 1
    with pytest.raises(ops.Refused, match="already queued"):
        ops.resend("T-0009", 300.0)


@pytest.mark.parametrize("setup,message", [
    (lambda t, g: None, "still open"),
    (lambda t, g: (g / "publication-decision-abc.json").write_text("{}"), "already approved"),
])
def test_helper_resend_refuses_open_or_approved(jobs, setup, message):
    task, grants = jobs
    setup(task, grants)
    with pytest.raises(ops.Refused, match=message):
        ops.resend("T-0009", 50.0 if message == "still open" else 200.0)
    assert not list(task.glob("publication-resend-*.json"))


@pytest.mark.parametrize("name", ["T-9", "../T-0009", "T-0009; rm", "X-0009"])
def test_helper_resend_refuses_malformed_task(jobs, name):
    with pytest.raises(ops.Refused):
        ops.resend(name, 200.0)
