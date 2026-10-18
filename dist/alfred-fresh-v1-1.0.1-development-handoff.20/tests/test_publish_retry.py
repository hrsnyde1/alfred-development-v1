"""handoff.20: after a definite Publisher error, only the owner authorizes another
publish attempt, under the same approval."""

import json
from unittest.mock import patch

import pytest

from draft_pr_publisher import worker as publisher
from fresh_v1 import host
from fresh_v1.protected import protected_json
from ops import alfred_dev_ops as ops
from tests.test_fresh_v1 import world  # noqa: F401 (pytest fixture)

HELD = {"state": "held",
        "reason": "Publisher success is unverified; publication investigation required"}


def failing_once(world):
    real = world.github.repository
    calls = []

    def repository(destination):
        calls.append(destination)
        if len(calls) == 1:
            raise publisher.PublicationError("github", "GitHub GET request failed: HTTP 404")
        return real(destination)

    world.github.repository = repository
    return calls


def approved_and_published_once(world):
    world.submit()
    world.tick()
    world.approve_development()
    world.tick()
    world.approve_publication()
    return world.tick()


def owner_republish(world, n):
    path = world.jobdir(world.job) / f"publisher-retry-{n}.json"
    path.write_text(json.dumps({"schema": "alfred.publisher-retry/1", "project": world.job["project"],
                                "task_id": world.job["task_id"], "n": n,
                                "authorized_by": "owner", "authorized_at": 1.0}))
    path.chmod(0o600)


def tick(world):
    trusted = lambda p: protected_json(p, trusted_uid=host.os.geteuid(),  # noqa: E731
                                       trusted_root=world.root)
    with patch.object(host, "protected_json", trusted):
        return world.tick()


def test_failed_publish_waits_for_the_owner_then_publishes_once(world):
    calls = failing_once(world)
    assert approved_and_published_once(world) == HELD
    job = world.jobdir(world.job)
    assert json.loads((job / "publisher.result.json").read_bytes())["status"] == "ERROR"
    # Nothing retries on its own.
    assert tick(world) == HELD and len(calls) == 1 and not world.pushes
    owner_republish(world, 1)
    result = tick(world)
    assert result["state"] == "complete", result
    assert len(world.pushes) == 1 and len(world.notifications) == 1
    assert (job / "publisher-retry-1.result.json").exists()
    # The completed task never publishes again.
    assert tick(world)["state"] == "complete" and len(world.pushes) == 1


def test_a_successful_publish_never_uses_a_retry(world):
    result = approved_and_published_once(world)
    assert result["state"] == "complete"
    assert not list(world.jobdir(world.job).glob("publisher-retry-*"))


# --- alfred-dev-ops republish -----------------------------------------------------------

@pytest.fixture
def jobs(tmp_path, monkeypatch):
    root = tmp_path / "jobs"
    task = root / "demo-site/T-0003"
    task.mkdir(parents=True)
    monkeypatch.setattr(ops, "JOBS", root)
    return task


def result(task, name, status):
    (task / name).write_text(json.dumps({"status": status}))


def test_republish_after_a_definite_error(jobs):
    result(jobs, "publisher.result.json", "ERROR")
    assert ops.republish("demo-site/T-0003", 5.0)["retry"] == 1
    record = json.loads((jobs / "publisher-retry-1.json").read_text())
    assert record["schema"] == "alfred.publisher-retry/1" and record["n"] == 1
    with pytest.raises(ops.Refused, match="already queued"):
        ops.republish("demo-site/T-0003", 6.0)
    result(jobs, "publisher-retry-1.result.json", "ERROR")
    assert ops.republish("demo-site/T-0003", 7.0)["retry"] == 2


@pytest.mark.parametrize("setup,message", [
    (lambda t: None, "no recorded publisher result"),
    (lambda t: result(t, "publisher.result.json", "PUBLISHED_DRAFT"), "definite error"),
    (lambda t: (t / "complete.json").write_text("{}"), "already completed"),
])
def test_republish_refuses(jobs, setup, message):
    setup(jobs)
    with pytest.raises(ops.Refused, match=message):
        ops.republish("demo-site/T-0003", 5.0)
    assert not list(jobs.glob("publisher-retry-*.json"))


def test_republish_is_bounded(jobs):
    result(jobs, "publisher.result.json", "ERROR")
    for n in range(1, ops.MAX_PUBLISH_RETRIES + 1):
        assert ops.republish("demo-site/T-0003", float(n))["retry"] == n
        result(jobs, f"publisher-retry-{n}.result.json", "ERROR")
    with pytest.raises(ops.Refused, match="already used"):
        ops.republish("demo-site/T-0003", 9.0)
