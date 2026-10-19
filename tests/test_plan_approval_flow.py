"""handoff.33 (owner-authorized 2026-10-19): the owner's one approval is the CTO's plan.

"All I want is a simple approval text of the plan that is being mapped out. I don't want
the first one where it's development task created." For a project the root policy puts in
development_approval "owner" mode, the request is filed with no preview, the plan reaches
the owner as a few plain lines ending "Reply yes to start.", and that yes is the
development grant. Draft PR and merge stay delegated (handoffs 29 and 31), so the owner's
texts from the pipeline are exactly two: the plan, and done.

Real workers, real Git, the real Intake, issuers, QA and Reviewer; models, Photon and
GitHub are the fixtures of tests/test_fresh_v1.py and tests/test_auto_merge_undo.py.
"""

import hashlib
import json
import os
import types
from pathlib import Path
from unittest.mock import patch

import intake
import pytest
from alfred.gateway.dispatcher import run_once

from developer_v1 import owner_grants
from developer_v1.router import Denied
from developer_v1.trusted_intake_development import IntakeRefused
from fresh_v1 import host, squads
from fresh_v1.protected import protected_json
from independent_qa import worker as qa
from tests.test_auto_merge_undo import MergeWorld
from tests.test_fresh_v1 import DRAFT, HERMES, OWNER, PROJECT, SIDE, event, save


@pytest.fixture
def world(tmp_path):
    previous = os.umask(0o077)
    try:
        yield MergeWorld(tmp_path)
    finally:
        os.umask(previous)


def policy(mode="owner", projects=(PROJECT,), publication="delegated", merge="delegated"):
    development = {"enabled": True, "projects": list(projects)}
    if mode is not None:
        development["mode"] = mode
    value = {"schema": owner_grants.DELEGATION_SCHEMA, "development_approval": development,
             "publication_approval": publication}
    if merge is not None:
        value["merge_approval"] = merge
    return value


def install_policy(world, value):
    """The owner's root policy, read by the Intake and both issuers on every use."""
    path = Path(world.root) / "delegation.json"
    path.write_text(json.dumps(value))
    path.chmod(0o644)
    world.gate.delegation_policy, world.gate.policy_owner = path, os.geteuid()
    world.development_issuer.delegation_policy = path
    world.publication_issuer.delegation_policy = path
    world.publication_issuer.policy_owner = os.geteuid()
    return path


def submit_direct(world, identifier="mock-request"):
    """The owner's message, Hermes's draft, and the filing: no preview, no confirmation."""
    message = event(identifier, f"Please add a backend multiply helper in {PROJECT}.")
    world.gate.dispatch({"op": "observe", "event": message}, SIDE)
    response = world.gate.dispatch(
        {"op": "submit", "event_id": identifier,
         "text_digest": hashlib.sha256(message["content"]["text"].encode()).hexdigest(),
         "draft": DRAFT}, HERMES)
    assert response["state"] == "submitted", response
    assert world.messages == []  # Step 1 sends nothing.
    report = run_once(world.registry, intake.IntakeFiler(), world.gateway)
    assert len(report.filed) == 1, report
    task = report.filed[0]
    root = Path(world.p["jobs"]) / PROJECT / task
    world.directory(root)
    world.job = {"project": PROJECT, "task_id": task, "request_id": response["request_id"],
                 "owner_id": OWNER, "space_id": "mock-dm"}
    world.freeze_json(root / "job.json", world.job)
    return task, response


def challenge(world):
    staged = json.loads((world.jobdir(world.job) / "development-challenge.result.json").read_bytes())
    receipt = json.loads((world.grants / f"challenge-{staged['challenge']}.json").read_bytes())
    return staged, receipt


def reply(world, text, identifier="mock-plan-reply", target=None, **changes):
    staged, _ = challenge(world)
    return world.gate.dispatch({"op": "observe", "event": event(
        identifier, text, target or staged["message_id"], **changes)}, SIDE)


def test_request_to_done_with_only_the_plan_text_and_the_done_text(world):
    install_policy(world, policy())
    task, response = submit_direct(world)
    # Filed from the owner's own message, bound to the exact envelope it published.
    route = json.loads((world.grants / f"request-route-{response['request_id']}.json").read_bytes())
    inbox = world.gateway.intake_dir / "inbox" / f"{response['request_id']}.json"
    assert route["schema"] == "alfred.direct-request-route/1"
    assert route["approval"] == "owner_plan_reply" and route["request_event_id"] == "mock-request"
    assert route["project"] == PROJECT and route["owner_id"] == OWNER
    assert "confirmation_event_id" not in route
    assert world.tick() == {"state": "awaiting_development_approval"}
    assert world.calls == [("plan", "alfred")]
    [(space, plan_text)] = world.messages
    assert space == "mock-dm" and plan_text.endswith("Reply yes to start.")
    assert "Approve development" not in plan_text
    # Nothing runs before the owner's yes.
    assert world.tick() == {"state": "awaiting_development_approval"}
    assert world.calls == [("plan", "alfred")]
    assert reply(world, "Yes!") == {"state": "development_approved",
                                    "reference": challenge(world)[0]["challenge"]}
    result = world.tick()
    assert result["state"] == "complete", result
    # Exactly two owner texts from the pipeline: the plan, and done (merged, with undo).
    assert world.messages == [("mock-dm", plan_text)]
    [done] = world.notifications
    assert "merged into main" in done and "Reply undo within 24 hours" in done
    assert len(world.github.squashes) == 1
    # The grant is the owner's own reply to the plan text, recorded as exactly that.
    staged, receipt = challenge(world)
    grant = json.loads((world.grants / f"grant-{staged['challenge']}.json").read_bytes())
    decision = json.loads((world.grants / f"decision-{staged['challenge']}.json").read_bytes())
    assert grant["source"] == "photon_native_owner_reply"
    assert decision["content_sha256"] == hashlib.sha256(b"yes").hexdigest()
    assert receipt["expires_at"] == receipt["issued_at"] + owner_grants.PLAN_MAX_AGE
    assert not list(world.grants.glob("delegation-*.json"))
    # Independent QA accepted that evidence and passed the work.
    assert json.loads((world.jobdir(world.job) / "qa.result.json").read_bytes())["decision"] == "PASS"
    assert world.tick()["state"] == "complete"
    assert len(world.messages) == len(world.notifications) == 1


def test_the_plan_text_is_the_goal_the_team_and_the_files_in_a_few_lines(world):
    install_policy(world, policy())
    submit_direct(world)
    world.tick()
    [(_, text)] = world.messages
    lines = text.splitlines()
    name = world.gate._display_name(PROJECT)
    assert lines[0].startswith(f"Plan for {name}: ")
    plan = json.loads((world.gateway.gateway_dir / "cto-plans"
                       / f"{PROJECT}-{world.job['task_id']}.json").read_bytes())
    assert plan["objective"].split("\n")[0][:60] in lines[0]
    assert lines[1] == "- Backend: calculator.py, test_calculator.py"
    assert lines[-1] == "Reply yes to start."
    assert len(lines) <= 5 and len(text) <= owner_grants.PLAN_TEXT_MAX
    # No hashes, task numbers or branch names for the owner to read.
    assert world.job["task_id"] not in text and plan["baseline_revision"] not in text
    assert "SHA" not in text and "worktree" not in text


def test_the_team_split_matches_the_specialists_work(world):
    request = {"scope": ["api.py", "app.js", "styles.css", "README.md"],
               "specialists": ["backend", "frontend"]}
    assert owner_grants._team_lines(request) == [
        "Backend: api.py, README.md", "Frontend: app.js, styles.css"]
    many = {"scope": [f"f{i}.py" for i in range(7)], "specialists": ["backend"]}
    assert owner_grants._team_lines(many) == ["Backend: f0.py, f1.py, f2.py, f3.py, 3 more"]


@pytest.mark.parametrize("text", ["What about tests?", "no", "yes but use floats", "maybe later"])
def test_anything_but_yes_starts_nothing_and_the_plan_stays_open(world, text):
    install_policy(world, policy())
    submit_direct(world)
    world.tick()
    with pytest.raises(IntakeRefused) as refused:
        reply(world, text, identifier="mock-other-reply")
    assert refused.value.code == "development_approval_refused"
    assert not list(world.grants.glob("grant-*.json"))
    assert world.tick() == {"state": "awaiting_development_approval"}
    assert world.calls == [("plan", "alfred")]
    # The owner's yes still works afterwards.
    assert reply(world, "yes")["state"] == "development_approved"


def test_a_yes_not_in_the_plan_texts_thread_or_forwarded_is_refused(world):
    install_policy(world, policy())
    submit_direct(world)
    world.tick()
    with pytest.raises(IntakeRefused):
        reply(world, "yes", nativeIsForward=True)
    with pytest.raises(IntakeRefused):
        reply(world, "yes", identifier="other-sender", sender={"id": "someone-else"})
    # A yes outside the thread is ordinary chat, never an approval.
    assert world.gate.dispatch({"op": "observe", "event": event(
        "mock-loose-yes", "yes")}, SIDE)["state"] != "development_approved"
    assert not list(world.grants.glob("grant-*.json"))


def test_an_expired_plan_text_cannot_be_approved(world):
    install_policy(world, policy())
    submit_direct(world)
    world.tick()
    _, receipt = challenge(world)
    real = host.time.time
    # Still open long after the old 5-minute window: another task waits instead of sending.
    with patch.object(host, "time", types.SimpleNamespace(time=lambda: real() + 3600)):
        assert world.owner_text_open("development")
    with patch.object(host, "time", types.SimpleNamespace(
            time=lambda: receipt["expires_at"] + 1)):
        assert not world.owner_text_open("development")
    world.development_issuer.clock = lambda: receipt["expires_at"] + 1
    with pytest.raises(IntakeRefused):
        reply(world, "yes")
    assert not list(world.grants.glob("grant-*.json"))
    assert world.tick() == {"state": "awaiting_development_approval"}
    assert world.calls == [("plan", "alfred")]


def test_an_unlisted_project_keeps_the_preview_and_the_full_approval(world):
    install_policy(world, policy(projects=("demo-site",)))
    world.submit()  # Asserts the preview, the confirmation and the filing.
    assert world.messages[0][1].startswith("Here's what I'll hand to the development team")
    assert world.tick() == {"state": "awaiting_development_approval"}
    assert "Approve development" in world.messages[1][1]
    _, receipt = challenge(world)
    assert "project_name" not in receipt
    assert receipt["expires_at"] == receipt["issued_at"] + owner_grants.MAX_AGE
    # A plain yes is not the exact phrase this text asked for.
    with pytest.raises(IntakeRefused):
        reply(world, "yes")
    world.approve_development()
    # Not listed: the draft PR is the owner's to approve, and nothing merges on its own.
    assert world.tick() == {"state": "awaiting_publication_approval"}
    assert not world.github.squashes


def test_delegated_mode_still_approves_without_any_text(world):
    """handoffs 29/31 unchanged: a policy without "mode" (or "delegated") previews the
    request and approves the plan itself."""
    install_policy(world, policy(mode=None))
    world.development_issuer.delegation_policy = world.gate.delegation_policy
    world.submit()
    assert world.messages[0][1].startswith("Here's what I'll hand")
    world.tick()
    staged = json.loads((world.jobdir(world.job) / "development-challenge.result.json").read_bytes())
    assert staged["state"] == "development_approved_by_delegation"
    assert len(world.messages) == 1  # Only the preview; no plan text.
    [record] = world.grants.glob("delegation-*.json")
    assert json.loads(record.read_text())["decided_by"] == "owner_delegation_policy"


def test_the_timer_poll_accepts_only_a_genuine_direct_route(world):
    install_policy(world, policy())
    _, response = submit_direct(world)
    save(world.gateway.gateway_dir / "v1-1-intake.json", {"owner_sender_id": OWNER})
    route_path = world.grants / f"request-route-{response['request_id']}.json"
    original = route_path.read_bytes()

    def poll():
        with (patch.object(host, "require_root"),
              patch.object(host, "root_directory", lambda path: None),
              patch.object(host, "protected_json", lambda p: protected_json(
                  p, trusted_uid=os.geteuid(), trusted_root=world.root)),
              patch.object(host, "Host", return_value=world),
              patch.object(host.pwd, "getpwnam",
                           return_value=type("Photon", (), {"pw_uid": SIDE})())):
            return host.poll(world.policy_path)

    assert poll()["state"] == "awaiting_development_approval"
    for change in ({"approval": "policy"}, {"confirmation_event_id": "forged"},
                   {"sidecar_uid": SIDE + 1}, {"request_event_id": ""}):
        route_path.chmod(0o600)
        route_path.write_bytes(json.dumps({**json.loads(original), **change}).encode())
        with pytest.raises(host.Held):
            poll()


def test_the_squad_chat_says_the_plan_went_to_hayden(world, tmp_path):
    install_policy(world, policy())
    submit_direct(world)
    world.tick()
    texts = [e["text"] for e in squads.events(world.jobdir(world.job), tmp_path, 0)]
    assert (f"📨 Plan for {PROJECT} {world.job['task_id']} sent to Hayden; "
            "waiting for the yes to start.") in texts
    reply(world, "yes")
    world.tick()
    texts = [e["text"] for e in squads.events(world.jobdir(world.job), tmp_path, 0)]
    assert any("(Hayden approved it with the plan)" in t for t in texts)


def test_the_policy_shape():
    def load(value, tmp):
        path = tmp / "delegation.json"
        path.write_text(json.dumps(value))
        path.chmod(0o644)
        return owner_grants.load_delegation_policy(path, owner_uid=os.geteuid())

    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        owner = load(policy(), tmp)
        assert owner_grants.plan_approval_requested(owner, PROJECT)
        assert not owner_grants.delegation_permits(owner, PROJECT)
        assert owner_grants.publication_delegation_permits(owner, PROJECT)
        assert owner_grants.merge_delegation_permits(owner, PROJECT)
        assert not owner_grants.plan_approval_requested(owner, "demo-site")
        assert not owner_grants.publication_delegation_permits(owner, "demo-site")
        for mode in (None, "delegated"):
            delegated = load(policy(mode=mode), tmp)
            assert owner_grants.delegation_permits(delegated, PROJECT)
            assert not owner_grants.plan_approval_requested(delegated, PROJECT)
        off = load({**policy(), "development_approval": {
            "enabled": False, "projects": [PROJECT], "mode": "owner"}}, tmp)
        assert not owner_grants.plan_approval_requested(off, PROJECT)
        for bad in ({"mode": "anyone"}, {"mode": True}, {"approver": "owner"}):
            value = policy()
            value["development_approval"] = {**value["development_approval"], **bad}
            with pytest.raises(Denied):
                load(value, tmp)


def test_qa_rejects_a_plain_yes_to_a_technical_text_and_a_policy_record_in_owner_mode():
    technical = {"phrase_sha256": "a" * 64, "issued_at": 100, "expires_at": 400}
    plan = {**technical, "project_name": "Demo", "expires_at": 100 + qa.PLAN_MAX_AGE}
    yes = hashlib.sha256(b"yes").hexdigest()
    assert yes not in qa.accepted_replies(technical)
    assert yes in qa.accepted_replies(plan) and "a" * 64 in qa.accepted_replies(plan)
    # A plan receipt with the 5-minute window is not a plan text.
    assert yes not in qa.accepted_replies({**plan, "expires_at": 400})
    assert qa.PLAN_REPLIES == owner_grants.PLAN_REPLIES
