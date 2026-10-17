"""Read-only Central CTO planning after the existing Gateway files a task.

This module cannot promote a task or launch a coding stage. Its only writes are
plan/delivery artifacts below the protected Gateway directory.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import stat
import sys
from pathlib import Path

from alfred.gateway.journal import Journal, JournalError
from alfred.registry.loader import RegistryError, parse_registry, read_registry_data
from jsonschema import Draft202012Validator
from taskspec import MAX_BYTES, SpecError, parse, validate

TASK_ID = re.compile(r"T-[0-9]{4}\Z")
REQUEST_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
MAX_PLAN = 32 * 1024
MAX_FILES = 500
MAX_FILE_BYTES = 16 * 1024
WEB_SUFFIXES = {
    ".html",
    ".css",
    ".scss",
    ".sass",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
}
MANIFESTS = {
    "package.json",
    "vite.config.js",
    "vite.config.ts",
    "next.config.js",
    "next.config.mjs",
    "astro.config.mjs",
    "index.html",
    "README.md",
    "pyproject.toml",
}


class CTOError(RuntimeError):
    pass


def _regular_bytes(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise CTOError(f"invalid file: {path.name}")
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > limit:
            raise CTOError(f"oversize file: {path.name}")
        return data
    finally:
        os.close(fd)


def _atomic(path: Path, obj: dict, *, exclusive: bool = False) -> None:
    data = (
        json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode()
    if len(data) > MAX_PLAN:
        raise CTOError("plan exceeds size limit")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not stat.S_ISDIR(os.lstat(path.parent).st_mode):
        raise CTOError("plan directory is not a real directory")
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    else:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _load(path: Path) -> dict:
    try:
        result = json.loads(_regular_bytes(path, MAX_PLAN))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CTOError("invalid plan artifact") from exc
    if not isinstance(result, dict):
        raise CTOError("invalid plan artifact")
    return result


def _validate_plan(plan: dict) -> None:
    schema = json.loads(
        _regular_bytes(Path(__file__).with_name("plan.schema.json"), MAX_PLAN)
    )
    if list(Draft202012Validator(schema).iter_errors(plan)):
        raise CTOError("plan artifact does not match the pending-approval schema")


def _repo_evidence(repo: Path, spec_name: str) -> dict:
    if not repo.is_absolute() or not stat.S_ISDIR(os.lstat(repo).st_mode):
        raise CTOError("registered repository is not a real directory")
    files: list[str] = []
    website: list[str] = []
    tests: list[str] = []
    roots = [repo]
    while roots:
        directory = roots.pop()
        if len(files) >= MAX_FILES:
            raise CTOError("repository exceeds planning inventory limit")
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            relative = Path(entry.path).relative_to(repo).as_posix()
            if entry.name in {
                ".git",
                "node_modules",
                ".venv",
                "__pycache__",
                "dist",
                "build",
            }:
                continue
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                roots.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                files.append(relative)
                if Path(relative).suffix in WEB_SUFFIXES or entry.name in MANIFESTS:
                    website.append(relative)
                if "test" in entry.name.lower() or "spec" in entry.name.lower():
                    tests.append(relative)
            if len(files) >= MAX_FILES:
                raise CTOError("repository exceeds planning inventory limit")
    # Read only bounded, relevant content. A task spec is already read separately.
    excerpts = {}
    for name in list(dict.fromkeys(website[:20] + tests[:20])):
        if name == spec_name or name.startswith(".dev/"):
            continue
        data = _regular_bytes(repo / name, MAX_FILE_BYTES)
        excerpts[name] = data.decode("utf-8", "replace")[:3000]
    return {
        "files": files,
        "web_files": website,
        "test_files": tests,
        "inspected_excerpts": excerpts,
    }


def _task_for(outcome: dict, registry) -> tuple[Path, dict, str, bytes]:
    project_id, task_id, request_id = (
        outcome.get("project"),
        outcome.get("task_id"),
        outcome.get("request_id"),
    )
    if (
        not isinstance(project_id, str)
        or not isinstance(task_id, str)
        or not TASK_ID.fullmatch(task_id)
    ):
        raise CTOError("invalid filed outcome")
    if (
        not isinstance(request_id, str)
        or not REQUEST_ID.fullmatch(request_id)
        or type(outcome.get("revision")) is not int
    ):
        raise CTOError("invalid filed outcome")
    project = registry.project(project_id)
    if (
        project is None
        or project.status != "active"
        or not project.permissions.hermes_requests
    ):
        raise CTOError("filed project is not authorized")
    repo = project.resolved_path(Path.home())
    if not repo.is_absolute() or not stat.S_ISDIR(os.lstat(repo).st_mode):
        raise CTOError("registered repository is not a real directory")
    tasks = repo / ".dev" / "tasks"
    if not stat.S_ISDIR(os.lstat(repo / ".dev").st_mode) or not stat.S_ISDIR(
        os.lstat(tasks).st_mode
    ):
        raise CTOError("task directory is invalid")
    matches = sorted(tasks.glob(f"{task_id}-*.md"))
    if len(matches) != 1:
        raise CTOError("expected exactly one canonical task")
    raw = _regular_bytes(matches[0], MAX_BYTES)
    try:
        doc = parse(raw.decode("utf-8"))
    except (SpecError, UnicodeDecodeError, ValueError) as exc:
        raise CTOError("canonical task cannot be parsed") from exc
    if validate(doc, matches[0].name, project.company):
        raise CTOError("canonical task is invalid")
    if (
        doc.get("id"),
        doc.get("project"),
        doc.get("request_id"),
        doc.get("status"),
        doc.get("source"),
    ) != (task_id, project_id, request_id, "proposed", "hermes"):
        raise CTOError("canonical task disagrees with filed outcome")
    return repo, doc, matches[0].name, raw


def _central_cto(doc: dict, repo: Path, evidence: dict, spec_hash: str) -> dict:
    """One bounded specialist. All named paths come from the registered repo inventory."""
    sections = doc["sections"]
    web = [p for p in evidence["web_files"] if not p.lower().endswith("readme.md")]
    tests = evidence["test_files"]
    dark_mode = "dark mode" in (doc["title"] + " " + sections["objective"]).lower()
    questions = []
    if dark_mode and not any(Path(p).suffix in WEB_SUFFIXES for p in web):
        questions.append(
            "Which authorized repository and path contain the website? The bound repository has no website source to modify."
        )
    if not evidence["files"]:
        questions.append("Where is the application source for this task?")
    if dark_mode:
        approach = "Locate the actual site source, add a visible theme control, use shared light/dark color tokens, persist an explicit choice, and use the OS preference when unset."
        work = [
            "Confirm the website source and existing styling approach.",
            "Add a theme toggle available on every page and preserve the current light appearance.",
            "Apply dark colors to existing page elements and persist manual choice across navigation/reload.",
            "Add focused checks for persistence, OS preference, and keyboard accessibility.",
        ]
        qa = [
            "Inspect all site pages in both themes for readable contrast and unchanged layout.",
            "Check toggle keyboard access and accessible label.",
            "Verify stored choice survives reload/navigation and an unset choice follows prefers-color-scheme.",
            "Run existing repository checks after implementation; check Chrome, Firefox, and Safari if available.",
        ]
        review = [
            "Verify changes stay within frontend scope and no unapproved dependency is added.",
            "Inspect all theme states and storage handling; no sensitive data or unsafe inline script.",
            "Confirm tests cover the requested behavior and no unrelated file changes appear.",
        ]
    else:
        approach = "Inspect the identified components, make the smallest change satisfying the canonical specification, and use existing project conventions."
        work = [
            "Confirm the affected components and existing tests.",
            "Implement the scoped requirements in the registered repository.",
            "Add focused automated coverage and document manual checks.",
        ]
        qa = [
            "Check every canonical acceptance criterion.",
            "Run the registered project checks after implementation and inspect regressions.",
        ]
        review = [
            "Confirm scope, tests, dependencies, and security considerations against the canonical task."
        ]
    risks = list(questions)
    if not tests:
        risks.append(
            "No existing test files were found in the registered repository inventory."
        )
    return {
        "schema": "alfred.cto-plan/1",
        "project": doc["project"],
        "task_id": doc["id"],
        "request_id": doc["request_id"],
        "spec_sha256": spec_hash,
        "approval_state": "awaiting_development_approval",
        "clarification_required": bool(questions),
        "objective": sections["objective"],
        "scope": sections["scope"],
        "repository": str(repo),
        "repository_evidence": {
            "files": evidence["files"],
            "web_files": evidence["web_files"],
            "test_files": tests,
            "inspected_files": list(evidence["inspected_excerpts"]),
        },
        "implementation_approach": approach,
        "expected_components_files": web[:30],
        "developer_work_items": work,
        "developer_deliverables": [
            "Scoped source changes",
            "Focused tests or documented manual verification",
            "Implementation notes for QA and review",
        ],
        "qa_checklist": qa,
        "independent_review_criteria": review,
        "dependencies_integrations": [
            "No new dependency or external integration is planned; seek separate approval if inspection shows one is needed."
        ],
        "risks_blockers": risks,
        "clarification_questions": questions,
        "acceptance_criteria": sections["acceptance_criteria"],
        "owner_summary": f"{doc['id']} ({doc['project']}): {sections['objective']} {approach}",
        "planning_note": "Repository inspected read only; no tests were executed and no development is authorized.",
        "delivery": {"state": "pending", "message_id": None},
    }


def _message(plan: dict) -> str:
    text = (
        f"Development plan {plan['task_id']} ({plan['project']})\n"
        f"Goal: {plan['objective']}\n"
        f"Approach: {plan['implementation_approach']}\n"
        f"Files found: {', '.join(plan['expected_components_files']) or 'no website source found'}\n"
        f"QA: {plan['qa_checklist'][0]}\n"
    )
    if plan["clarification_questions"]:
        text += (
            "Before development, please clarify: "
            + " ".join(plan["clarification_questions"])
            + "\n"
        )
    ask = "Here's how we'll build it. Do you approve development?"
    return text[: 3900 - len(ask) - 1] + "\n" + ask


def _send(config: dict, message: str) -> str:
    destination = config.get("owner_space_id")
    port = config.get("sidecar_port")
    token = config.get("sidecar_token")
    if (
        not isinstance(destination, str)
        or not destination
        or not isinstance(port, int)
        or not 1 <= port <= 65535
        or not isinstance(token, str)
        or not token
    ):
        raise CTOError("protected owner delivery configuration is incomplete")
    body = json.dumps(
        {"spaceId": destination, "text": message, "format": "text"}
    ).encode()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(
            "POST",
            "/send",
            body,
            {"Content-Type": "application/json", "x-hermes-sidecar-token": token},
        )
        response = connection.getresponse()
        data = response.read(1025)
        if response.status != 200 or len(data) > 1024:
            raise CTOError("plan delivery was rejected or uncertain")
        result = json.loads(data)
        message_id = result.get("messageId")
        if (
            result.get("ok") is not True
            or not isinstance(message_id, str)
            or not 1 <= len(message_id) <= 200
        ):
            raise CTOError("plan delivery acknowledgment is invalid")
        return message_id
    finally:
        connection.close()


def poll(
    *, gateway_dir: Path, registry_path: Path, config_path: Path, sender=_send, prepare_only: bool = False
) -> dict[str, int]:
    """Use the Gateway's lock and journal; one plan and at most one send attempt per task."""
    from alfred.gateway.dispatcher import gateway_lock

    counts = {"planned": 0, "delivered": 0, "existing": 0, "unavailable": 0}
    with gateway_lock(gateway_dir):
        if (gateway_dir / "PAUSE").exists() or (gateway_dir / "STOP").exists():
            return counts
        registry = parse_registry(read_registry_data(registry_path))
        entries = Journal(gateway_dir / "journal.jsonl").entries()
        outcomes = [
            row
            for row in entries
            if row["kind"] == "outcome" and row.get("outcome") == "filed"
        ]
        for row in outcomes:
            try:
                repo, doc, name, raw = _task_for(row, registry)
                spec_hash = hashlib.sha256(raw).hexdigest()
                path = (
                    gateway_dir
                    / "cto-plans"
                    / f"{row['project']}-{row['task_id']}.json"
                )
                if path.exists():
                    old = _load(path)
                    _validate_plan(old)
                    if (
                        old.get("spec_sha256") != spec_hash
                        or old.get("request_id") != row["request_id"]
                    ):
                        raise CTOError("filed task changed after planning")
                    counts["existing"] += 1
                    if old.get("delivery", {}).get("state") != "pending":
                        continue
                    plan = old
                else:
                    evidence = _repo_evidence(repo, name)
                    plan = _central_cto(doc, repo, evidence, spec_hash)
                    _validate_plan(plan)
                    _atomic(path, plan, exclusive=True)
                    counts["planned"] += 1
                if prepare_only:
                    continue
                # A durable attempt marker precedes external I/O. A timeout cannot
                # be retried automatically because the sidecar may have sent it.
                plan["delivery"]["state"] = "attempted_uncertain"
                _atomic(path, plan)
                try:
                    config = _load(config_path)
                    message_id = sender(config, _message(plan))
                    plan["delivery"] = {"state": "delivered", "message_id": message_id}
                    counts["delivered"] += 1
                except (CTOError, OSError, ValueError, TimeoutError):
                    pass
                _atomic(path, plan)
            except (CTOError, OSError, SpecError, RegistryError, ValueError, KeyError):
                counts["unavailable"] += 1
    return counts


def show_plan(gateway_dir: Path, project: str, task_id: str) -> dict:
    """Read the full protected plan for the existing Gateway CLI."""
    if not TASK_ID.fullmatch(task_id) or not re.fullmatch(
        r"[a-z][a-z0-9-]{1,31}", project
    ):
        raise CTOError("valid project and task ID required")
    plan = _load(gateway_dir / "cto-plans" / f"{project}-{task_id}.json")
    _validate_plan(plan)
    if plan["project"] != project or plan["task_id"] != task_id:
        raise CTOError("plan identity mismatch")
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gateway-bound Central CTO planning")
    parser.add_argument("command", choices=("poll", "show"))
    parser.add_argument("task_id", nargs="?")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--project", default="dev-001")
    parser.add_argument(
        "--gateway-dir", type=Path, default=Path.home() / "Alfred/gateway"
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("/home/alfred/Git/alfred/registry/projects.yaml"),
    )
    parser.add_argument(
        "--delivery-config",
        type=Path,
        default=Path.home() / "Alfred/gateway/v1-cto-delivery.json",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "poll":
            print(
                json.dumps(
                    poll(
                        gateway_dir=args.gateway_dir,
                        registry_path=args.registry,
                        config_path=args.delivery_config,
                        prepare_only=args.prepare_only,
                    )
                )
            )
        else:
            if not args.task_id:
                raise CTOError("valid project and task ID required")
            print(
                json.dumps(
                    show_plan(args.gateway_dir, args.project, args.task_id), indent=2
                )
            )
    except (CTOError, OSError, JournalError, RegistryError) as exc:
        print(f"CTO unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
