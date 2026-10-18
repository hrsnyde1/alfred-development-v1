#!/usr/bin/python3 -IB
"""Restricted root operations for Alfred Development (Option C). Installed root-owned at
/usr/local/sbin/alfred-dev-ops and run by the owner with sudo.

Only these operations exist: status, pause, resume, install <N>, rollback <N>,
resend <task> (one fresh publication approval text for an expired one) and abandon
<project/task> (stop one task for good, by the owner's decision) and republish
<project/task> (one more publish attempt after a definite Publisher error) and
claude-token (save the development agents' own long-lived Claude token) and
confirm-delivered <project/task> (the owner received a completion text whose delivery
record stayed uncertain; nothing is sent or resent). There is no generic command, path
or argument passthrough. `install` runs a fixed sequence on a
pinned handoff release, executing only code from inside the hash-verified archive, never
from the alfred-writable checkout. The owner confirms each install by typing the start of
the archive SHA-256 from Claude's report; the helper never displays it first. Every
operation appends a record to the root-only audit log.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import getpass
import grp
import hashlib
import json
import os
import pwd
import re
import stat
import shutil
import subprocess
import sys
from pathlib import Path

LAB = Path("/home/alfred/alfred-development-v1")
PAUSE = Path("/home/alfred/Alfred/gateway/PAUSE")
WORK = Path("/root")
AUDIT = Path("/var/log/alfred-dev-ops.jsonl")
# The only units an install may restart; a release can name a subset, never others.
RESTARTABLE = {"alfred-development-intake.service"}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"alfred-fresh-v1-1\.0\.1-development-handoff\.[0-9]{1,3}\Z")
RELEASE_KEYS = {"schema", "name", "archive_sha256", "manifest_sha256", "installer",
                "installer_sha256", "installed_after", "preflight", "restart"}
PYTHON = "/usr/bin/python3"
# The development agents' own Claude token: root-owned, readable by the alfred group only.
CLAUDE_TOKEN = Path("/etc/alfred-development/claude-agents.token")
TOKEN = re.compile(r"[A-Za-z0-9_-]{20,400}\Z")


class Refused(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(operation: str, outcome: str, **detail) -> None:
    record = {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "operation": operation,
              "outcome": outcome, "sudo_user": os.environ.get("SUDO_USER"), **detail}
    fd = os.open(AUDIT, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+ " + " ".join(argv), flush=True)
    return subprocess.run(argv, check=True, text=True, **kwargs)


def release_pins(number: int) -> dict:
    """The handoff's pins. Untrusted until the owner confirms the archive hash."""
    pins = json.loads((LAB / f"development_handoff{number}" / "release.json").read_bytes())
    if (type(pins) is not dict or set(pins) != RELEASE_KEYS
            or pins["schema"] != "alfred.development-release/1"
            or not NAME.fullmatch(pins["name"])
            or not pins["name"].endswith(f".{number}")
            or not all(HEX64.fullmatch(pins[k]) for k in
                       ("archive_sha256", "manifest_sha256", "installer_sha256"))
            or pins["installer"] != f"development_handoff{number}/install_patch.py"
            or pins["installed_after"] != f"development_handoff{number}/installed-after.sha256"
            or pins["preflight"] not in (None, "verification/role_sandbox_preflight.py")
            or type(pins["restart"]) is not list or not set(pins["restart"]) <= RESTARTABLE):
        raise Refused("release pins invalid")
    return pins


def confirm_archive(pins: dict, answer: str) -> None:
    if len(answer) != 12 or not pins["archive_sha256"].startswith(answer.lower()):
        raise Refused("archive hash not confirmed; nothing was changed")


def install(number: int, answer: str) -> dict:
    pins = release_pins(number)
    confirm_archive(pins, answer)
    if not PAUSE.is_file():
        raise Refused("PAUSE is not set; run `alfred-dev-ops pause` first")
    name = pins["name"]
    archive = WORK / (name + ".tar.gz")
    review = WORK / (name + "-review")
    backup = WORK / (name + "-backup")
    if review.exists() or backup.exists():
        raise Refused(f"{review} or {backup} already exists; this release was already used")
    shutil.copyfile(LAB / "dist" / (name + ".tar.gz"), archive)
    os.chmod(archive, 0o600)
    if sha256(archive) != pins["archive_sha256"]:
        raise Refused("archive differs from the confirmed pin")
    review.mkdir(mode=0o700)
    run(["tar", "--no-same-owner", "--no-same-permissions", "-xzf", str(archive), "-C", str(review)])
    release = review / name
    installer = release / pins["installer"]
    if sha256(installer) != pins["installer_sha256"]:
        raise Refused("installer differs from its pin")
    run([PYTHON, "-I", "-B", str(installer), "verify", "--release", str(release),
         "--manifest", pins["manifest_sha256"]])
    run([PYTHON, "-I", "-B", str(installer), "install", "--release", str(release),
         "--manifest", pins["manifest_sha256"], "--backup", str(backup)])
    run(["sha256sum", "-c", str(release / pins["installed_after"])])
    for unit in pins["restart"]:
        run(["systemctl", "restart", unit])
        run(["systemctl", "is-active", "--quiet", unit])
    if pins["preflight"]:
        # The verified copy, run from inside the release; never the writable checkout.
        run([PYTHON, "-I", "-B", pins["preflight"]], cwd=release)
    if not PAUSE.is_file():
        raise Refused("PAUSE disappeared during install; investigate before resuming")
    return {"release": name, "archive_sha256": pins["archive_sha256"],
            "restarted": pins["restart"], "pause": "still set"}


def rollback(number: int) -> dict:
    pins = release_pins(number)
    if not PAUSE.is_file():
        raise Refused("PAUSE is not set; run `alfred-dev-ops pause` first")
    release = WORK / (pins["name"] + "-review") / pins["name"]
    installer = release / pins["installer"]
    if sha256(installer) != pins["installer_sha256"]:
        raise Refused("installer differs from its pin")
    run([PYTHON, "-I", "-B", str(installer), "rollback",
         "--backup", str(WORK / (pins["name"] + "-backup"))])
    for unit in pins["restart"]:
        run(["systemctl", "restart", unit])
    return {"release": pins["name"], "state": "rolled back", "pause": "still set"}


TASK = re.compile(r"T-[0-9]{4,}\Z")
JOBS = Path("/var/lib/alfred-v1-handoffs")
GRANTS = Path("/var/lib/alfred-development-grants")


def resend(task: str, now: float) -> dict:
    """Authorize one fresh publication approval text for an expired, unanswered one."""
    project, _, number = task.rpartition("/")
    if not TASK.fullmatch(number) or (project and not PROJECT.fullmatch(project)):
        raise Refused("task must look like T-0009 or demo-site/T-0009")
    task = number
    directories = sorted(JOBS.glob(f"{project or '*'}/{task}"))
    if len(directories) != 1:
        raise Refused(f"{task} not found")
    directory = directories[0]
    results = sorted(directory.glob("publication-challenge*.result.json"),
                     key=lambda p: p.stat().st_mtime)
    if not results:
        raise Refused(f"{task} has not asked for publication approval yet")
    reference = json.loads(results[-1].read_bytes())["challenge"]
    if (GRANTS / f"publication-decision-{reference}.json").exists():
        raise Refused(f"{task} was already approved; nothing to resend")
    receipt = json.loads((GRANTS / f"publication-challenge-{reference}.json").read_bytes())
    if now <= receipt["expires_at"]:
        raise Refused(f"{task}'s approval text is still open; reply yes to it")
    n = 1
    while (directory / f"publication-resend-{n}.json").exists():
        n += 1
    if (directory / f"publication-resend-{n - 1}.json").exists() and not (
            directory / f"publication-challenge-resend-{n - 1}.result.json").exists():
        raise Refused(f"a resend for {task} is already queued")
    record = {"schema": "alfred.publication-resend/1", "project": directory.parent.name,
              "task_id": task, "n": n, "authorized_by": os.environ.get("SUDO_USER"),
              "authorized_at": now}
    fd = os.open(directory / f"publication-resend-{n}.json",
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return {"task": task, "resend": n, "next": "a fresh approval text within about 2 minutes"}


PROJECT = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")


def abandon(name: str, now: float) -> dict:
    """Stop one task for good, by the owner's decision: add a record the poll treats as
    a definite outcome. Nothing existing is changed, removed or retried."""
    project, _, task = name.partition("/")
    if not PROJECT.fullmatch(project) or not TASK.fullmatch(task):
        raise Refused("name the task as project/task, for example demo-site/T-0002")
    directory = JOBS / project / task
    if not directory.is_dir() or directory.is_symlink():
        raise Refused(f"{name} not found")
    if (directory / "complete.json").exists():
        raise Refused(f"{name} already completed")
    if any(directory.glob("*.failure.json")):
        raise Refused(f"{name} is already stopped")
    record = {"schema": "alfred.owner-abandoned/1", "stage": "owner-abandoned",
              "project": project, "task_id": task,
              "authorized_by": os.environ.get("SUDO_USER"), "abandoned_at": now}
    fd = os.open(directory / "owner-abandoned.failure.json",
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return {"task": name, "state": "abandoned", "next": "later requests run on the next poll"}


def claude_token(token: str) -> dict:
    """Save the agents' long-lived token from `claude setup-token`. It is never printed or
    logged; only its fingerprint is."""
    token = token.strip()
    if not TOKEN.fullmatch(token):
        raise Refused("that does not look like a Claude token; nothing was saved")
    gid = grp.getgrnam("alfred").gr_gid
    temporary = CLAUDE_TOKEN.with_name(CLAUDE_TOKEN.name + ".new")
    temporary.unlink(missing_ok=True)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchown(fd, 0, gid)
        os.fchmod(fd, 0o640)
        os.write(fd, (token + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, CLAUDE_TOKEN)
    return {"claude_token": "saved", "fingerprint": hashlib.sha256(token.encode()).hexdigest()[:12],
            "next": "agents use it from their next task"}


MAX_PUBLISH_RETRIES = 3


def republish(name: str, now: float) -> dict:
    """Authorize one more publish attempt after the Publisher reported a definite error."""
    project, _, task = name.partition("/")
    if not PROJECT.fullmatch(project) or not TASK.fullmatch(task):
        raise Refused("name the task as project/task, for example demo-site/T-0003")
    directory = JOBS / project / task
    if not directory.is_dir() or directory.is_symlink():
        raise Refused(f"{name} not found")
    if (directory / "complete.json").exists():
        raise Refused(f"{name} already completed")
    n = 1
    while (directory / f"publisher-retry-{n}.json").exists():
        n += 1
    latest = directory / ("publisher.result.json" if n == 1 else f"publisher-retry-{n - 1}.result.json")
    if not latest.exists():
        raise Refused(f"{name} has no recorded publisher result to retry"
                      if n == 1 else f"a publish retry for {name} is already queued")
    if json.loads(latest.read_bytes()).get("status") != "ERROR":
        raise Refused(f"{name}'s last publish did not report a definite error")
    if n > MAX_PUBLISH_RETRIES:
        raise Refused(f"{name} already used {MAX_PUBLISH_RETRIES} publish retries")
    record = {"schema": "alfred.publisher-retry/1", "project": project, "task_id": task,
              "n": n, "authorized_by": os.environ.get("SUDO_USER"), "authorized_at": now}
    fd = os.open(directory / f"publisher-retry-{n}.json",
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return {"task": name, "retry": n, "next": "the next poll publishes again"}


DELIVERY = Path("/home/alfred/Alfred/completion-delivery")


def delivery_uid() -> int:
    return pwd.getpwnam("alfred").pw_uid


def latest_publish(directory: Path) -> dict:
    """The task's last recorded Publisher result (the original or the latest retry)."""
    latest = directory / "publisher.result.json"
    for n in range(1, MAX_PUBLISH_RETRIES + 1):
        if (directory / f"publisher-retry-{n}.result.json").exists():
            latest = directory / f"publisher-retry-{n}.result.json"
    return json.loads(latest.read_bytes()) if latest.exists() else {}


def tracked() -> bytes:
    """delivery.json as it is now, read under the tracker's own lock so no send is in
    flight. Opened read-only; the lock and state are never created or replaced."""
    lock = os.open(DELIVERY / "delivery.lock", os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.open(DELIVERY / "delivery.json", os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != delivery_uid() or info.st_mode & 0o077):
                raise Refused("completion delivery state is not protected; nothing was changed")
            return stream.read(1048577)
    except BlockingIOError:
        raise Refused("a completion text is being sent right now; try again shortly") from None
    finally:
        os.close(lock)


def confirm_delivered(name: str, now: float) -> dict:
    """The owner received a completion text whose delivery record stayed `uncertain`
    with no receipt: record that confirmation separately so the poll completes the
    task. The uncertain record stays as it is (it is still the duplicate guard), the
    attempt and failure evidence stay, and nothing is sent or resent."""
    project, _, task = name.partition("/")
    if not PROJECT.fullmatch(project) or not TASK.fullmatch(task):
        raise Refused("name the task as project/task, for example demo-site/T-0003")
    directory = JOBS / project / task
    if not directory.is_dir() or directory.is_symlink():
        raise Refused(f"{name} not found")
    if (directory / "complete.json").exists():
        raise Refused(f"{name} already completed")
    if (directory / "completion-confirmed.json").exists():
        raise Refused(f"{name}'s delivery is already confirmed")
    if not (directory / "completion.attempt.json").exists():
        raise Refused(f"{name} has not attempted its completion text")
    if any(p.name != "completion.failure.json" for p in directory.glob("*.failure.json")):
        raise Refused(f"{name} stopped before its completion text")
    if (directory / "completion.result.json").exists() and json.loads(
            (directory / "completion.result.json").read_bytes()).get("status") != "uncertain":
        raise Refused(f"{name}'s completion did not end uncertain")
    published = latest_publish(directory)
    if published.get("status") != "PUBLISHED_DRAFT":
        raise Refused(f"{name} has no published draft PR")
    revision = json.loads(
        (directory / "completion" / "config.json").read_bytes())["binding"]["final_revision"]
    raw = tracked()
    records = {
        key: record for key, record in json.loads(raw)["records"].items()
        if record["identity"][:2] == [project, task]
    }
    if len(records) != 1:
        raise Refused(f"{name} has {len(records)} completion delivery records, not one")
    (key, record), = records.items()
    identity = record["identity"]
    if record["state"] != "uncertain" or record.get("receipt_id") is not None:
        raise Refused(f"{name}'s completion record is {record['state']}, not uncertain")
    if (hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest() != key
            or identity != [project, task, published.get("draft_pr_url"), revision]):
        raise Refused(f"{name}'s completion record does not match its published draft PR")
    snapshot = directory / "completion-confirmed.delivery.json"
    fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
    confirmation = {"schema": "alfred.completion-owner-confirmed/1", "project": project,
                    "task_id": task, "record_key": key, "identity": identity,
                    "text_digest": record["text_digest"], "transport_state": "uncertain",
                    "receipt_id": None, "delivery_sha256": hashlib.sha256(raw).hexdigest(),
                    "resend_permitted": False, "authorized_by": os.environ.get("SUDO_USER"),
                    "confirmed_at": now}
    fd = os.open(directory / "completion-confirmed.json",
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(confirmation, indent=2, sort_keys=True) + "\n")
    return {"task": name, "state": "owner-confirmed received", "transport_state": "uncertain",
            "next": "the next poll marks it complete; nothing is sent"}


def status() -> dict:
    handoffs = JOBS
    tasks = {}
    for directory in sorted(handoffs.glob("*/T-*")):
        stages = sorted(p.name.removesuffix(".result.json")
                        for p in directory.glob("*.result.json"))
        failed = sorted(p.name.removesuffix(".failure.json")
                        for p in directory.glob("*.failure.json"))
        tasks[f"{directory.parent.name}/{directory.name}"] = {"completed_stages": stages, "failed": failed,
                                 "complete": (directory / "complete.json").exists()}
    return {"pause": PAUSE.is_file(), "tasks": tasks}


def main() -> int:
    parser = argparse.ArgumentParser(prog="alfred-dev-ops")
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("status")
    sub.add_parser("pause")
    sub.add_parser("resume")
    for name in ("install", "rollback"):
        sub.add_parser(name).add_argument("handoff", type=int)
    sub.add_parser("resend").add_argument("task")
    sub.add_parser("abandon").add_argument("task", help="project/task, e.g. demo-site/T-0002")
    sub.add_parser("republish").add_argument("task", help="project/task, e.g. demo-site/T-0003")
    sub.add_parser("claude-token")
    sub.add_parser("confirm-delivered").add_argument(
        "task", help="project/task, e.g. demo-site/T-0003")
    args = parser.parse_args()
    if os.geteuid() != 0:
        print("Run with sudo.", file=sys.stderr)
        return 2
    try:
        if args.operation == "status":
            result = status()
        elif args.operation == "pause":
            PAUSE.touch()
            result = {"pause": True}
        elif args.operation == "resume":
            if input("Type RESUME to let the Gateway run new work: ").strip() != "RESUME":
                raise Refused("not confirmed")
            PAUSE.unlink(missing_ok=True)
            result = {"pause": False}
        elif args.operation == "install":
            answer = input("Type the first 12 characters of the archive SHA-256 from Claude's report: ")
            result = install(args.handoff, answer.strip())
        elif args.operation == "resend":
            result = resend(args.task, dt.datetime.now(dt.timezone.utc).timestamp())
        elif args.operation == "abandon":
            result = abandon(args.task, dt.datetime.now(dt.timezone.utc).timestamp())
        elif args.operation == "republish":
            result = republish(args.task, dt.datetime.now(dt.timezone.utc).timestamp())
        elif args.operation == "claude-token":
            result = claude_token(getpass.getpass(
                "Paste the token from `claude setup-token` (input is hidden): "))
        elif args.operation == "confirm-delivered":
            if input(f"Type RECEIVED if you got the completion text for {args.task}: "
                     ).strip() != "RECEIVED":
                raise Refused("not confirmed")
            result = confirm_delivered(args.task, dt.datetime.now(dt.timezone.utc).timestamp())
        else:
            result = rollback(args.handoff)
    except (Refused, subprocess.CalledProcessError, OSError, ValueError) as exc:
        audit(args.operation, "refused_or_failed", handoff=getattr(args, "handoff", None),
              reason=str(exc))
        print("STOPPED: " + str(exc), file=sys.stderr)
        return 1
    if args.operation != "status":
        audit(args.operation, "ok", handoff=getattr(args, "handoff", None), result=result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
