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
