"""The Development board feed for Alfred OS (handoff.44).

Every task's workflow, from the request to the merge, as Alfred OS's Development board
shows it. The task records under /var/lib/alfred-v1-handoffs are root-only (0600), so a
sandboxed root oneshot (alfred-dev-board.timer, every 20 seconds) reads them, the same
way squads.py does for the Telegram chats, and writes one summary file the development
bridge (user alfred) may read: /var/lib/alfred-dev-board/workflows.json, 0640 root:alfred.

What leaves the records, per task: the project and task id, the goal's first line, the
specialists and squads, one entry per pipeline step (state, time, a short detail such as
QA's top findings), the fix rounds, and the draft PR, merge and undo links. Never: plans,
approval phrases or challenges, grants, worktree paths, model credentials, diffs.
"""

from __future__ import annotations

import grp
import json
import os
import sys
import time
from pathlib import Path

from fresh_v1.squads import JOBS, REPORTS, TEAM, TITLES, _findings, _json, _objective, _short

OUT = Path("/var/lib/alfred-dev-board/workflows.json")
READER_GROUP = "alfred"
MAX_TASKS = 200
SCHEMA = "alfred.dev-board/1"

# The pipeline's steps, in order. Fix rounds and retries fold into these.
STEPS = (
    ("request", "Request"),
    ("plan", "CTO plan"),
    ("approval", "Your yes"),
    ("build", "Developers"),
    ("qa", "QA"),
    ("review", "Review"),
    ("publish", "Draft PR"),
    ("merge", "Merged"),
)
# Where a task sits now; the board's columns.
LANES = {
    "planning": "Planning",
    "waiting": "Waiting for you",
    "building": "Building",
    "qa": "QA",
    "review": "Review",
    "fixing": "Fixing",
    "shipping": "Shipping",
    "done": "Done",
    "undone": "Undone",
    "stopped": "Stopped",
}


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _round(stage: str) -> int:
    tail = stage.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def workflow(directory: Path, reports: Path = REPORTS) -> dict:
    """One task's workflow, from its records."""
    context = _json(directory / "context.json") or {}
    specialists = [s for s in context.get("specialists") or [] if s in TEAM]
    squads = []
    for s in specialists:
        if TEAM[s][1] not in squads:
            squads.append(TEAM[s][1])
    steps = {key: {"key": key, "label": label, "state": "pending", "at": None, "detail": None}
             for key, label in STEPS}

    def mark(key, state, at, detail=None):
        steps[key].update(state=state, at=at, detail=_short(detail, 300) if detail else None)

    started = _mtime(directory / "context.json") or _mtime(directory)
    mark("request", "done", started)

    # Results in the order they happened; later rounds overwrite earlier ones.
    results = sorted(directory.glob("*.result.json"), key=lambda p: p.stat().st_mtime)
    fix_rounds, links = 0, {}
    last_check = None  # "qa" or "review": which check failed most recently
    for path in results:
        stage = path.name[: -len(".result.json")]
        result = _json(path)
        if not isinstance(result, dict):
            continue
        at = path.stat().st_mtime
        if stage == "plan" or stage.startswith("plan-"):
            mark("plan", "done", at)
        elif stage == "development-challenge":
            if result.get("state") == "awaiting_native_owner_reply":
                mark("approval", "active", at, "The plan was texted to you; reply yes to start.")
            else:
                mark("approval", "done", at)
        elif stage == "qa" or stage.startswith(("qa-fix-", "qa-recovery-")):
            if result.get("decision") == "PASS":
                mark("qa", "done", at, "Passed")
            else:
                mark("qa", "failed", at, "; ".join(_findings(result)[:3]) or "QA found problems")
                last_check = "qa"
        elif stage == "reviewer" or stage.startswith("reviewer-fix-"):
            if result.get("decision") == "APPROVED":
                mark("review", "done", at, "Approved")
            else:
                mark("review", "failed", at,
                     "; ".join(_findings(result)[:3]) or "The Reviewer asked for changes")
                last_check = "review"
        elif stage == "developer" or stage.startswith("developer-fix-"):
            fix_rounds = max(fix_rounds, _round(stage) if stage != "developer" else 0)
            mark("build", "done", at, "Fix round %d done" % fix_rounds if fix_rounds else None)
            if fix_rounds:
                # A new round reopens the checks it has to pass again.
                for key in ("qa", "review"):
                    if steps[key]["state"] == "failed":
                        steps[key]["state"] = "pending"
        elif stage.startswith("publication-challenge"):
            if result.get("state") == "publication_delegated":
                mark("publish", "active", at, "Opening the draft PR (approved with the plan)")
            else:
                mark("publish", "active", at, "Waiting for your go-ahead to publish")
        elif stage == "publisher" or stage.startswith("publisher-retry-"):
            if result.get("status") == "PUBLISHED_DRAFT" and result.get("draft_pr_url"):
                links["pr"] = str(result["draft_pr_url"])
                mark("publish", "done", at, "Draft PR open")
            elif result.get("status") == "ERROR":
                mark("publish", "failed", at, result.get("detail") or "Publishing failed")
        elif stage == "merge":
            if result.get("status") == "MERGED":
                if result.get("commit_url"):
                    links["commit"] = str(result["commit_url"])
                mark("merge", "done", at, "Merged into main")
            elif result.get("status") == "NOT_MERGED":
                mark("merge", "failed", at, result.get("reason") or "Not merged; the draft PR waits")
        elif stage == "undo":
            if result.get("status") == "REVERTED":
                if result.get("commit_url"):
                    links["undo"] = str(result["commit_url"])
                links["undone_at"] = at
            elif result.get("status") == "NOT_REVERTED":
                links["undo_refused"] = _short(result.get("reason"), 200)

    if steps["approval"]["state"] == "pending" and _mtime(directory / "developer.attempt.json"):
        mark("approval", "done", _mtime(directory / "developer.attempt.json"))
    building = sorted(directory.glob("developer*.attempt.json"), key=lambda p: p.stat().st_mtime)
    if building:
        latest = building[-1]
        stage = latest.name[: -len(".attempt.json")]
        if not (directory / (stage + ".result.json")).exists():
            fix_rounds = max(fix_rounds, _round(stage) if stage != "developer" else 0)
            mark("build", "active", latest.stat().st_mtime,
                 "Fix round %d" % fix_rounds if fix_rounds else "Working")
    for key, prefix in (("qa", "qa"), ("review", "reviewer")):
        for attempt in directory.glob(prefix + "*.attempt.json"):
            stage = attempt.name[: -len(".attempt.json")]
            if not (directory / (stage + ".result.json")).exists() and steps[key]["state"] != "done":
                mark(key, "active", attempt.stat().st_mtime, "Checking")

    developers = []
    for report_path in sorted((reports / directory.parent.name / directory.name).glob("report-*.json")):
        report = _json(report_path)
        if isinstance(report, dict) and report.get("specialist") in TEAM:
            model = report.get("model_used") or {}
            developers.append({
                "specialist": report["specialist"],
                "title": TITLES[report["specialist"]],
                "status": report.get("status"),
                "model": model.get("model") if isinstance(model, dict) else None,
                "summary": _short(report.get("work_completed"), 300) or None,
                "at": report_path.stat().st_mtime,
            })

    stopped = None
    for failure in sorted(directory.glob("*.failure.json"), key=lambda p: p.stat().st_mtime):
        stage = failure.name[: -len(".failure.json")]
        stopped = {"stage": stage, "at": failure.stat().st_mtime,
                   "reason": "You stopped it" if stage == "owner-abandoned"
                   else "Stopped at %s; nothing is retried on its own" % stage}
    if (at := _mtime(directory / "fix-rounds-exhausted.result.json")) is not None:
        stopped = {"stage": "fix-rounds", "at": at,
                   "reason": "The fix rounds ran out; you decide what happens next"}

    lane = _lane(steps, stopped, links, last_check, fix_rounds)
    updated = max([started or 0] + [s["at"] or 0 for s in steps.values()]
                  + [stopped["at"] if stopped else 0, links.get("undone_at") or 0])
    return {
        "project": directory.parent.name,
        "taskId": directory.name,
        "title": _objective(directory) or None,
        "specialists": [{"id": s, "title": TITLES[s]} for s in specialists],
        "squads": squads,
        "lane": lane,
        "laneLabel": LANES[lane],
        "fixRounds": fix_rounds,
        "steps": [steps[key] for key, _ in STEPS],
        "developers": developers,
        "stopped": stopped,
        "links": {k: v for k, v in links.items() if k in ("pr", "commit", "undo")},
        "undoRefused": links.get("undo_refused"),
        "startedAt": started,
        "updatedAt": updated or None,
    }


def _lane(steps: dict, stopped, links: dict, last_check, fix_rounds: int) -> str:
    if links.get("undone_at"):
        return "undone"
    if steps["merge"]["state"] == "done":
        return "done"
    if stopped:
        return "stopped"
    if steps["publish"]["state"] in ("active", "done") or steps["merge"]["state"] == "failed":
        return "shipping" if steps["merge"]["state"] != "failed" else "waiting"
    if steps["publish"]["state"] == "failed":
        return "stopped"
    if steps["review"]["state"] in ("active",) or (
            steps["qa"]["state"] == "done" and steps["review"]["state"] == "pending"
            and steps["build"]["state"] == "done"):
        return "review"
    if steps["build"]["state"] == "active":
        return "fixing" if fix_rounds else "building"
    if steps["qa"]["state"] == "active" or (
            steps["build"]["state"] == "done" and steps["qa"]["state"] == "pending"):
        return "qa"
    if last_check and steps[last_check]["state"] == "failed":
        return "fixing"
    if steps["approval"]["state"] == "active":
        return "waiting"
    if steps["approval"]["state"] == "done":
        return "building"
    return "planning"


def snapshot(jobs: Path = JOBS, reports: Path = REPORTS, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    tasks, skipped = [], 0
    for directory in sorted(jobs.glob("*/T-*")):
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            tasks.append(workflow(directory, reports))
        except Exception:  # one malformed record never hides the other tasks
            skipped += 1
    tasks.sort(key=lambda t: t["updatedAt"] or 0, reverse=True)
    return {"schema": SCHEMA, "generatedAt": now, "lanes": LANES,
            "steps": [{"key": k, "label": l} for k, l in STEPS],
            "tasks": tasks[:MAX_TASKS], "truncated": len(tasks) > MAX_TASKS, "skipped": skipped}


def write(board: dict, out: Path = OUT, group: str | None = READER_GROUP) -> None:
    temporary = out.with_name(out.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        if group is not None:
            try:
                os.fchown(fd, -1, grp.getgrnam(group).gr_gid)
                os.fchmod(fd, 0o640)
            except KeyError:
                pass  # no reader group: the file stays root-only
        os.write(fd, (json.dumps(board, sort_keys=True) + "\n").encode())
    finally:
        os.close(fd)
    os.replace(temporary, out)


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("run as root from alfred-dev-board.service")
    board = snapshot()
    write(board)
    print(json.dumps({"tasks": len(board["tasks"]), "skipped": board["skipped"]}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
