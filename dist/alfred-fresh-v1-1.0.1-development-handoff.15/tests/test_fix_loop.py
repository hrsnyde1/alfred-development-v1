"""handoff.15: when QA or the Reviewer finds problems, the same approved team fixes
them, up to three rounds, then Alfred tells the owner in plain language."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from developer_v1.owner_grants import MAX_FIX_ROUNDS
from developer_v1.router import Denied
from fresh_v1 import host
from tests import test_fresh_v1 as fresh
from tests.test_fresh_v1 import world  # noqa: F401 (pytest fixture)


class RecordingBroker(fresh.MultiplyBroker):
    objectives = []

    def generate(self, choice, *, objective, sources):
        RecordingBroker.objectives.append(objective)
        return super().generate(choice, objective=objective, sources=sources)


class CalculatorOnlyBroker(fresh.MultiplyBroker):
    """Changes one of its two assigned files, as most real requests do."""

    def generate(self, choice, *, objective, sources):
        result = super().generate(choice, objective=objective, sources=sources)
        result["edits"] = [e for e in result["edits"] if e["path"] == "calculator.py"]
        return result


@pytest.fixture
def recording(monkeypatch):
    RecordingBroker.objectives = []
    monkeypatch.setattr(fresh, "MultiplyBroker", RecordingBroker)
    return RecordingBroker.objectives


def to_review(world):
    world.submit()
    world.tick()
    world.approve_development()


def grant_reference(world):
    return json.loads((world.jobdir(world.job) / "execution.json").read_bytes())[
        "authorization_reference"]


def test_qa_failure_is_fixed_in_the_next_round_and_published(world, recording):
    world.qa_decision = ["FAIL", "PASS"]
    to_review(world)
    assert world.tick() == {"state": "awaiting_publication_approval"}
    job = world.jobdir(world.job)
    assert (job / "developer-fix-1.result.json").exists()
    assert not (job / "developer-fix-2.attempt.json").exists()
    # Round 1 claimed the same approval under its own record.
    ref = grant_reference(world)
    assert (world.grants / f"execution-{ref}-r1.json").exists()
    assert json.loads((world.grants / f"execution-result-{ref}-r1.json").read_bytes())[
        "status"] == "completed"
    # The publication is built from the round that passed.
    assert (job / "publisher-input/review-report.json").read_bytes() == (
        job / "reviewer-output-r1" / fresh.PROJECT / world.job["task_id"]
        / "review-report.json").read_bytes()
    world.approve_publication()
    assert world.tick()["state"] == "complete"
    assert len(world.pushes) == 1


def test_reviewer_changes_are_fixed_in_the_next_round(world, recording):
    world.review_decision = ["CHANGES_REQUESTED", "APPROVED"]
    to_review(world)
    assert world.tick() == {"state": "awaiting_publication_approval"}
    assert (world.jobdir(world.job) / "reviewer-fix-1.result.json").exists()


def test_fix_round_tells_developers_what_failed_and_shows_the_previous_attempt(world, recording):
    world.qa_decision = ["FAIL", "PASS"]
    to_review(world)
    world.tick()
    first, fix = recording[0], recording[-1]
    assert "Fix round" not in first
    assert "Fix round 1 of 3" in fix and "mock finding" in fix
    assert "=== calculator.py (previous attempt) ===" in fix and "def multiply" in fix
    request = json.loads((world.jobdir(world.job) / "execution-r1.json").read_bytes())
    assert request["fix_round"] == 1
    assert [item["id"] for item in request["items"]] == ["backend-r1"]
    assert request["scope"] == json.loads(
        (world.jobdir(world.job) / "execution.json").read_bytes())["scope"]


def test_after_three_rounds_the_owner_gets_one_plain_text(world, recording):
    world.review_decision = "CHANGES_REQUESTED"
    to_review(world)
    held = {"state": "held", "reason": "fix rounds exhausted; owner notified"}
    assert world.tick() == held
    assert len(recording) == 1 + MAX_FIX_ROUNDS
    stuck = [m for _, m in world.messages if m.startswith("I couldn't finish this one:")]
    assert len(stuck) == 1 and "T-0" not in stuck[0] and "Nothing was published" in stuck[0]
    assert world.tick() == held
    assert len([m for _, m in world.messages if m.startswith("I couldn't finish")]) == 1
    assert not world.pushes


def test_tasks_planned_before_multi_project_support_keep_the_old_behaviour(world, recording):
    original = world.plan

    def legacy_plan(job):
        return {k: v for k, v in original(job).items() if k != "specialists"}

    world.plan = legacy_plan
    world.review_decision = "CHANGES_REQUESTED"
    to_review(world)
    assert world.tick() == {"state": "held", "reason": "independent Reviewer did not approve"}
    assert not list(world.jobdir(world.job).glob("developer-fix-*"))
    assert len(recording) == 1


def test_qa_accepts_a_developer_changing_only_some_of_its_files(world, monkeypatch):
    monkeypatch.setattr(fresh, "MultiplyBroker", CalculatorOnlyBroker)
    to_review(world)
    assert world.tick() == {"state": "awaiting_publication_approval"}
    assert not list(world.jobdir(world.job).glob("developer-fix-*"))


def test_previous_files_are_never_read_through_a_symlink(tmp_path):
    final = tmp_path / "final"
    (final / "src").mkdir(parents=True)
    (final / "src/app.js").write_text("ok")
    secret = tmp_path / "secret.txt"
    secret.write_text("root-only")
    (final / "link.js").symlink_to(secret)
    (final / "linked").symlink_to(tmp_path)
    assert host.previous_file(final, "src/app.js", 100) == "ok"
    assert host.previous_file(final, "link.js", 100) is None
    assert host.previous_file(final, "linked/secret.txt", 100) is None
    assert host.previous_file(final, "../secret.txt", 100) is None
    assert host.previous_file(final, "src/app.js", 1) is None  # over the budget
    alias = tmp_path / "alias"
    alias.symlink_to(final)
    assert host.previous_file(alias, "src/app.js", 100) is None


def test_each_round_claims_the_approval_once_in_order(world, recording):
    world.qa_decision = ["FAIL", "PASS"]
    to_review(world)
    world.tick()
    ref = grant_reference(world)
    from developer_v1.owner_grants import ProtectedDevelopmentAuthority
    store = ProtectedDevelopmentAuthority(world.grants, environment="staging")
    expected = json.loads((world.grants / f"grant-{ref}.json").read_bytes())
    expected = {k: expected[k] for k in ("schema", "project", "task_id", "spec_sha256",
                                          "plan_sha256", "repository", "worktree_root",
                                          "scope", "specialists")}
    with pytest.raises(Denied, match="already consumed"):
        store.claim(ref, expected, run_sha256="a" * 64, fix_round=1)
    with pytest.raises(Denied, match="previous round"):
        store.claim(ref, expected, run_sha256="a" * 64, fix_round=3)
    with pytest.raises(Denied, match="invalid fix round"):
        store.claim(ref, expected, run_sha256="a" * 64, fix_round=MAX_FIX_ROUNDS + 1)
    assert os.path.exists(world.grants / f"execution-{ref}.json")
