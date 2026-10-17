"""Parse, render and validate Alfred task specs (.dev/tasks/T-NNNN-<slug>.md).

A spec is YAML frontmatter plus fixed `## ` sections. Its normalised form (a dict of the
frontmatter fields plus `sections`) is what `.dev/schema/task.schema.json` describes, so
Alfred can also send specs as JSON.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from alfred.gateway.permitted_paths import PermittedPathsError, parse_permitted_paths

ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = ROOT / ".dev" / "tasks"
SCHEMA_PATH = ROOT / ".dev" / "schema" / "task.schema.json"

REPO_COMPANY = "alfred"
MAX_BYTES = 64 * 1024

SECTIONS: dict[str, str] = {
    "Objective": "objective",
    "Scope": "scope",
    "Requirements": "requirements",
    "Constraints": "constraints",
    "Acceptance criteria": "acceptance_criteria",
    "Security considerations": "security_considerations",
    "Testing requirements": "testing_requirements",
    "Permitted paths": "permitted_paths",
    "Implementation notes": "implementation_notes",
    "Log": "log",
}
# Optional body sections (ADR 0008): absent from `sections` when a spec has none, so the spec
# hash of every spec written before the section existed is unchanged.
OPTIONAL_SECTIONS = frozenset({"permitted_paths"})
FRONTMATTER_ORDER = (
    "id",
    "title",
    "status",
    "source",
    "risk",
    "company",
    "created",
    "approved_by",
    "branch",
    "pr",
    "project",
    "request_id",
)
# Optional frontmatter keys (gateway specs only); rendered only when set.
OPTIONAL_KEYS = ("project", "request_id")
APPROVED_STATUSES = {"ready", "in_progress", "in_review", "pr_open", "done"}
FILENAME_RE = re.compile(r"^(T-\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
PROTECTED_MENTION = re.compile(
    r"(\.claude\b|\.github\b|\.dev/(schema|bin|security)|CLAUDE\.md|\.mcp\.json"
    r"|src/alfred/(gateway|registry)|tests/(gateway|security|registry|dev)"
    r"|pyproject\.toml|uv\.lock|\.gitattributes|\.gitmodules"
    r"|docs/(secrets|branch-protection)\.md"
    r"|src/alfred/__init__\.py|pytest\.(ini|toml)|ruff\.toml|mypy\.ini|setup\.cfg|tox\.ini|uv\.toml|(site|user)customize\.py|\.pth\b|conftest\.py"
    r"|guard\.py|branch protection|CODEOWNERS|permission|hook|\bregistry\b)",
    re.IGNORECASE,
)


class SpecError(ValueError):
    """Raised when a spec cannot be parsed at all."""


def parse(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise SpecError(f"spec is larger than {MAX_BYTES} bytes")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise SpecError("missing YAML frontmatter between '---' lines")
    front = yaml.safe_load(match.group(1)) or {}
    if not isinstance(front, dict):
        raise SpecError("frontmatter must be a mapping")
    doc: dict[str, Any] = {
        k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in front.items()
    }
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in match.group(2).splitlines():
        heading = re.match(r"^## (.+?)\s*$", line)
        if heading:
            if current:
                sections[current] = "\n".join(lines).strip()
            title = heading.group(1)
            if title not in SECTIONS:
                raise SpecError(f"unknown section '## {title}'")
            current = SECTIONS[title]
            if current in sections:
                raise SpecError(f"duplicate section '## {title}'")
            lines = []
        elif current:
            lines.append(line)
        elif line.strip():
            raise SpecError("text before the first '## ' section")
    if current:
        sections[current] = "\n".join(lines).strip()
    doc["sections"] = sections
    return doc


def render(doc: dict[str, Any]) -> str:
    front = {
        k: doc.get(k) for k in FRONTMATTER_ORDER if k not in OPTIONAL_KEYS or doc.get(k) is not None
    }
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
    body = "\n\n".join(
        f"## {title}\n{doc['sections'].get(key, '')}"
        for title, key in SECTIONS.items()
        if key not in OPTIONAL_SECTIONS or doc["sections"].get(key)
    )
    return f"---\n{head}\n---\n\n{body}\n"


def load_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema


def validate(
    doc: dict[str, Any], filename: str | None = None, company: str = REPO_COMPANY
) -> list[str]:
    """Return every problem with `doc`. `company` is the target repository's company."""
    validator = Draft202012Validator(load_schema())
    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
        for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]
    if filename is not None:
        m = FILENAME_RE.match(filename)
        if not m:
            errors.append(f"filename '{filename}' must look like T-NNNN-short-slug.md")
        elif m.group(1) != doc.get("id"):
            errors.append(f"filename id {m.group(1)} does not match id {doc.get('id')}")
    sections = doc.get("sections")
    if isinstance(sections, dict) and "permitted_paths" in sections:
        try:
            parse_permitted_paths(str(sections["permitted_paths"]))
        except PermittedPathsError as exc:
            errors.append(f"permitted_paths: {exc}")
    status = doc.get("status")
    if status in APPROVED_STATUSES:
        if doc.get("approved_by") != "hrsnyde1":
            errors.append(f"status '{status}' requires approved_by: hrsnyde1")
        if doc.get("risk") is None:
            errors.append(f"status '{status}' requires risk to be assessed")
    if status in {"in_progress", "in_review", "pr_open", "done"} and not doc.get("branch"):
        errors.append(f"status '{status}' requires branch")
    if status in {"pr_open", "done"} and not doc.get("pr"):
        errors.append(f"status '{status}' requires pr")
    if doc.get("company") not in (None, company):
        errors.append(
            f"company '{doc.get('company')}' does not belong in this repository ({company})"
        )
    return errors


def validate_file(path: Path) -> list[str]:
    try:
        doc = parse(path.read_text(encoding="utf-8"))
    except (SpecError, yaml.YAMLError, UnicodeDecodeError) as exc:
        return [str(exc)]
    return validate(doc, path.name)


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return "-".join(slug.split("-")[:6]) or "task"


def next_id(tasks_dir: Path = TASKS_DIR) -> str:
    """Allocate above checkout, branch, worktree and protected reservation IDs.

    Callers must hold an exclusive lock on ``tasks_dir`` through publication. A
    stale or unreadable Git view fails closed; this function never fetches refs.
    """
    repo = tasks_dir.parent.parent
    numbers = _task_numbers(tasks_dir)
    numbers.update(_reservation_numbers(repo / ".dev" / "task-id-reservations.txt"))
    if (repo / ".git").exists():
        top = Path(_git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
        if top != repo.resolve():
            raise SpecError("task directory is not at the Git repository root")
        refs = _git(
            repo,
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            "refs/heads",
            "refs/remotes",
        ).splitlines()
        commits: set[str] = set()
        for line in refs:
            try:
                ref, oid = line.rsplit(" ", 1)
            except ValueError as exc:
                raise SpecError("malformed Git ref") from exc
            numbers.update(int(m.group(1)) for m in re.finditer(r"T-([0-9]{4})(?![0-9])", ref))
            if not re.fullmatch(r"[0-9a-f]{40,64}", oid):
                raise SpecError("malformed Git object ID")
            commits.add(oid)
        for oid in commits:
            names = _git(repo, "ls-tree", "-r", "--name-only", oid, "--", ".dev/tasks")
            numbers.update(_numbers_in_names(names.splitlines()))
            reservations = _git(
                repo, "show", f"{oid}:.dev/task-id-reservations.txt", missing_ok=True
            )
            numbers.update(_reservation_text(reservations))
        for line in _git(repo, "worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                worktree = Path(line[9:])
                work_tasks = worktree / ".dev" / "tasks"
                if not work_tasks.is_dir() or work_tasks.is_symlink():
                    raise SpecError("unreadable worktree task directory")
                numbers.update(_task_numbers(work_tasks))
                numbers.update(_reservation_numbers(worktree / ".dev" / "task-id-reservations.txt"))
    candidate = max(numbers, default=0) + 1
    if candidate > 9999:
        raise SpecError("task ID space exhausted")
    return f"T-{candidate:04d}"


def _task_numbers(tasks_dir: Path) -> set[int]:
    return _numbers_in_names(p.name for p in tasks_dir.glob("T-[0-9][0-9][0-9][0-9]-*.md"))


def _numbers_in_names(names: Any) -> set[int]:
    return {
        int(m.group(1))
        for name in names
        if (m := re.search(r"(?:^|/)T-([0-9]{4})-[a-z0-9-]+\.md$", name))
    }


def _reservation_text(text: str) -> set[int]:
    numbers: set[int] = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            if not re.fullmatch(r"T-[0-9]{4}", line):
                raise SpecError("malformed task ID reservation")
            numbers.add(int(line[2:]))
    return numbers


def _reservation_numbers(path: Path) -> set[int]:
    if path.is_symlink():
        raise SpecError("unsafe task ID reservations")
    if not path.exists():
        return set()
    if path.stat().st_size > 16 * 1024:
        raise SpecError("unsafe task ID reservations")
    return _reservation_text(path.read_text(encoding="utf-8"))


def _git(repo: Path, *args: str, missing_ok: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": "/nonexistent",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_OPTIONAL_LOCKS": "0",
            },
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SpecError("cannot inspect Git task IDs") from exc
    if result.returncode:
        if missing_ok and "does not exist" in result.stderr:
            return ""
        raise SpecError("cannot inspect Git task IDs")
    return result.stdout


def mentions_protected(doc: dict[str, Any]) -> bool:
    text = (
        " ".join(str(v) for v in doc.get("sections", {}).values()) + " " + str(doc.get("title", ""))
    )
    return bool(PROTECTED_MENTION.search(text))
