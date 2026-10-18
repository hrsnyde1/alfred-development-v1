"""handoff.29 (owner-authorized 2026-10-18): one "yes" to the request preview also
approves its draft PR for delegated projects. Merging stays the owner's. Broader wording."""

import json
import os
from pathlib import Path

import pytest

from developer_v1 import owner_grants
from developer_v1.publication_approval import DELEGATED, DELEGATED_DECISION
from developer_v1.router import Denied
from developer_v1.trusted_intake_development import _development_request_text
from tests.test_fresh_v1 import PROJECT, world  # noqa: F401 (pytest fixture)


def delegate(world, publication="delegated", projects=(PROJECT,)):
    path = Path(world.root) / "delegation.json"
    path.write_text(json.dumps({
        "schema": owner_grants.DELEGATION_SCHEMA,
        "development_approval": {"enabled": True, "projects": list(projects)},
        "publication_approval": publication}))
    path.chmod(0o644)
    world.publication_issuer.delegation_policy = path
    world.publication_issuer.policy_owner = os.geteuid()
    return path


def test_one_yes_takes_a_request_all_the_way_to_a_draft_pr(world):
    delegate(world)
    world.submit()
    assert world.tick() == {"state": "awaiting_development_approval"}
    world.approve_development()
    result = world.tick()
    assert result["state"] == "complete", result
    # No "Ready to publish" text was sent; the only texts are the request and the done one.
    assert not any("Ready to publish" in text for _, text in world.messages)
    assert len(world.pushes) == len(world.notifications) == 1
    assert "ready for you to push" in world.notifications[0]
    # The record says delegated and never claims an owner reply.
    grants = Path(world.p["grant_root"])
    [receipt] = [json.loads(p.read_text()) for p in grants.glob("publication-challenge-*.json")]
    [decision] = [json.loads(p.read_text()) for p in grants.glob("publication-decision-*.json")]
    assert receipt["schema"] == DELEGATED and decision["schema"] == DELEGATED_DECISION
    assert decision["owner_event_id"].startswith("delegated-publication-")


def test_owner_policy_still_asks_for_the_second_yes(world):
    delegate(world, publication="owner")
    world.submit()
    world.tick()
    world.approve_development()
    assert world.tick() == {"state": "awaiting_publication_approval"}
    assert not world.pushes


def test_a_project_outside_the_policy_still_asks(world):
    delegate(world, projects=("demo-site",))
    world.submit()
    world.tick()
    world.approve_development()
    assert world.tick() == {"state": "awaiting_publication_approval"}


def test_turning_delegation_off_before_publishing_stops_the_draft_pr(world):
    path = delegate(world)
    issuer = world.publication_issuer
    original = issuer.prepare

    def prepare_after_owner_turned_it_off(reference, *, peer_uid):
        policy = json.loads(path.read_text())
        policy["publication_approval"] = "owner"
        path.write_text(json.dumps(policy))
        return original(reference, peer_uid=peer_uid)

    issuer.prepare = prepare_after_owner_turned_it_off
    world.submit()
    world.tick()
    world.approve_development()
    result = world.tick()
    assert result["state"] == "held" and not world.pushes


def test_a_tampered_delegated_record_is_refused(world):
    delegate(world)
    issuer = world.publication_issuer
    original = issuer.prepare

    def tamper_then_prepare(reference, *, peer_uid):
        path = Path(world.p["grant_root"]) / f"publication-decision-{reference}.json"
        record = json.loads(path.read_text())
        record["owner_event_id"] = "owner-reply-that-never-happened"
        path.chmod(0o600)
        path.write_text(json.dumps(record))
        return original(reference, peer_uid=peer_uid)

    issuer.prepare = tamper_then_prepare
    world.submit()
    world.tick()
    world.approve_development()
    assert world.tick()["state"] == "held" and not world.pushes


@pytest.mark.parametrize("publication", ["owner", "delegated"])
def test_the_policy_accepts_only_owner_or_delegated(tmp_path, publication):
    path = tmp_path / "delegation.json"
    path.write_text(json.dumps({"schema": owner_grants.DELEGATION_SCHEMA,
                                "development_approval": {"enabled": True, "projects": ["x-site"]},
                                "publication_approval": publication}))
    path.chmod(0o644)
    policy = owner_grants.load_delegation_policy(path, owner_uid=os.geteuid())
    assert owner_grants.publication_delegation_permits(policy, "x-site") == (publication == "delegated")
    assert not owner_grants.publication_delegation_permits(policy, "other")
    path.write_text(path.read_text().replace(publication, "merge"))
    with pytest.raises(Denied):
        owner_grants.load_delegation_policy(path, owner_uid=os.geteuid())


@pytest.mark.parametrize("text,project", [
    ("Make the demo site's footer text gray.", "demo-site"),
    ("Hey Alfred, I want you to make a pricing page on the demo site with blue cards in a "
     "3-column grid, the price in bold, and a Buy button under each.", "demo-site"),
    ("Can you add dark mode to the site?", None),
    ("I'd like the login button to be green and centered", None),
    ("Get rid of the banner on the homepage", None),
    ("Set up a contact form on the website", None),
])
def test_requests_in_the_owners_own_words_are_accepted(text, project):
    assert _development_request_text(text, project=project)


@pytest.mark.parametrize("text,project", [
    ("How is the demo site doing?", "demo-site"),
    ("What is on my calendar today?", None),
    ("Remind me to call mom", None),
    ("I need groceries", None),
])
def test_questions_and_ordinary_chat_stay_chat(text, project):
    assert not _development_request_text(text, project=project)
