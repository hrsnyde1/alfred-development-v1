"""handoff.44: the Development board feed reads each task's records into its workflow."""

import json
import os

from fresh_v1 import dev_board as b

T0 = 1_800_000_000


def record(directory, name, body, at):
    path = directory / name
    path.write_text(json.dumps(body))
    os.utime(path, (at, at))


def task(tmp_path, steps, task_id="T-0042", specialists=("frontend",)):
    directory = tmp_path / "jobs" / "demo-site" / task_id
    directory.mkdir(parents=True)
    record(directory, "context.json", {"specialists": list(specialists), "scope": ["ui"]}, T0)
    record(directory, "execution.json",
           {"items": [{"objective": "Add a dark mode toggle\nCanonical specification ..."}]}, T0)
    for i, (name, body) in enumerate(steps, start=1):
        record(directory, name, body, T0 + i * 60)
    return directory


def lane_of(tmp_path, steps, **kw):
    return b.workflow(task(tmp_path, steps, **kw), tmp_path / "reports")


def test_a_new_task_waits_for_the_owners_yes(tmp_path):
    w = lane_of(tmp_path, [("plan.result.json", {}),
                           ("development-challenge.result.json",
                            {"state": "awaiting_native_owner_reply"})])
    assert w["lane"] == "waiting" and w["laneLabel"] == "Waiting for you"
    assert w["title"] == "Add a dark mode toggle"
    states = {s["key"]: s["state"] for s in w["steps"]}
    assert states == {"request": "done", "plan": "done", "approval": "active", "build": "pending",
                      "qa": "pending", "review": "pending", "publish": "pending", "merge": "pending"}
    assert w["squads"] == ["web-app"] and w["specialists"][0]["title"] == "Frontend"


def test_building_then_qa_then_review(tmp_path):
    w = lane_of(tmp_path, [("plan.result.json", {}), ("developer.attempt.json", {})])
    assert w["lane"] == "building"
    assert w["steps"][2]["state"] == "done"  # the yes came: developers started
    w = lane_of(tmp_path / "2", [("plan.result.json", {}), ("developer.attempt.json", {}),
                                 ("developer.result.json", {})])
    assert w["lane"] == "qa"
    w = lane_of(tmp_path / "3", [("plan.result.json", {}), ("developer.attempt.json", {}),
                                 ("developer.result.json", {}), ("qa.result.json", {"decision": "PASS"})])
    assert w["lane"] == "review"


def test_a_failed_check_and_a_fix_round(tmp_path):
    findings = {"decision": "FAIL", "findings": [
        {"severity": "error", "requirement": "AC1", "detail": "toggle missing"},
        {"severity": "info", "requirement": "x", "detail": "ignored"}]}
    base = [("plan.result.json", {}), ("developer.attempt.json", {}),
            ("developer.result.json", {}), ("qa.result.json", findings)]
    w = lane_of(tmp_path, base)
    assert w["lane"] == "fixing"
    assert w["steps"][4]["state"] == "failed" and "toggle missing" in w["steps"][4]["detail"]
    w = lane_of(tmp_path / "2", base + [("developer-fix-1.attempt.json", {})])
    assert w["lane"] == "fixing" and w["fixRounds"] == 1
    assert w["steps"][3]["detail"] == "Fix round 1"


def test_merged_with_links_and_then_undone(tmp_path):
    steps = [("plan.result.json", {}), ("developer.attempt.json", {}),
             ("developer.result.json", {}), ("qa.result.json", {"decision": "PASS"}),
             ("reviewer.result.json", {"decision": "APPROVED"}),
             ("publication-challenge.result.json", {"state": "publication_delegated"}),
             ("publisher.result.json", {"status": "PUBLISHED_DRAFT", "draft_pr_url": "https://github.com/x/y/pull/3"}),
             ("merge.result.json", {"status": "MERGED", "commit_url": "https://github.com/x/y/commit/abc"})]
    w = lane_of(tmp_path, steps)
    assert w["lane"] == "done"
    assert w["links"] == {"pr": "https://github.com/x/y/pull/3", "commit": "https://github.com/x/y/commit/abc"}
    assert all(s["state"] == "done" for s in w["steps"])
    w = lane_of(tmp_path / "2", steps + [("undo.result.json", {"status": "REVERTED", "commit_url": "https://github.com/x/y/commit/def"})])
    assert w["lane"] == "undone" and w["links"]["undo"].endswith("def")


def test_stopped_tasks(tmp_path):
    w = lane_of(tmp_path, [("plan.result.json", {}), ("owner-abandoned.failure.json", {})])
    assert w["lane"] == "stopped" and w["stopped"]["reason"] == "You stopped it"
    w = lane_of(tmp_path / "2", [("plan.result.json", {}), ("fix-rounds-exhausted.result.json", {})])
    assert w["lane"] == "stopped" and "fix rounds" in w["stopped"]["reason"]


def test_snapshot_never_leaks_records_and_survives_a_bad_task(tmp_path, monkeypatch):
    task(tmp_path, [("plan.result.json", {"plan_raw": "SECRET PLAN", "phrase": "yes-1234"})])
    (tmp_path / "jobs" / "demo-site" / "T-0043").mkdir()
    board = b.snapshot(tmp_path / "jobs", tmp_path / "reports", now=T0)
    raw = json.dumps(board)
    assert "SECRET PLAN" not in raw and "yes-1234" not in raw
    assert {t["taskId"] for t in board["tasks"]} == {"T-0042", "T-0043"}
    assert board["schema"] == "alfred.dev-board/1" and board["skipped"] == 0
    real = b.workflow
    monkeypatch.setattr(b, "workflow", lambda d, r: real(d, r) if d.name == "T-0042" else 1 / 0)
    board = b.snapshot(tmp_path / "jobs", tmp_path / "reports", now=T0)
    assert [t["taskId"] for t in board["tasks"]] == ["T-0042"] and board["skipped"] == 1


def test_write_is_readable_by_the_reader_group_only(tmp_path):
    out = tmp_path / "workflows.json"
    b.write({"tasks": []}, out, group=None)
    assert out.stat().st_mode & 0o777 == 0o600
    assert json.loads(out.read_text()) == {"tasks": []}
