"""The development pipeline speaks in the squads' Telegram group chats.

A separate root oneshot (alfred-dev-squads.timer) reads what the pipeline has already
recorded for each task and posts each step once, through the squads bridge
(alfred-os-squads, loopback only), as the bot of the agent that did it:

- the Dev CTO announces the plan and the team, then each assignment;
- each specialist reports what it changed (or why it could not);
- QA reports its verdict; the CTO reports the review, fix rounds, the draft PR and stops.

It only reads pipeline evidence and never writes it, so it cannot change, hold or speed
up a task. If an agent's bot is not connected yet, the CTO posts for it. A squad chat
that is not linked yet, a missing CTO bot or a Telegram limit leaves the message pending
for the next run. Steps older than MAX_AGE are never posted, so linking a chat later does
not replay history. Each squad gets at most PER_RUN messages per run.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

JOBS = Path("/var/lib/alfred-v1-handoffs")
REPORTS = Path("/var/lib/alfred-development-state")
STATE = Path("/var/lib/alfred-dev-squads/posted.json")
AGENTS_TOKEN = Path("/etc/alfred-os-squads/agents-token")
BRIDGE = "http://127.0.0.1:8798"
MAX_AGE = 6 * 3600
PER_RUN = 8
MAX_TEXT = 3500
CTO = "cto"
# Pipeline specialist -> (squads bridge agent id, squad).
TEAM = {
    "frontend": ("frontend", "web-app"),
    "backend": ("backend", "web-app"),
    "full_stack": ("full-stack", "web-app"),
    "ai_ml": ("ai-ml", "ai-data"),
    "data_scientist": ("data-scientist", "ai-data"),
    "data_engineer": ("data-engineer", "ai-data"),
    "devops": ("devops", "integrations-infra"),
    "integration": ("integrations", "integrations-infra"),
    "security": ("security", "security-review"),
}
TITLES = {
    "frontend": "Frontend", "backend": "Backend", "full_stack": "Full Stack",
    "ai_ml": "AI/ML", "data_scientist": "Data Scientist", "data_engineer": "Data Engineer",
    "devops": "DevOps", "integration": "Integrations", "security": "Security",
}
# The squads bridge's own squad ids and agent id rule (config.squads.example.json).
SQUADS = {"core", "web-app", "ai-data", "integrations-infra", "security-review"}


def AGENT_ID_OK(agent: str) -> bool:  # noqa: N802 - mirrors the bridge's AGENT_ID
    import re

    return re.fullmatch(r"[a-z][a-z0-9-]{1,31}", agent) is not None


# Answers that mean "try again on the next run" rather than "never".
RETRY = {409, 429, 500, 502, 503}


def _json(path: Path):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None


def _short(text, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _names(items) -> list[str]:
    """File or blocker entries as text: reports list files as {path, sha256}."""
    out = []
    for item in items or []:
        if isinstance(item, dict):
            item = item.get("path") or item.get("detail") or item.get("reason")
        if item:
            out.append(str(item))
    return out


def _squads(specialists) -> list[str]:
    out = []
    for s in specialists or []:
        if s in TEAM and TEAM[s][1] not in out:
            out.append(TEAM[s][1])
    return out


def _objective(directory: Path) -> str:
    request = _json(directory / "execution.json") or {}
    items = request.get("items") or []
    text = items[0].get("objective", "") if items and isinstance(items[0], dict) else ""
    return _short(text.split("\nCanonical specification")[0].strip().splitlines()[0] if text else "")


def _findings(result: dict) -> list[str]:
    lines = []
    for f in result.get("findings") or []:
        if isinstance(f, dict) and f.get("severity") != "info":
            lines.append(_short(f"{f.get('requirement')}: {f.get('detail')}", 140))
    return lines[:5]


def events(directory: Path, reports: Path, now: float) -> list[dict]:
    """Every postable step of one task, oldest first: {key, squad, agent, text, at}."""
    context = _json(directory / "context.json") or {}
    specialists = [s for s in context.get("specialists") or [] if s in TEAM]
    squads = _squads(specialists)
    if not squads:
        return []
    project, task = directory.parent.name, directory.name
    name = f"{project} {task}"
    out = []

    def add(key, at, text, agent=CTO, only=None):
        for squad in [only] if only else squads:
            out.append({"key": f"{project}/{task}/{key}/{squad}", "squad": squad,
                        "agent": agent, "text": text[:MAX_TEXT], "at": at})

    def mtime(name_):
        try:
            return (directory / name_).stat().st_mtime
        except OSError:
            return None

    goal = _objective(directory)
    if (at := mtime("plan.result.json")) is not None:
        team = ", ".join(f"{TITLES[s]} ({', '.join(context.get('scope') or [])})"
                         if len(specialists) == 1 else TITLES[s] for s in specialists)
        add("plan", at, f"📋 New task, {name}: {goal or 'see the plan'}\nTeam: {team}.")
    if (at := mtime("developer.attempt.json")) is not None:
        for s in specialists:
            agent, squad = TEAM[s]
            add(f"assign-{s}", at, f"▶️ {TITLES[s]}, you're up on {name}.", only=squad)
    for report_path in sorted((reports / project / task).glob("report-*.json")):
        report = _json(report_path)
        if not isinstance(report, dict) or report.get("specialist") not in TEAM:
            continue
        s = report["specialist"]
        agent, squad = TEAM[s]
        model = report.get("model_used") or {}
        via = f" ({model.get('provider')}/{model.get('model')})" if model.get("model") else ""
        if report.get("status") == "completed":
            files = ", ".join(_names(report.get("files_modified"))) or "no files"
            text = (f"✅ Done with {name}{via}: {_short(report.get('work_completed'), 300)}\n"
                    f"Changed: {files}.")
        else:
            text = f"⚠️ I couldn't finish {name}: {_short('; '.join(_names(report.get('blockers'))))}"
        add(f"{report_path.stem}-{int(report_path.stat().st_mtime)}", report_path.stat().st_mtime,
            text, agent=agent, only=squad)
    for result_path in sorted(directory.glob("*.result.json"), key=lambda p: p.stat().st_mtime):
        stage = result_path.name[: -len(".result.json")]
        result = _json(result_path)
        if not isinstance(result, dict):
            continue
        at = result_path.stat().st_mtime
        if stage == "qa" or stage.startswith(("qa-fix-", "qa-recovery-")):
            if result.get("decision") == "PASS":
                text = f"🧪 QA passed {name}."
            else:
                text = "🧪 QA found problems in {}:\n{}".format(
                    name, "\n".join("- " + f for f in _findings(result)) or "- see the QA report")
            add(stage, at, text, agent="qa")
        elif stage == "reviewer" or stage.startswith("reviewer-fix-"):
            if result.get("decision") == "APPROVED":
                text = f"🔎 Review approved {name}."
            else:
                text = "🔎 Review asked for changes on {}:\n{}".format(
                    name, "\n".join("- " + f for f in _findings(result)) or "- see the review")
            add(stage, at, text)
        elif stage.startswith("developer-fix-"):
            add(stage, mtime(stage + ".attempt.json") or at,
                f"🔁 Fix round {stage.rsplit('-', 1)[1]} on {name}: back to "
                f"{', '.join(TITLES[s] for s in specialists)} with the findings above.")
        elif stage.startswith("publication-challenge"):
            if result.get("state") == "publication_delegated":
                add(stage, at, f"📦 {name} passed review; opening the draft PR "
                               "(Hayden approved it with the request).")
            else:
                add(stage, at, f"📨 {name} is ready; waiting for Hayden's go-ahead to publish.")
        elif stage == "publisher" or stage.startswith("publisher-retry-"):
            if result.get("status") == "PUBLISHED_DRAFT" and result.get("draft_pr_url"):
                add("published", at, f"🚀 {name} is on GitHub as a draft: {result['draft_pr_url']}")
            elif result.get("status") == "ERROR":
                add(stage, at, f"⚠️ Publishing {name} failed: {_short(result.get('detail'))}")
    if (at := mtime("fix-rounds-exhausted.result.json")) is not None:
        add("exhausted", at, f"🛑 {name} is on hold: the fix rounds ran out. Hayden decides next.")
    for failure in directory.glob("*.failure.json"):
        stage = failure.name[: -len(".failure.json")]
        if stage == "owner-abandoned":
            text = f"🛑 Hayden stopped {name}."
        else:
            text = f"🛑 {name} stopped at {stage}. Hayden has been told; nothing is retried on its own."
        add(f"stopped-{stage}", failure.stat().st_mtime, text)
    return sorted(out, key=lambda e: e["at"])


class Bridge:
    def __init__(self, token: str, base: str = BRIDGE):
        self.token, self.base = token, base

    def post(self, squad: str, agent: str, text: str) -> tuple[int, dict]:
        body = json.dumps({"agent": agent, "text": text}).encode()
        request = urllib.request.Request(
            f"{self.base}/v1/squads/{squad}/agent-messages", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except ValueError:
                return exc.code, {}
        except (OSError, ValueError):
            return 503, {"error": "bridge_unreachable"}


def deliver(event: dict, bridge: Bridge) -> str:
    """'sent', 'retry' or 'skip'. The CTO speaks for an agent whose bot isn't connected."""
    status, reply = bridge.post(event["squad"], event["agent"], event["text"])
    if status == 200:
        return "sent"
    if event["agent"] != CTO and reply.get("error") in {"bot_not_configured", "agent_not_in_squad"}:
        status, reply = bridge.post(event["squad"], CTO, f"[{event['agent']}] {event['text']}")
        if status == 200:
            return "sent"
    if status in RETRY or reply.get("error") == "bot_not_configured":
        return "retry"
    return "skip"


def _load_state(path: Path) -> dict:
    data = _json(path)
    return data if isinstance(data, dict) and isinstance(data.get("posted"), dict) else {"posted": {}}


def _save_state(path: Path, state: dict, now: float) -> None:
    # Forget keys well past MAX_AGE: those steps can never be posted again anyway.
    state["posted"] = {k: v for k, v in state["posted"].items() if now - v < 4 * MAX_AGE}
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(state, stream, sort_keys=True)
    os.replace(temporary, path)


def _token(path: Path) -> str | None:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            return None
        token = path.read_text().strip()
    except OSError:
        return None
    return token or None


def run(jobs: Path = JOBS, reports: Path = REPORTS, state_path: Path = STATE,
        bridge: Bridge | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if bridge is None:
        token = _token(AGENTS_TOKEN)
        if token is None:
            return {"posted": 0, "reason": "squads bridge agents token unavailable"}
        bridge = Bridge(token)
    state = _load_state(state_path)
    posted, pending, per_squad = 0, 0, {}
    for directory in sorted(jobs.glob("*/T-*")):
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            found = events(directory, reports, now)
        except Exception as exc:  # one malformed record never stops the other tasks
            print(json.dumps({"skipped": directory.name, "error": type(exc).__name__}),
                  file=sys.stderr, flush=True)
            continue
        for event in found:
            if event["key"] in state["posted"] or now - event["at"] > MAX_AGE:
                continue
            if per_squad.get(event["squad"], 0) >= PER_RUN:
                pending += 1
                continue
            outcome = deliver(event, bridge)
            if outcome == "retry":
                pending += 1
                per_squad[event["squad"]] = PER_RUN  # keep this squad's order: try again next run
                continue
            state["posted"][event["key"]] = now
            per_squad[event["squad"]] = per_squad.get(event["squad"], 0) + 1
            posted += outcome == "sent"
    _save_state(state_path, state, now)
    return {"posted": posted, "pending": pending}


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("run as root from alfred-dev-squads.service")
    print(json.dumps(run()), flush=True)


if __name__ == "__main__":
    main()
