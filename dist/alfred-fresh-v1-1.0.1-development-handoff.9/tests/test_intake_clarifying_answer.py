"""handoff.9: Hermes asks a clarifying question first, then submits the owner's short
answer ("2", "yes"). The intake files the owner's own earlier request from the same DM
instead, with the project still taken only from genuine owner text."""

import hashlib
import json
import time
from pathlib import Path

import pytest
import yaml

from tests.test_fresh_v1 import (DRAFT, HERMES, PROJECT, SIDE, IntakeRefused, event, intake,
                                 run_once, world)  # noqa: F401 (pytest fixture)


def observe(world, identifier, text, **changes):
    message = event(identifier, text, **changes)
    world.gate.dispatch({"op": "observe", "event": message}, SIDE)
    return message


def submit_turn(world, message, op="submit"):
    request = {
        "op": op,
        "event_id": message["messageId"],
        "text_digest": hashlib.sha256(message["content"]["text"].encode()).hexdigest(),
    }
    if op == "submit":
        request["draft"] = DRAFT
    return world.gate.dispatch(request, HERMES)


def test_clarifying_answer_files_the_owners_original_request(world):
    request = observe(world, "owner-request", f"Please add a backend multiply helper in {PROJECT}.")
    answer = observe(world, "owner-answer", "2")
    assert submit_turn(world, answer)["state"] == "awaiting_confirmation"
    assert world.gate._active.message_id == request["messageId"]
    assert world.gate._active.project == PROJECT
    # Hermes's status call on the answer turn follows the original request.
    assert submit_turn(world, answer, op="status") == {"state": "awaiting_confirmation"}
    # The answer is consumed and cannot be submitted again.
    with pytest.raises(IntakeRefused):
        submit_turn(world, answer)
    observe(world, "owner-confirm", "Yes, go ahead", target=world.gate._active.preview_id)
    [envelope] = (world.gateway.intake_dir / "inbox").glob("*.json")
    filed = envelope.read_text()
    assert request["content"]["text"] in filed and f'"{PROJECT}"' in filed
    report = run_once(world.registry, intake.IntakeFiler(), world.gateway)
    assert len(report.filed) == 1, report


def test_answer_without_an_earlier_request_still_fails_closed(world):
    answer = observe(world, "owner-answer", "2")
    with pytest.raises(IntakeRefused) as refused:
        submit_turn(world, answer)
    assert refused.value.code == "explicit_authorized_project_required"
    assert not world.messages


def test_expired_original_request_is_not_linked(world):
    observe(world, "owner-request", f"Please add a backend multiply helper in {PROJECT}.")
    start = time.time()
    world.gate.clock = lambda: start + 301
    answer = observe(world, "owner-answer", "2")
    with pytest.raises(IntakeRefused):
        submit_turn(world, answer)
    assert not world.messages


def test_request_from_another_dm_is_not_linked(world):
    observe(world, "owner-request", f"Please add a backend multiply helper in {PROJECT}.",
            space={"id": "other-dm", "type": "dm"})
    answer = observe(world, "owner-answer", "2")
    with pytest.raises(IntakeRefused):
        submit_turn(world, answer)
    assert not world.messages


def test_earlier_requests_for_different_projects_are_ambiguous(world):
    data = yaml.safe_load(Path(world.p["registry"]).read_bytes())
    other = json.loads(json.dumps(data["projects"][0]))
    other.update(id="other-project", local_path=str(world.root / "other"))
    other["repo"]["github"] = "fixtureowner/other"
    data["projects"].append(other)
    Path(world.p["registry"]).write_text(yaml.safe_dump(data))
    observe(world, "request-1", f"Please add a backend multiply helper in {PROJECT}.")
    observe(world, "request-2", "Please add a backend multiply helper in other-project.")
    answer = observe(world, "owner-answer", "yes")
    with pytest.raises(IntakeRefused):
        submit_turn(world, answer)
    assert not world.messages


def test_a_self_contained_request_is_unchanged(world):
    request = observe(world, "owner-request", f"Please add a backend multiply helper in {PROJECT}.")
    assert submit_turn(world, request)["state"] == "awaiting_confirmation"
    assert world.gate._active.message_id == request["messageId"]
