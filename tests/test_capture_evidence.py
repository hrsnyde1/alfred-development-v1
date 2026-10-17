"""Phase D evidence capture: read-only verdicts on disposable job directories."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
import capture_evidence as capture

DESTINATION = "hrsnyde1/alfred-dev-v1-acceptance"
TASK = "T-0004"
SECRET = "model narrative and token-like text that must never be printed"
RESULTS = {
    "plan": {
        "scope": ["calculator.py"],
        "baseline_revision": "a" * 40,
        "plan_sha256": "b" * 64,
        "repository": SECRET,
    },
    "development-challenge": {
        "state": "development_approval_requested",
        "challenge": "ref-1",
    },
    "developer": {"state": "ready_for_independent_qa"},
    "qa": {
        "decision": "PASS",
        "qa_model": {"provider": "codex"},
        "findings": [],
        "final_revision": "c" * 40,
        "detail": SECRET,
    },
    "reviewer": {"decision": "APPROVED", "findings": [], "correctness": "PASS"},
    "publication-plan": {"status": "PREPARED", "publication_plan_sha256": "d" * 64},
    "publication-challenge": {
        "state": "publication_approval_requested",
        "challenge": "pub-1",
    },
    "publisher": {
        "status": "PUBLISHED_DRAFT",
        "commit": "c" * 40,
        "destination": DESTINATION,
        "draft_pr_url": f"https://github.com/{DESTINATION}/pull/2",
    },
    "completion": {"status": "sent"},
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def host(tmp_path):
    jobs, grants, gateway = tmp_path / "jobs", tmp_path / "grants", tmp_path / "gateway"
    gateway.mkdir()
    policy = tmp_path / "policy.json"
    write(
        policy,
        {
            "project": "dev-v1-accept",
            "jobs": str(jobs),
            "grant_root": str(grants),
            "gateway_state": str(gateway),
            "destination": DESTINATION,
            "publisher_token": "/never/read",
        },
    )
    directory = jobs / "dev-v1-accept" / TASK
    write(directory / "job.json", {"project": "dev-v1-accept", "task_id": TASK})
    return policy, directory, grants, gateway


def complete_run(directory, grants, upto=None):
    for name, result in RESULTS.items():
        write(directory / f"{name}.attempt.json", {"stage": name})
        write(directory / f"{name}.result.json", result)
        if name == "development-challenge":
            write(grants / "grant-ref-1.json", {"state": "approved"})
        if name == upto:
            return
    write(directory / "complete.json", {"state": "complete"})


def report(policy, capsys, code=0):
    assert capture.main(["--task", TASK, "--policy", str(policy)]) == code
    out = capsys.readouterr().out
    assert SECRET not in out
    return json.loads(out)


def test_complete_task_passes_every_gate_without_printing_bodies(host, capsys):
    policy, directory, grants, _ = host
    complete_run(directory, grants)
    result = report(policy, capsys)
    assert result["overall"] == "PASS"
    assert all(g["verdict"] == "PASS" for g in result["gates"].values())
    assert result["job_identity_matches"] is True and result["paused"] is False
    publisher = next(s for s in result["stages"] if s["stage"] == "publisher")
    assert publisher["summary"]["draft_pr_url"].endswith("/pull/2")


def test_awaiting_development_approval_is_in_progress(host, capsys):
    policy, directory, grants, gateway = host
    complete_run(directory, grants, upto="development-challenge")
    (grants / "grant-ref-1.json").unlink()
    (gateway / "PAUSE").write_text("")
    result = report(policy, capsys)
    assert result["overall"] == "IN_PROGRESS" and result["paused"] is True
    assert result["gates"]["development_challenge_sent"]["verdict"] == "PASS"
    assert result["gates"]["development_grant_issued"]["verdict"] == "PENDING"


def test_attempt_without_result_is_held(host, capsys):
    policy, directory, grants, _ = host
    complete_run(directory, grants, upto="developer")
    write(directory / "qa.attempt.json", {"stage": "qa"})
    result = report(policy, capsys, code=2)
    assert result["overall"] == "HELD"
    assert result["gates"]["qa_pass_with_model"]["verdict"] == "HELD"


@pytest.mark.parametrize(
    "stage,change,gate",
    [
        ("qa", {"decision": "FAIL"}, "qa_pass_with_model"),
        ("qa", {"qa_model": None}, "qa_pass_with_model"),
        (
            "reviewer",
            {"findings": [{"severity": "low"}]},
            "reviewer_approved_no_findings",
        ),
        (
            "reviewer",
            {"decision": "CHANGES_REQUESTED"},
            "reviewer_approved_no_findings",
        ),
        (
            "publisher",
            {"draft_pr_url": "https://github.com/someone/else/pull/2"},
            "draft_pr_published",
        ),
        ("publisher", {"status": "PUBLICATION_UNVERIFIED"}, "draft_pr_published"),
        ("completion", {"status": "uncertain"}, "completion_text_sent"),
    ],
)
def test_wrong_stage_outcome_fails_its_gate(host, capsys, stage, change, gate):
    policy, directory, grants, _ = host
    complete_run(directory, grants)
    write(directory / f"{stage}.result.json", {**RESULTS[stage], **change})
    result = report(policy, capsys, code=2)
    assert result["overall"] == "FAIL"
    assert result["gates"][gate]["verdict"] == "FAIL"


def test_worker_failure_evidence_fails_with_category_only(host, capsys):
    policy, directory, grants, _ = host
    complete_run(directory, grants, upto="developer")
    write(directory / "qa.attempt.json", {"stage": "qa"})
    write(
        directory / "qa.failure.json", {"category": "worker_timeout", "detail": SECRET}
    )
    result = report(policy, capsys, code=2)
    assert result["gates"]["qa_pass_with_model"] == {
        "verdict": "FAIL",
        "detail": "qa failure: worker_timeout",
    }


def test_symlinked_stage_file_is_refused(host, capsys, tmp_path):
    policy, directory, grants, _ = host
    complete_run(directory, grants)
    target = tmp_path / "elsewhere.json"
    write(target, RESULTS["qa"])
    (directory / "qa.result.json").unlink()
    os.symlink(target, directory / "qa.result.json")
    assert capture.main(["--task", TASK, "--policy", str(policy)]) == 1
    assert json.loads(capsys.readouterr().out)["overall"] == "UNAVAILABLE"


@pytest.mark.parametrize("task", ["T-4", "../T-0004", "T-0004/x"])
def test_invalid_task_identity_is_refused(host, capsys, task):
    policy, *_ = host
    assert capture.main(["--task", task, "--policy", str(policy)]) == 1
    assert json.loads(capsys.readouterr().out)["overall"] == "UNAVAILABLE"


def test_capture_never_writes(host, capsys):
    policy, directory, grants, _ = host
    complete_run(directory, grants)
    root = policy.parent
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }
    report(policy, capsys)
    after = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }
    assert before == after


def test_recovered_qa_attempt_satisfies_the_qa_gate(host, capsys):
    # T-0005 shape: the original QA attempt held undispatched; qa-recovery-1 passed.
    policy, directory, grants, _ = host
    complete_run(directory, grants)
    (directory / "qa.result.json").unlink()
    write(directory / "qa-recovery-1.attempt.json", {"stage": "qa-recovery-1"})
    write(directory / "qa-recovery-1.result.json", RESULTS["qa"])
    result = report(policy, capsys)
    assert result["overall"] == "PASS"
    recovered = next(s for s in result["stages"] if s["stage"] == "qa-recovery-1")
    assert recovered["summary"]["qa_model_present"] is True


def test_recovered_qa_attempt_without_result_is_held(host, capsys):
    policy, directory, grants, _ = host
    complete_run(directory, grants, upto="developer")
    write(directory / "qa.attempt.json", {"stage": "qa"})
    write(directory / "qa-recovery-1.attempt.json", {"stage": "qa-recovery-1"})
    result = report(policy, capsys, code=2)
    assert result["gates"]["qa_pass_with_model"]["verdict"] == "HELD"


@pytest.fixture
def refusal_host(host, tmp_path):
    policy, directory, grants, gateway = host
    repository, completion = tmp_path / "repo", tmp_path / "completion"
    write(repository / ".dev/tasks/T-0002-done.md", {"task": "T-0002"})
    completion.mkdir()
    value = json.loads(policy.read_text())
    write(
        policy,
        {**value, "repository": str(repository), "completion_state": str(completion)},
    )
    complete_run(directory, grants)
    write(gateway / "journal.jsonl", {"event": "filed"})
    (gateway / "PAUSE").write_text("")
    return policy, repository, grants, gateway


def save_snapshot(policy, capsys, tmp_path):
    assert capture.main(["--snapshot", "--policy", str(policy)]) == 0
    out = capsys.readouterr().out
    assert SECRET not in out
    baseline = tmp_path / "before.json"
    baseline.write_text(out)
    return baseline


def since(policy, baseline, capsys, code):
    assert capture.main(["--since", str(baseline), "--policy", str(policy)]) == code
    out = capsys.readouterr().out
    assert SECRET not in out
    return json.loads(out)


def test_refusal_with_no_new_authority_is_unchanged(refusal_host, capsys, tmp_path):
    policy, _, grants, gateway = refusal_host
    baseline = save_snapshot(policy, capsys, tmp_path)
    # A refused request may log context, never authority.
    with open(gateway / "journal.jsonl", "a") as stream:
        stream.write('{"event": "rejected"}\n')
    write(grants / "request-route-r9.json", {"state": "refused"})
    result = since(policy, baseline, capsys, 0)
    assert result["overall"] == "UNCHANGED" and result["authority"] == {}
    assert result["context"]["gateway_state"]["changed"] == ["journal.jsonl"]
    assert result["context"]["grant_root"]["added"] == ["request-route-r9.json"]


@pytest.mark.parametrize(
    "mutate,section,kind,name",
    [
        (lambda r, g, s: write(r / ".dev/tasks/T-0004-x.md", {}), "tasks", "added",
         "T-0004-x.md"),
        (lambda r, g, s: write(g / "grant-ref-9.json", {}), "grants", "added",
         "grant-ref-9.json"),
        (lambda r, g, s: write(g / "publication-decision-p.json", {}), "grants",
         "added", "publication-decision-p.json"),
        (lambda r, g, s: write(s / "cto-plans/dev-v1-accept-T-0004.json", {}),
         "cto_plans", "added", "cto-plans/dev-v1-accept-T-0004.json"),
        (lambda r, g, s: (g / "grant-ref-1.json").unlink(), "grants", "removed",
         "grant-ref-1.json"),
    ],
)
def test_new_or_altered_authority_is_changed(
    refusal_host, capsys, tmp_path, mutate, section, kind, name
):
    policy, repository, grants, gateway = refusal_host
    baseline = save_snapshot(policy, capsys, tmp_path)
    mutate(repository, grants, gateway)
    result = since(policy, baseline, capsys, 2)
    assert result["overall"] == "CHANGED"
    assert result["authority"][section][kind] == [name]


def test_new_job_stage_is_changed(refusal_host, capsys, tmp_path):
    policy, *_ = refusal_host
    baseline = save_snapshot(policy, capsys, tmp_path)
    jobs = Path(json.loads(policy.read_text())["jobs"]) / "dev-v1-accept"
    write(jobs / "T-0005" / "job.json", {"task_id": "T-0005"})
    write(jobs / TASK / "qa.result.json", {"decision": "FAIL"})
    result = since(policy, baseline, capsys, 2)
    assert result["authority"]["jobs"]["added"] == ["T-0005/job.json"]
    assert result["authority"]["jobs"]["changed"] == [f"{TASK}/qa.result.json"]


def test_snapshot_symlink_is_recorded_not_followed(refusal_host, capsys, tmp_path):
    policy, _, grants, _ = refusal_host
    baseline = save_snapshot(policy, capsys, tmp_path)
    outside = tmp_path / "outside.json"
    write(outside, {"secret": SECRET})
    os.symlink(outside, grants / "grant-ref-7.json")
    result = since(policy, baseline, capsys, 2)
    assert result["authority"]["grants"]["added"] == ["grant-ref-7.json"]


def test_since_rejects_non_snapshot_baseline(refusal_host, capsys, tmp_path):
    policy, *_ = refusal_host
    bogus = tmp_path / "bogus.json"
    write(bogus, {"schema": "something-else"})
    assert capture.main(["--since", str(bogus), "--policy", str(policy)]) == 1
    assert json.loads(capsys.readouterr().out)["overall"] == "UNAVAILABLE"


def test_snapshot_and_since_never_write(refusal_host, capsys, tmp_path):
    policy, *_ = refusal_host
    baseline = save_snapshot(policy, capsys, tmp_path)
    state = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file() and not p.is_symlink()
    }
    since(policy, baseline, capsys, 0)
    assert capture.main(["--snapshot", "--policy", str(policy)]) == 0
    capsys.readouterr()
    after = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file() and not p.is_symlink()
    }
    assert state == after


def test_task_and_snapshot_modes_are_exclusive(host):
    policy, *_ = host
    with pytest.raises(SystemExit):
        capture.main(["--task", TASK, "--snapshot", "--policy", str(policy)])


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads mode-000 directories")
def test_unreadable_directory_is_refused_not_skipped(refusal_host, capsys, tmp_path):
    policy, _, grants, _ = refusal_host
    hidden = grants / "private"
    hidden.mkdir()
    hidden.chmod(0)
    try:
        assert capture.main(["--snapshot", "--policy", str(policy)]) == 1
        assert json.loads(capsys.readouterr().out)["overall"] == "UNAVAILABLE"
    finally:
        hidden.chmod(0o700)
