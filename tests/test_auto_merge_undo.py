"""handoff.31 (owner-authorized 2026-10-18): after QA and the Reviewer pass, the pipeline
squash-merges the draft PR itself for delegated projects, and the owner can reply "undo"
to the final text within 24 hours to revert exactly that squash commit.

Real workers and real Git; GitHub is a local bare repository behind a fake API that
performs real squash merges, so every commit and tree below is genuine.
"""

import contextlib
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from developer_v1 import owner_grants
from developer_v1.router import Denied
from developer_v1.trusted_intake_development import IntakeRefused
from developer_v1.undo_approval import UNDO_MAX_AGE, UndoIssuer, undo_reply
from draft_pr_publisher import worker as publisher
from fresh_v1 import squads
from fresh_v1.handoffs import undo
from tests.test_draft_pr_publisher import FakeGitHub
from tests.test_fresh_v1 import OWNER, PROJECT, SIDE, World, event, git

IDENTITY = {"GIT_AUTHOR_NAME": "GitHub", "GIT_AUTHOR_EMAIL": "noreply@github.com",
            "GIT_COMMITTER_NAME": "GitHub", "GIT_COMMITTER_EMAIL": "noreply@github.com"}


class MergingGitHub(FakeGitHub):
    """The draft PR fake, plus ready-for-review, squash merge and commit readback."""

    def __init__(self, bare, destination):
        super().__init__(bare, destination)
        self.refuse_merge = None
        self.squashes = []

    def _git(self, *args):
        return subprocess.run(["git", "-C", str(self.bare), *args], check=True,
                              capture_output=True, env={**os.environ, **IDENTITY}
                              ).stdout.decode().strip()

    def _pr(self, number):
        [pr] = [p for p in self.pr_list if p["number"] == number]
        return pr

    def prs(self, destination, owner, branch, base):
        return [p for p in self.pr_list if p["head"]["ref"] == branch]

    def pull(self, destination, number):
        return json.loads(json.dumps(self._pr(number)))

    def mark_ready(self, node_id):
        for pr in self.pr_list:
            pr["draft"] = False

    def squash(self, destination, number, payload):
        if self.refuse_merge:
            raise publisher.PublicationError("github", "fixture refusal", self.refuse_merge)
        pr = self._pr(number)
        assert payload["merge_method"] == "squash" and payload["sha"] == pr["head"]["sha"]
        assert pr["draft"] is False, "GitHub never merges a draft"
        main = self._git("rev-parse", "refs/heads/main")
        head = pr["head"]["sha"]
        if self._git("merge-base", main, head) == main:
            tree = self._git("rev-parse", f"{head}^{{tree}}")
        else:
            tree = self._git("merge-tree", "--write-tree", main, head).splitlines()[0]
        commit = self._git("commit-tree", tree, "-p", main, "-m", payload["commit_title"])
        self._git("update-ref", "refs/heads/main", commit, main)
        self.squashes.append(payload)
        pr.update(merged=True, state="closed", draft=False, merged_at="2026-10-18T21:00:00Z",
                  merge_commit_sha=commit, merged_by={"login": "alfredpublish"})
        return {"sha": commit, "merged": True}

    def commit(self, destination, sha):
        parents = self._git("rev-list", "--parents", "-n", "1", sha).split()[1:]
        return {"sha": sha, "tree": {"sha": self._git("rev-parse", f"{sha}^{{tree}}")},
                "parents": [{"sha": p} for p in parents]}

    def create_revert_pr(self, destination, payload):
        number = len(self.pr_list) + 1
        record = {"number": number, "draft": False, "state": "open", "merged": False,
                  "html_url": f"https://github.com/{destination}/pull/{number}",
                  "body": payload["body"],
                  "head": {"sha": self.ref(destination, payload["head"])["object"]["sha"],
                           "ref": payload["head"], "repo": {"full_name": destination}},
                  "base": {"ref": payload["base"], "repo": {"full_name": destination},
                           "sha": self.ref(destination, payload["base"])["object"]["sha"]}}
        self.pr_list.append(record)
        return record


class MergeWorld(World):
    def __init__(self, root):
        super().__init__(root)
        self.github = MergingGitHub(self.bare, self.p["destination"])
        self.undo_issuer = UndoIssuer(self.grants, owner_sender_id=OWNER, sidecar_uid=SIDE)
        self.gate.undo_issuer = self.undo_issuer

    def worker(self, job, stage, user, fix_round=0):
        real_merge, real_revert = publisher.merge, publisher.revert
        fixture = {"github": self.github, "trusted_uid": os.geteuid(), "trusted_root": self.root}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(
                publisher, "merge", lambda **kw: real_merge(**kw, **fixture)))
            stack.enter_context(patch.object(
                publisher, "revert",
                lambda **kw: real_revert(**kw, **fixture, _fixture_remote=str(self.bare))))
            return super().worker(job, stage, user, fix_round)

    def main_head(self):
        return git(self.bare, "rev-parse", "refs/heads/main")

    def commit_on_main(self, path, content, message="owner's later change"):
        """Another change lands on GitHub's main (for example the owner's own merge)."""
        work = self.root / f"clone-{len(os.listdir(self.root))}"
        git(self.root, "clone", "-q", "-b", "main", self.bare, work)
        git(work, "config", "user.name", "Owner")
        git(work, "config", "user.email", "owner@example.invalid")
        (work / path).write_text(content)
        git(work, "add", path)
        git(work, "commit", "-qm", message)
        git(work, "push", "-q", "origin", "HEAD:main")
        return git(work, "rev-parse", "HEAD")

    def reply(self, text, identifier="mock-undo-reply", target="mock-receipt", **changes):
        return self.gate.dispatch(
            {"op": "observe", "event": event(identifier, text, target, **changes)}, SIDE)

    def undo_tick(self):
        return undo(self.jobdir(self.job), self.job, self)


@pytest.fixture
def world(tmp_path):
    previous = os.umask(0o077)
    try:
        yield MergeWorld(tmp_path)
    finally:
        os.umask(previous)


def delegate(world, merge="delegated", publication="delegated"):
    policy = {"schema": owner_grants.DELEGATION_SCHEMA,
              "development_approval": {"enabled": True, "projects": [PROJECT]},
              "publication_approval": publication}
    if merge is not None:
        policy["merge_approval"] = merge
    path = Path(world.root) / "delegation.json"
    path.write_text(json.dumps(policy))
    path.chmod(0o644)
    world.publication_issuer.delegation_policy = path
    world.publication_issuer.policy_owner = os.geteuid()
    return path


def run_to_completion(world):
    world.submit()
    assert world.tick() == {"state": "awaiting_development_approval"}
    world.approve_development()
    result = world.tick()
    assert result["state"] == "complete", result
    return result


def records(world, name):
    return json.loads((world.jobdir(world.job) / name).read_bytes())


def test_one_yes_merges_into_main_and_the_text_offers_undo(world):
    delegate(world)
    baseline = world.main_head()
    result = run_to_completion(world)
    merged = records(world, "merge.result.json")
    assert merged["status"] == "MERGED" and result["merge_commit"] == merged["merge_commit"]
    # One squash commit on main, on top of the tested baseline, with exactly the approved files.
    head = world.main_head()
    assert head == merged["merge_commit"] and merged["merge_parent"] == baseline
    assert git(world.bare, "rev-list", "--parents", "-n", "1", head).split() == [head, baseline]
    assert (git(world.bare, "rev-parse", f"{head}^{{tree}}")
            == git(world.bare, "rev-parse", f"{merged['final_revision']}^{{tree}}"))
    assert len(world.github.squashes) == 1
    # The merge record says why it was allowed and never claims an owner reply.
    authorization = records(world, "publication/merge-authorization.json")
    assert authorization["owner_event_id"].startswith("delegated-merge-")
    [decision] = Path(world.p["grant_root"]).glob("merge-delegation-*.json")
    assert json.loads(decision.read_text())["policy"]["merge_approval"] == "delegated"
    # The owner's one text: done, merged, the commit link, and how to undo it.
    [text] = world.notifications
    assert "merged into main" in text and merged["commit_url"] in text
    assert "Reply undo within 24 hours to take it back." in text
    assert "ready for you to push" not in text
    assert result["undo"] == "undo_window_open"
    # Nothing repeats on later ticks.
    assert world.tick()["state"] == "complete"
    assert len(world.github.squashes) == len(world.notifications) == 1


def test_without_merge_delegation_the_owner_merges(world):
    delegate(world, merge=None)
    result = run_to_completion(world)
    assert records(world, "merge-decision.result.json") == {"merge": "owner"}
    assert not (world.jobdir(world.job) / "merge.attempt.json").exists()
    assert "merge_commit" not in result and not world.github.squashes
    assert "ready for you to push" in world.notifications[0]


def test_merge_needs_the_draft_pr_delegated_too(world):
    delegate(world, merge="delegated", publication="owner")
    world.submit()
    world.tick()
    world.approve_development()
    assert world.tick() == {"state": "awaiting_publication_approval"}
    world.approve_publication()
    assert world.tick()["state"] == "complete"
    assert records(world, "merge-decision.result.json") == {"merge": "owner"}
    assert not world.github.squashes


def test_main_moved_since_testing_is_not_merged_and_the_owner_is_told(world):
    delegate(world)
    real_merge = world.merge

    def merge_after_someone_else_did(job):
        world.commit_on_main("NOTES.md", "unrelated\n")
        return real_merge(job)

    world.merge = merge_after_someone_else_did
    run_to_completion(world)
    merged = records(world, "merge.result.json")
    assert merged["status"] == "NOT_MERGED" and merged["reason"] == "main_moved"
    assert not world.github.squashes
    [text] = world.notifications
    assert "couldn't merge it on my own" in text and "ready for you to merge" in text
    assert "undo" not in text.lower()
    assert not (world.jobdir(world.job) / "undo-window.result.json").exists()


def test_github_refusing_the_merge_merges_nothing(world):
    delegate(world)
    world.github.refuse_merge = 405
    before = world.main_head()
    run_to_completion(world)
    assert records(world, "merge.result.json")["reason"] == "github_refused"
    assert world.main_head() == before
    assert "couldn't merge it on my own" in world.notifications[0]


def test_no_answer_from_github_is_never_assumed(world):
    delegate(world)
    world.github.refuse_merge = None
    world.github.squash = lambda *a: (_ for _ in ()).throw(
        publisher.PublicationError("github", "timeout"))
    world.submit()
    world.tick()
    world.approve_development()
    assert world.tick()["state"] == "held"
    assert not world.notifications
    assert world.tick()["state"] == "held"  # held for good; never retried on its own


def test_undo_reverts_exactly_the_squash_commit_once(world):
    delegate(world)
    baseline = world.main_head()
    run_to_completion(world)
    merged = records(world, "merge.result.json")
    assert world.undo_tick() is None  # nothing to do before the owner replies
    assert world.reply("Undo")["state"] == "undo_requested"
    outcome = world.undo_tick()
    assert outcome["state"] == "undone"
    reverted = records(world, "undo.result.json")
    head = world.main_head()
    assert reverted["status"] == "REVERTED" and reverted["revert_commit"] == head
    assert git(world.bare, "rev-list", "--parents", "-n", "1", head).split() == [head, merged["merge_commit"]]
    assert (git(world.bare, "rev-parse", f"{head}^{{tree}}")
            == git(world.bare, "rev-parse", f"{baseline}^{{tree}}"))
    assert world.messages[-1][1].startswith("Undone.") and reverted["commit_url"] in world.messages[-1][1]
    # The owner's reply is durable evidence; the revert authorization names it.
    authorization = records(world, "publication/undo-authorization.json")
    assert authorization["owner_event_id"] == "mock-undo-reply"
    assert authorization["merge_commit"] == merged["merge_commit"]
    # A second "undo" changes nothing and sends nothing.
    sent = len(world.messages)
    assert world.reply("undo", identifier="mock-undo-again")["state"] == "undo_already_requested"
    assert world.undo_tick() is None
    assert len(world.messages) == sent and world.main_head() == head


def test_undo_keeps_later_unrelated_changes(world):
    delegate(world)
    run_to_completion(world)
    later = world.commit_on_main("NOTES.md", "the owner's own note\n")
    world.reply("undo")
    assert world.undo_tick()["state"] == "undone"
    head = world.main_head()
    assert git(world.bare, "rev-list", "--parents", "-n", "1", head).split() == [head, later]
    assert git(world.bare, "show", f"{head}:NOTES.md") == "the owner's own note"
    assert "multiply" not in git(world.bare, "show", f"{head}:calculator.py")
    changed = git(world.bare, "diff", "--name-only", later, head).split()
    assert set(changed) <= {"calculator.py", "test_calculator.py"}


def test_undo_that_would_clash_with_newer_work_changes_nothing(world):
    delegate(world)
    run_to_completion(world)
    calculator = git(world.bare, "show", "refs/heads/main:calculator.py")
    later = world.commit_on_main(
        "calculator.py", calculator.replace("return a * b", "return int(a) * int(b)"))
    world.reply("undo")
    assert world.undo_tick() == {"state": "undo_refused", "reason": "conflict",
                                 "revert_commit": None}
    assert world.main_head() == later
    text = world.messages[-1][1]
    assert text.startswith("I couldn't undo that change") and "Nothing was changed." in text
    assert len(world.github.squashes) == 1


@pytest.mark.parametrize("change", [
    {"sender": {"id": "someone-else"}},
    {"space": {"id": "another-dm", "type": "dm"}},
    {"nativeIsForward": True},
])
def test_undo_needs_the_owners_own_native_reply(world, change):
    delegate(world)
    run_to_completion(world)
    with pytest.raises(IntakeRefused, match="undo_refused"):
        world.reply("undo", **change)
    assert not list(Path(world.p["grant_root"]).glob("undo-decision-*.json"))
    assert world.undo_tick() is None


def test_other_replies_and_other_messages_are_ordinary_chat(world):
    delegate(world)
    run_to_completion(world)
    issuer = world.undo_issuer
    assert issuer.observe(event("m1", "thanks!", "mock-receipt"), peer_uid=SIDE) == {"state": "not_undo"}
    assert issuer.observe(event("m2", "undo", "some-other-message"), peer_uid=SIDE) == {"state": "not_undo"}
    assert issuer.observe(event("m3", "undo", None), peer_uid=SIDE) == {"state": "not_undo"}
    assert not list(Path(world.p["grant_root"]).glob("undo-decision-*.json"))


def test_undo_after_24_hours_is_refused(world):
    delegate(world)
    run_to_completion(world)
    window = records(world, "undo-window.result.json")
    issuer = world.undo_issuer
    issuer.clock = lambda: window["expires_at"] + 1
    with pytest.raises(Denied):
        issuer.observe(event("late", "undo", "mock-receipt"), peer_uid=SIDE)
    assert world.undo_tick() is None
    assert UNDO_MAX_AGE == 24 * 3600


def test_uncertain_completion_text_has_no_undo_window(world):
    delegate(world)
    world.transport_receipt = None
    world.submit()
    world.tick()
    world.approve_development()
    assert world.tick()["state"] == "held"  # completion delivery requires reconciliation
    assert not (world.jobdir(world.job) / "undo-window.result.json").exists()
    assert world.undo_issuer.observe(event("u", "undo", "mock-receipt"), peer_uid=SIDE) == {
        "state": "not_undo"}
    assert world.undo_tick() is None


def test_only_root_can_open_a_window_or_prepare_an_undo(world):
    with pytest.raises(Denied):
        world.undo_issuer.open({}, peer_uid=SIDE)
    with pytest.raises(Denied):
        world.undo_issuer.prepare("0" * 32, peer_uid=SIDE)


@pytest.mark.parametrize("text,accepted", [
    ("undo", True), ("Undo.", True), ("undo it!", True), ("please undo", True),
    ("take it back", True), ("don't undo", False), ("undo the header and the footer", False),
])
def test_undo_wording(text, accepted):
    assert undo_reply(text) is accepted


@pytest.mark.parametrize("merge,permits", [(None, False), ("owner", False), ("delegated", True)])
def test_the_policy_merge_modes(tmp_path, merge, permits):
    value = {"schema": owner_grants.DELEGATION_SCHEMA,
             "development_approval": {"enabled": True, "projects": ["x-site"]},
             "publication_approval": "delegated"}
    if merge is not None:
        value["merge_approval"] = merge
    path = tmp_path / "delegation.json"
    path.write_text(json.dumps(value))
    path.chmod(0o644)
    policy = owner_grants.load_delegation_policy(path, owner_uid=os.geteuid())
    assert owner_grants.merge_delegation_permits(policy, "x-site") is permits
    assert not owner_grants.merge_delegation_permits(policy, "other")
    path.write_text(json.dumps({**value, "merge_approval": "always"}))
    with pytest.raises(Denied):
        owner_grants.load_delegation_policy(path, owner_uid=os.geteuid())


def test_the_shipped_policy_delegates_merging_for_the_same_projects():
    root = Path(__file__).resolve().parents[1]
    shipped = json.loads((root / "development_handoff31/delegation.json").read_bytes())
    before = json.loads((root / "development_handoff29/delegation.json").read_bytes())
    assert shipped == {**before, "merge_approval": "delegated"}


def test_the_squad_chat_announces_the_merge_and_the_undo(world, tmp_path):
    delegate(world)
    run_to_completion(world)
    world.reply("undo")
    world.undo_tick()
    texts = [e["text"] for e in squads.events(world.jobdir(world.job), tmp_path, 0)]
    merged, undone = records(world, "merge.result.json"), records(world, "undo.result.json")
    assert f"🔀 {PROJECT} {world.job['task_id']} merged into main: {merged['commit_url']}" in texts
    assert any(t.startswith("↩️") and undone["commit_url"] in t for t in texts)
