"""Staged worktree invocation and inspectable handoff records.

Only a synthetic backend is supplied here. A host backend must add OS isolation,
trusted authorization and Hermes invocation before any real developer execution.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Protocol

from .router import Denied, ModelChoice, scoped_path


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.file.allow=never",
            "-C",
            str(path),
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )
    if result.returncode:
        raise Denied("git metadata unavailable")
    return result.stdout.rstrip("\n")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(worktree: Path, relative: str) -> Path:
    scoped_path(relative)
    target = worktree / relative
    if target.is_symlink() or any(
        parent.is_symlink() for parent in target.parents if parent != worktree
    ):
        raise Denied("symlink in worktree path")
    if not target.resolve().is_relative_to(worktree.resolve()):
        raise Denied("worktree escape")
    return target


class Worker(Protocol):
    def execute(self, assignment: dict, worktree: Path, model: ModelChoice) -> dict:
        """Return work, tests and model-used evidence; host workers require containment."""


def build_assignments(dispatch: dict, items: list[dict]) -> list[dict]:
    """Compile CTO work items to bounded, nonoverlapping specialist assignments."""
    if not items or type(items) is not list:
        raise Denied("no CTO work items")
    ids = set()
    owners = set()
    result = []
    for item in items:
        if type(item) is not dict or set(item) != {
            "id",
            "specialist",
            "files",
            "depends_on",
            "objective",
        }:
            raise Denied("invalid CTO work item")
        if (
            not isinstance(item["id"], str)
            or not re.fullmatch(r"[a-z0-9_-]{1,64}", item["id"])
            or item["id"] in ids
        ):
            raise Denied("duplicate or invalid work item id")
        ids.add(item["id"])
        if (
            item["specialist"] not in dispatch["specialists"]
            or not isinstance(item["objective"], str)
            or not item["objective"]
        ):
            raise Denied("unapproved specialist or empty objective")
        files = item["files"]
        if type(files) is not list or not files or len(files) != len(set(files)):
            raise Denied("invalid work item files")
        if any(path not in dispatch["scope"] for path in files) or owners.intersection(
            files
        ):
            raise Denied("work items overlap or exceed approval")
        owners.update(files)
        if type(item["depends_on"]) is not list or len(item["depends_on"]) != len(
            set(item["depends_on"])
        ):
            raise Denied("invalid dependencies")
        result.append(
            {**item, "project": dispatch["project"], "task_id": dispatch["task_id"]}
        )
    if {item["specialist"] for item in items} != set(dispatch["specialists"]):
        raise Denied("not all approved specialists have bounded work")
    graph = {item["id"]: item["depends_on"] for item in items}
    if any(dep not in ids for deps in graph.values() for dep in deps):
        raise Denied("missing prerequisite")
    seen = set()
    active = set()

    def visit(node):
        if node in active:
            raise Denied("cyclic specialist dependencies")
        if node in seen:
            return
        active.add(node)
        for dep in graph[node]:
            visit(dep)
        active.remove(node)
        seen.add(node)

    for node in graph:
        visit(node)
    return result


class AssignmentStore:
    """Atomic claim and file-overlap prevention in a protected state directory."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _locked(self):
        handle = (self.root / ".lock").open("a+")
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle

    def claim(self, assignment: dict) -> None:
        key = assignment["id"]
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", key):
            raise Denied("invalid assignment id")
        with self._locked():
            path = self.root / f"{key}.json"
            if path.exists():
                raise Denied("duplicate dispatch")
            files = set(assignment["files"])
            for item in self.root.glob("*.json"):
                prior = json.loads(item.read_text())
                if prior["status"] == "running" and files & set(prior["files"]):
                    raise Denied("concurrent file ownership conflict")
            for prerequisite in assignment.get("depends_on", []):
                previous = self.root / f"{prerequisite}.json"
                if (
                    not previous.exists()
                    or json.loads(previous.read_text())["status"] != "completed"
                ):
                    raise Denied("prerequisite incomplete")
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fd, "w") as stream:
                json.dump(
                    {
                        "status": "running",
                        "files": sorted(files),
                        "task_id": assignment["task_id"],
                    },
                    stream,
                )

    def finish(self, assignment: dict, status: str) -> None:
        with self._locked():
            path = self.root / f"{assignment['id']}.json"
            state = json.loads(path.read_text())
            if state["status"] != "running":
                raise Denied("assignment is not running")
            state["status"] = status
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state))
            os.replace(temporary, path)


def invoke(
    dispatch: dict,
    assignment: dict,
    *,
    worktree: Path,
    model: ModelChoice,
    worker: Worker,
    store: AssignmentStore,
    synthetic: bool = False,
    trusted_authority=None,
    approved_fallback: ModelChoice | None = None,
) -> dict:
    """Invoke only in fixture mode or after protected grant re-verification."""
    if synthetic is not True:
        from .owner_grants import ProtectedDevelopmentAuthority
        if type(trusted_authority) is not ProtectedDevelopmentAuthority:
            raise Denied("protected development authority required")
        expected = {k: dispatch[k] for k in (
            "project", "task_id", "spec_sha256", "plan_sha256", "repository",
            "worktree_root", "scope", "specialists")}
        expected["schema"] = "alfred.development-grant/1"
        expected["specialists"] = sorted(expected["specialists"])
        trusted_authority.verify(dispatch["authorization_reference"], expected)
    if assignment.get("project") != dispatch.get("project") or assignment.get(
        "task_id"
    ) != dispatch.get("task_id"):
        raise Denied("assignment canonical identity mismatch")
    if assignment.get("specialist") not in dispatch.get("specialists", []):
        raise Denied("specialist was not approved")
    files = assignment.get("files")
    if (
        type(files) is not list
        or not files
        or any(f not in dispatch["scope"] for f in files)
    ):
        raise Denied("assignment exceeds approved scope")
    if not worktree.is_absolute() or worktree.is_symlink() or not worktree.is_dir():
        raise Denied("invalid worktree")
    if worktree.parent.resolve() != Path(dispatch["worktree_root"]).resolve():
        raise Denied("worktree outside authorized root")
    if worktree.resolve() == Path(dispatch["repository"]).resolve():
        raise Denied("cannot execute in registered source repository")
    if _git(worktree, "rev-parse", "--is-inside-work-tree") != "true":
        raise Denied("worktree is not git")
    if Path(_git(worktree, "rev-parse", "--show-toplevel")) != worktree.resolve():
        raise Denied("worktree root mismatch")
    repo_path = Path(dispatch["repository"])
    repo_common = (
        repo_path / _git(repo_path, "rev-parse", "--git-common-dir")
    ).resolve()
    worker_common = (
        worktree / _git(worktree, "rev-parse", "--git-common-dir")
    ).resolve()
    if repo_common != worker_common:
        raise Denied("worktree belongs to another repository")
    baseline = _git(worktree, "rev-parse", "HEAD")
    branch = _git(worktree, "branch", "--show-current")
    if not branch or not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise Denied("invalid worktree revision")
    if _git(worktree, "status", "--porcelain"):
        raise Denied("worktree must start clean")
    store.claim(assignment)
    try:
        try:
            result = worker.execute(assignment, worktree, model)
        except Exception as exc:  # noqa: BLE001 - worker failures must become a report
            result = {
                "status": "failed",
                "work_completed": "",
                "tests": [],
                "commits": [],
                "known_limitations": [],
                "blockers": [f"worker exception: {type(exc).__name__}"],
                "actual_model": getattr(worker, "actual_model", None),
            }
        if type(result) is not dict:
            raise Denied("worker result invalid")
        status = result.get("status")
        if status not in {"completed", "blocked", "failed"}:
            raise Denied("worker status invalid")
        changed = [
            line[3:]
            for line in _git(
                worktree, "status", "--porcelain", "--untracked-files=all"
            ).splitlines()
        ]
        committed = _git(worktree, "diff", "--name-only", baseline, "HEAD").splitlines()
        paths = []
        for relative in sorted(set(changed + committed)):
            if " -> " in relative:
                raise Denied("renames are outside V1 staged contract")
            if relative not in files:
                raise Denied("worker changed unassigned file")
            target = _inside(worktree, relative)
            if not target.is_file():
                raise Denied("worker produced unsupported file type")
            paths.append(relative)
        tests = result.get("tests", [])
        if type(tests) is not list or any(
            type(t) is not dict
            or set(t) != {"name", "outcome", "evidence"}
            or t["outcome"] not in {"passed", "failed", "skipped"}
            for t in tests
        ):
            raise Denied("test evidence invalid")
        if status == "completed" and (
            not paths or not tests or any(t["outcome"] == "failed" for t in tests)
        ):
            raise Denied("completed report lacks inspected changes or passing checks")
        actual = result.get("actual_model")
        used_choice = model
        if (approved_fallback is not None and
                actual == {"provider": approved_fallback.provider, "model": approved_fallback.model}):
            used_choice = approved_fallback
        if actual is None and status != "completed":
            used_choice = None
        elif actual != {"provider": used_choice.provider, "model": used_choice.model}:
            raise Denied("actual model evidence mismatch")
        commits = _git(worktree, "rev-list", f"{baseline}..HEAD").splitlines()
        if result.get("commits", []) != commits:
            raise Denied("commit evidence mismatch")
        report = {
            "schema": "alfred.developer-report/1",
            "project": dispatch["project"],
            "task_id": dispatch["task_id"],
            "assignment_id": assignment["id"],
            "specialist": assignment["specialist"],
            "assigned_scope": files,
            "repository": dispatch["repository"],
            "worktree": str(worktree),
            "branch": branch,
            "baseline_revision": baseline,
            "files_modified": [
                {"path": p, "sha256": _hash(_inside(worktree, p))} for p in paths
            ],
            "work_completed": result.get("work_completed", ""),
            "tests": tests,
            "commits": commits,
            "known_limitations": result.get("known_limitations", []),
            "blockers": result.get("blockers", []),
            "status": status,
            "model_used": ({**actual, "reasoning_effort": used_choice.reasoning_effort,
                            "fallback_used": used_choice.fallback_used}
                           if used_choice is not None else None),
            "qa_handoff": {
                "ready": status == "completed",
                "baseline_revision": baseline,
                "changed_file_hashes": {p: _hash(_inside(worktree, p)) for p in paths},
            },
        }
        if status != "completed" and not report["blockers"]:
            raise Denied("failed or blocked work needs blockers")
        store.finish(assignment, status)
        return report
    except Exception:
        store.finish(assignment, "failed")
        raise


def qa_manifest(
    reports: list[dict], assignments: list[dict], final_worktree: Path
) -> dict:
    if not reports or {r["assignment_id"] for r in reports} != {
        a["id"] for a in assignments
    }:
        raise Denied("missing developer reports")
    if any(r["status"] != "completed" or not r["qa_handoff"]["ready"] for r in reports):
        raise Denied("incomplete developer work")
    if len({(r["project"], r["task_id"], r["repository"]) for r in reports}) != 1:
        raise Denied("incoherent final change set")
    if not final_worktree.is_dir() or final_worktree.is_symlink():
        raise Denied("missing final QA snapshot")
    if _git(final_worktree, "status", "--porcelain"):
        raise Denied("final QA snapshot is not committed")
    common = (
        final_worktree / _git(final_worktree, "rev-parse", "--git-common-dir")
    ).resolve()
    repo = Path(reports[0]["repository"])
    if common != (repo / _git(repo, "rev-parse", "--git-common-dir")).resolve():
        raise Denied("final QA snapshot belongs to another repository")
    hashes = {}
    for report in reports:
        for row in report["files_modified"]:
            path = row["path"]
            if path in hashes and hashes[path] != row["sha256"]:
                raise Denied("conflicting developer outputs")
            hashes[path] = row["sha256"]
    for path, expected in hashes.items():
        target = _inside(final_worktree, path)
        if not target.is_file() or _hash(target) != expected:
            raise Denied("developer output missing from final QA snapshot")
    return {
        "schema": "alfred.qa-input/1",
        "project": reports[0]["project"],
        "task_id": reports[0]["task_id"],
        "repository": reports[0]["repository"],
        "developer_reports": reports,
        "final_worktree": str(final_worktree),
        "final_revision": _git(final_worktree, "rev-parse", "HEAD"),
        "changed_file_hashes": hashes,
        "state": "ready_for_independent_qa",
    }
