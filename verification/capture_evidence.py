"""Read-only Phase D evidence summary for one fresh V1 task. Never writes or sends.

Run as root on the host after (or during) a live acceptance task:

    /usr/bin/python3 -I -B verification/capture_evidence.py --task T-0004

It reads the existing handoff job directory and grant store named by the protected
fresh V1 policy and prints one JSON report: every stage file in pipeline order with
its SHA-256, a small allowlist of status fields, and a PASS / PENDING / HELD / FAIL
verdict per acceptance gate. File bodies, model output, tokens and message text are
never printed. Paste the output back for review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

POLICY = Path("/etc/alfred-fresh-v1/policy.json")
MAX_BYTES = 1024 * 1024
TASK = re.compile(r"T-[0-9]{4}\Z")
PROJECT = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
# The literal chain in fresh_v1/handoffs.py:advance, in order.
STAGES = (
    "plan",
    "plan-recovery-1",
    "development-challenge",
    "developer",
    "qa",
    "reviewer",
    "publication-plan",
    "publication-challenge",
    "publisher",
    "completion",
)
# Status-only fields; anything else in a result (plans, model text) is not printed.
SUMMARY_FIELDS = {
    "plan": ("scope", "baseline_revision", "plan_sha256"),
    "plan-recovery-1": ("scope", "baseline_revision", "plan_sha256"),
    "development-challenge": ("state", "challenge"),
    "developer": ("state",),
    "qa": ("decision", "final_revision", "next_authorized_action"),
    "reviewer": ("decision", "correctness", "next_authorized_stage"),
    "publication-plan": ("status", "publication_plan_sha256"),
    "publication-challenge": ("state", "challenge"),
    "publisher": ("status", "draft_pr_url", "commit", "destination", "next_stage"),
    "completion": ("status",),
}


class Unsafe(ValueError):
    pass


def read(path: Path) -> bytes | None:
    """Bounded, no-follow read of a regular single-link file; None if absent."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Unsafe(f"unreadable: {path.name}: errno={exc.errno}") from None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Unsafe(f"not a regular single-link file: {path.name}")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise Unsafe(f"oversize: {path.name}")
    return raw


def load(raw: bytes | None) -> dict | None:
    if raw is None:
        return None
    value = json.loads(raw)
    if type(value) is not dict:
        raise Unsafe("JSON object required")
    return value


def stage_record(directory: Path, name: str) -> dict:
    record = {"stage": name}
    for kind in ("attempt", "result", "failure"):
        raw = read(directory / f"{name}.{kind}.json")
        record[kind] = raw is not None
        if raw is not None:
            record[kind + "_sha256"] = hashlib.sha256(raw).hexdigest()
        if kind == "result" and raw is not None:
            result = load(raw)
            record["summary"] = {
                key: result[key] for key in SUMMARY_FIELDS[name] if key in result
            }
            if name == "qa":
                record["summary"]["qa_model_present"] = (
                    result.get("qa_model") is not None
                )
            if name in ("qa", "reviewer") and isinstance(result.get("findings"), list):
                record["summary"]["findings"] = len(result["findings"])
        if kind == "failure" and raw is not None:
            failure = load(raw)
            record["failure_category"] = failure.get("category")
    record["held"] = record["attempt"] and not record["result"]
    return record


def gate(ok, *, pending=False, held=False, detail=None):
    state = "PASS" if ok else "HELD" if held else "PENDING" if pending else "FAIL"
    return {"verdict": state, **({"detail": detail} if detail else {})}


def evaluate(records: dict, complete: dict | None, grant: bool, destination: str):
    def result(name):
        r = records[name]
        return r.get("summary") if r["result"] else None

    def judged(name, check, detail):
        r = records[name]
        if r["failure"]:
            return gate(False, detail=f"{name} failure: {r.get('failure_category')}")
        if r["held"]:
            return gate(False, held=True, detail=f"{name} attempt without result")
        summary = result(name)
        if summary is None:
            return gate(False, pending=True)
        return gate(check(summary), detail=None if check(summary) else detail)

    plan_stage = "plan-recovery-1" if records["plan-recovery-1"]["attempt"] else "plan"
    pr = re.compile(
        r"https://github\.com/" + re.escape(destination) + r"/pull/[0-9]+\Z"
    )
    gates = {
        "cto_plan": judged(plan_stage, lambda s: bool(s.get("scope")), "empty scope"),
        "development_challenge_sent": judged(
            "development-challenge",
            lambda s: bool(s.get("challenge")),
            "no challenge reference",
        ),
        "development_grant_issued": gate(grant, pending=True),
        "developer_ready_for_qa": judged(
            "developer",
            lambda s: s.get("state") == "ready_for_independent_qa",
            "developer not complete",
        ),
        "qa_pass_with_model": judged(
            "qa",
            lambda s: s.get("decision") == "PASS" and s.get("qa_model_present"),
            "QA did not pass",
        ),
        "reviewer_approved_no_findings": judged(
            "reviewer",
            lambda s: s.get("decision") == "APPROVED" and s.get("findings") == 0,
            "reviewer not approved or findings present",
        ),
        "publication_plan_sealed": judged(
            "publication-plan",
            lambda s: bool(s.get("publication_plan_sha256")),
            "no seal",
        ),
        "publication_challenge_sent": judged(
            "publication-challenge",
            lambda s: bool(s.get("challenge")),
            "no challenge reference",
        ),
        "draft_pr_published": judged(
            "publisher",
            lambda s: (
                s.get("status") == "PUBLISHED_DRAFT"
                and pr.fullmatch(str(s.get("draft_pr_url"))) is not None
            ),
            "not a draft PR on the policy destination",
        ),
        "completion_text_sent": judged(
            "completion",
            lambda s: s.get("status") in {"sent", "already_sent"},
            "completion not sent",
        ),
        "task_complete": gate(
            complete is not None and complete.get("state") == "complete", pending=True
        ),
    }
    return gates


def capture(policy_path: Path, project: str | None, task: str) -> dict:
    policy = load(read(policy_path))
    if policy is None:
        raise Unsafe("policy missing")
    project = project or policy["project"]
    if not PROJECT.fullmatch(project) or not TASK.fullmatch(task):
        raise Unsafe("invalid project or task identity")
    directory = Path(policy["jobs"]) / project / task
    if not directory.is_dir() or directory.is_symlink():
        raise Unsafe("job directory missing")
    job = load(read(directory / "job.json"))
    records = {name: stage_record(directory, name) for name in STAGES}
    challenge = (records["development-challenge"].get("summary") or {}).get("challenge")
    grant = False
    if isinstance(challenge, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", challenge):
        grant = read(Path(policy["grant_root"]) / f"grant-{challenge}.json") is not None
    complete = load(read(directory / "complete.json"))
    gates = evaluate(records, complete, grant, policy["destination"])
    verdicts = [g["verdict"] for g in gates.values()]
    overall = (
        "FAIL"
        if "FAIL" in verdicts
        else "HELD"
        if "HELD" in verdicts
        else "PASS"
        if set(verdicts) == {"PASS"}
        else "IN_PROGRESS"
    )
    return {
        "schema": "alfred.phase-d-evidence/1",
        "project": project,
        "task_id": task,
        "job_identity_matches": job is not None
        and (job.get("project"), job.get("task_id")) == (project, task),
        "paused": any(
            (Path(policy["gateway_state"]) / name).exists()
            for name in ("PAUSE", "STOP")
        ),
        "stages": [records[name] for name in STAGES],
        "gates": gates,
        "overall": overall,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", required=True)
    parser.add_argument("--project")
    parser.add_argument("--policy", type=Path, default=POLICY)
    args = parser.parse_args(argv)
    try:
        report = capture(args.policy, args.project, args.task)
    except (Unsafe, OSError, ValueError, KeyError) as exc:
        # Never echo file bodies; the exception text names only a path or check.
        print(
            json.dumps(
                {"overall": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["overall"] in {"PASS", "IN_PROGRESS"} else 2


if __name__ == "__main__":
    sys.exit(main())
