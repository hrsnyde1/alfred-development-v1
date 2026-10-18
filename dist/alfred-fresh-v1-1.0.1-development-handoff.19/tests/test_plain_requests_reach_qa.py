"""handoff.19: a plain request (no file names) passes Independent QA's plan check, a QA
verdict reached before any model ran is recorded, and the owner can abandon a task."""

import json
from pathlib import Path

import pytest

from fresh_v1 import host
from fresh_v1.handoffs import Held
from ops import alfred_dev_ops as ops
from tests import test_fresh_v1 as fresh
from tests.test_fresh_v1 import world  # noqa: F401 (pytest fixture)

PLAIN = {**fresh.DRAFT, "scope": "Backend only. No new dependencies or other systems."}


def test_plain_request_names_its_approved_files_and_reaches_publication(world, monkeypatch):
    monkeypatch.setattr(fresh, "DRAFT", PLAIN)
    world.submit()
    world.tick()
    world.approve_development()
    assert world.tick() == {"state": "awaiting_publication_approval"}
    plan = json.loads((world.gateway.gateway_dir / "cto-plans"
                       / f"{fresh.PROJECT}-{world.job['task_id']}.json").read_bytes())
    assert plan["scope"].endswith("\nApproved files: calculator.py, test_calculator.py")
    # Independent QA checked every approved file against that text and passed.
    assert not list(world.jobdir(world.job).glob("developer-fix-*"))


def test_named_files_keep_the_plan_scope_unchanged(world):
    world.submit()
    world.tick()
    plan = json.loads((world.gateway.gateway_dir / "cto-plans"
                       / f"{fresh.PROJECT}-{world.job['task_id']}.json").read_bytes())
    assert "Approved files" not in plan["scope"]


class StubHost(host.Host):
    def __init__(self, result):
        self.result, self.p = result, {"worktree_root": "/nonexistent"}

    def share(self, path, users):
        pass

    def directory(self, path, user=None):
        pass

    def worker(self, job, stage, user, fix_round=0):
        return self.result


JOB = {"project": "demo-site", "task_id": "T-0002", "repository": "/nonexistent"}


def test_a_qa_verdict_without_model_evidence_is_recorded():
    failed = {"decision": "FAIL", "qa_model": None, "findings": [
        {"severity": "high", "requirement": "approved_scope", "detail": "Grant scope is outside CTO plan"}]}
    assert StubHost(failed).qa_dispatch(dict(JOB), Path("/tmp"), Path("/tmp")) == failed
    blocked = {"decision": "BLOCKED", "qa_model": None}
    assert StubHost(blocked).qa_dispatch(dict(JOB), Path("/tmp"), Path("/tmp")) == blocked


def test_a_pass_still_requires_model_evidence():
    with pytest.raises(Held, match="model evidence missing"):
        StubHost({"decision": "PASS", "qa_model": None}).qa_dispatch(
            dict(JOB), Path("/tmp"), Path("/tmp"))


# --- alfred-dev-ops abandon / resend -------------------------------------------------------

@pytest.fixture
def jobs(tmp_path, monkeypatch):
    root = tmp_path / "jobs"
    for name in ("demo-site/T-0002", "dev-v1-accept/T-0009", "demo-site/T-0001"):
        (root / name).mkdir(parents=True)
    (root / "dev-v1-accept/T-0009/complete.json").write_text("{}")
    (root / "demo-site/T-0001/plan.failure.json").write_text("{}")
    monkeypatch.setattr(ops, "JOBS", root)
    return root


def test_abandon_adds_one_record_and_changes_nothing_else(jobs):
    task = jobs / "demo-site/T-0002"
    (task / "qa.attempt.json").write_text('{"stage": "qa"}')
    before = {p.name: p.read_bytes() for p in task.iterdir()}
    assert ops.abandon("demo-site/T-0002", 5.0)["state"] == "abandoned"
    after = {p.name: p.read_bytes() for p in task.iterdir()}
    assert set(after) - set(before) == {"owner-abandoned.failure.json"}
    assert all(after[name] == data for name, data in before.items())
    record = json.loads(after["owner-abandoned.failure.json"])
    assert record["schema"] == "alfred.owner-abandoned/1" and record["task_id"] == "T-0002"
    with pytest.raises(ops.Refused, match="already stopped"):
        ops.abandon("demo-site/T-0002", 6.0)


@pytest.mark.parametrize("name,message", [
    ("dev-v1-accept/T-0009", "already completed"),
    ("demo-site/T-0001", "already stopped"),
    ("demo-site/T-0099", "not found"),
    ("T-0002", "project/task"),
    ("demo-site/../T-0002", "project/task"),
    ("Demo/T-0002", "project/task"),
])
def test_abandon_refuses(jobs, name, message):
    with pytest.raises(ops.Refused, match=message):
        ops.abandon(name, 5.0)


def test_status_names_tasks_by_project(jobs, monkeypatch):
    monkeypatch.setattr(ops, "PAUSE", jobs / "PAUSE")
    tasks = ops.status()["tasks"]
    assert {"demo-site/T-0002", "dev-v1-accept/T-0009", "demo-site/T-0001"} == set(tasks)
