"""One bounded worker for every Developer V1 specialty.

The model broker sees scoped source text and returns file contents. It never
receives a writable repository mount. Checks run without network in bubblewrap.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .execution import _git, _inside
from .router import Denied, ModelChoice, ProviderUnavailable

MAX_SOURCE = 65536
MAX_OUTPUT = 131072


def _json_or_none(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None
PROVIDER = "codex"


class CodexReadOnlyBroker:
    """Uses existing Codex authentication; never copies tokens to the worker."""

    def __init__(self, *, executable: str | None = None, timeout: int = 180):
        # sudo may supply a restricted PATH. Resolve the installed CLI from
        # the runner UID, not the caller's HOME or Personal Alfred's config.
        home = Path(pwd.getpwuid(os.geteuid()).pw_dir)
        self.executable = executable or str(home / ".local/bin/codex")
        self._resolved_executable: str | None = None
        self.timeout = timeout

    def require_executable(self) -> str:
        """Pin one executable for both auth and generation before grant claim."""
        if self._resolved_executable is not None:
            return self._resolved_executable
        candidate = Path(self.executable)
        if not candidate.is_absolute():
            raise Denied("Codex executable path must be absolute")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise Denied("Codex executable unavailable at configured path") from exc
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise Denied("Codex executable unavailable at configured path")
        self._resolved_executable = str(resolved)
        return self._resolved_executable

    def authenticated(self) -> bool:
        try:
            result = subprocess.run([self.require_executable(), "login", "status"],
                                    capture_output=True, text=True, timeout=15, check=False)
        except OSError as exc:
            raise Denied("Codex executable unavailable during authentication") from exc
        return result.returncode == 0 and "Logged in" in result.stdout + result.stderr

    def generate(self, choice: ModelChoice, *, objective: str, sources: dict[str, str]) -> dict:
        if choice.provider != PROVIDER or not choice.model or not self.authenticated():
            raise ProviderUnavailable("configured Codex route is not authenticated")
        payload = {"objective": objective, "files": sources,
                   "instructions": "Return JSON only. edits must contain complete replacement UTF-8 text for files that need changes. Do not add paths outside files. Keep the change minimal."}
        prompt = json.dumps(payload, ensure_ascii=False)
        with tempfile.TemporaryDirectory(prefix="alfred-model-") as temporary:
            # An empty cwd means the model has no project worktree to edit.
            command = [self.require_executable(), "exec", "--ignore-user-config", "--ignore-rules",
                       "--disable", "shell_tool", "--disable", "unified_exec",
                       "--disable", "browser_use", "--disable", "apps",
                       "--disable", "code_mode_host",
                       "--model", choice.model, "--sandbox", "read-only", "--ephemeral",
                       "--skip-git-repo-check", "--json", "--output-schema",
                       str(Path(__file__).parent / "schemas" / "model-edits.schema.json"), "-C", temporary,
                       "-c", f'model_reasoning_effort="{choice.reasoning_effort}"', prompt]
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=self.timeout, check=False, stdin=subprocess.DEVNULL)
        if result.returncode:
            diagnostic = (result.stderr + result.stdout).lower()
            if any(term in diagnostic for term in ("unavailable", "not found", "rate limit", "unauthorized", "authentication", "overloaded")):
                raise ProviderUnavailable("approved model unavailable")
            raise Denied("model invocation failed")
        if len(result.stdout) > MAX_OUTPUT:
            raise Denied("model response too large")
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        if not any(event.get("type") == "turn.completed" for event in events):
            raise Denied("model invocation lacks completion evidence")
        answers = [event["item"]["text"] for event in events
                   if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message"]
        if not answers:
            raise Denied("model produced ambiguous response")
        # Codex may send progress notes (e.g. {"status": ...}) before its schema-bound
        # final message. Exactly one message may carry the edit contract, and it must
        # be the final one; a second contract-shaped message stays ambiguous.
        decoded = [_json_or_none(text) for text in answers]
        contract = [i for i, answer in enumerate(decoded) if type(answer) is dict
                    and set(answer) == {"edits", "summary"}]
        if len(contract) > 1:
            raise Denied("model produced ambiguous response")
        if not contract or contract[0] != len(answers) - 1:
            if decoded[-1] is None:
                raise Denied("model response is not JSON")
            raise Denied("model edit contract invalid")
        answer = decoded[-1]
        if type(answer["edits"]) is not list:
            raise Denied("model edit contract invalid")
        return answer


def _check_command(command: list[str]) -> list[str]:
    allowed = (
        ["/usr/bin/python3", "-m", "unittest", "discover", "-v"],
        ["/usr/bin/python3", "-m", "compileall", "-q", "."],
    )
    if command not in allowed:
        raise Denied("check command is not approved")
    return command


def _sandbox_base(worktree: Path, *, writable: bool) -> list[str]:
    if not shutil.which("bwrap"):
        raise Denied("bubblewrap isolation unavailable")
    if not worktree.is_dir() or worktree.is_symlink():
        raise Denied("invalid isolated worktree")
    return ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin", "--ro-bind", "/lib", "/lib",
            "--ro-bind-try", "/lib64", "/lib64", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp", "--bind" if writable else "--ro-bind",
            str(worktree), "/workspace", "--chdir", "/workspace",
            "--clearenv", "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/usr/bin:/bin",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1"]


def run_check(worktree: Path, command: list[str], *, timeout: int = 60) -> dict:
    _check_command(command)
    sandbox = [*_sandbox_base(worktree, writable=False), *command]
    result = subprocess.run(sandbox, capture_output=True, text=True, timeout=timeout,
                            check=False, stdin=subprocess.DEVNULL)
    evidence = (result.stdout + result.stderr)[:8192]
    return {"name": " ".join(command), "outcome": "passed" if result.returncode == 0 else "failed",
            "evidence": f"exit={result.returncode}; {evidence}"}


def apply_edits(worktree: Path, edits: list[dict], allowed: list[str]) -> None:
    """Only /workspace is writable in the code-writing child mount namespace."""
    packet = json.dumps({"allowed": allowed, "edits": edits}).encode()
    if len(packet) > MAX_OUTPUT:
        raise Denied("edit packet too large")
    script = Path(__file__).parent / "isolated_apply.py"
    base = _sandbox_base(worktree, writable=True)
    command = [*base[:2], "--dir", "/agent", "--ro-bind", str(script), "/agent/apply.py",
               *base[2:], "/usr/bin/python3", "-I", "/agent/apply.py"]
    result = subprocess.run(command, input=packet, capture_output=True, timeout=30,
                            check=False, env={"PATH": "/usr/bin:/bin"})
    if result.returncode:
        raise Denied("isolated edit applier refused or unavailable")


class DeveloperWorker:
    def __init__(self, broker: CodexReadOnlyBroker, *, objective: str,
                 checks: list[list[str]], fallback: ModelChoice | None = None):
        self.broker, self.objective, self.checks, self.fallback = broker, objective, checks, fallback
        self.actual_model = None
        for command in checks:
            _check_command(command)

    def execute(self, assignment: dict, worktree: Path, model: ModelChoice) -> dict:
        files = assignment["files"]
        baseline = _git(worktree, "rev-parse", "HEAD")
        if not {"read_scoped", "write_scoped", "run_approved_check"} <= set(model.tools):
            raise Denied("model route lacks developer tools")
        sources = {}
        for relative in files:
            target = _inside(worktree, relative)
            if target.exists():
                if not target.is_file() or target.stat().st_size > MAX_SOURCE:
                    raise Denied("source file unavailable or too large")
                sources[relative] = target.read_text(encoding="utf-8")
            else:
                sources[relative] = ""
        if sum(len(value.encode()) for value in sources.values()) > MAX_SOURCE:
            raise Denied("assignment source exceeds model budget")
        actual = model
        try:
            response = self.broker.generate(model, objective=self.objective, sources=sources)
        except ProviderUnavailable:
            if self.fallback is None:
                raise
            actual = self.fallback
            response = self.broker.generate(actual, objective=self.objective, sources=sources)
        self.actual_model = {"provider": actual.provider, "model": actual.model}
        edits = response["edits"]
        if not edits or len(edits) > len(files):
            raise Denied("model supplied no bounded edits")
        seen = set()
        for edit in edits:
            if (type(edit) is not dict or set(edit) != {"path", "content"}
                    or edit["path"] not in files or edit["path"] in seen
                    or type(edit["content"]) is not str or len(edit["content"].encode()) > MAX_SOURCE):
                raise Denied("model edit exceeds assignment")
            seen.add(edit["path"])
            _inside(worktree, edit["path"])
        apply_edits(worktree, edits, files)
        tests = [run_check(worktree, command) for command in self.checks]
        status = "completed" if tests and all(t["outcome"] == "passed" for t in tests) else "failed"
        commits = []
        if status == "completed" and "git_local_commit_if_granted" in actual.tools:
            changed = [line[3:] for line in _git(worktree, "status", "--porcelain",
                                                   "--untracked-files=all").splitlines()]
            if any(path not in files for path in changed):
                raise Denied("unassigned file changed before local commit")
            _git(worktree, "add", "--", *sorted(seen))
            subprocess.run(["git", "-C", str(worktree), "-c", "core.hooksPath=/dev/null",
                            "-c", "user.name=Alfred Developer", "-c", "user.email=developer@localhost",
                            "commit", "-qm", f"{assignment['task_id']}: {assignment['id']}",
                            "--only", "--", *sorted(seen)],
                           check=True, timeout=20, env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
                                                        "GIT_CONFIG_NOSYSTEM": "1"})
            commits = _git(worktree, "rev-list", f"{baseline}..HEAD").splitlines()
        return {"status": status, "work_completed": str(response["summary"])[:2000],
                "tests": tests, "commits": commits, "known_limitations": [],
                "blockers": [] if status == "completed" else ["approved check failed"],
                "actual_model": {"provider": actual.provider, "model": actual.model}}


def create_worktree(repository: Path, root: Path, project: str, task_id: str,
                    assignment_id: str, start_revision: str | None = None) -> Path:
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", assignment_id):
        raise Denied("invalid assignment ID")
    if root.is_symlink() or not root.is_dir() or repository.is_symlink():
        raise Denied("invalid worktree binding")
    destination = root / f"{project}-{task_id}-{assignment_id}"
    if destination.exists() or destination.is_symlink():
        raise Denied("assignment worktree already exists")
    branch = f"developer/{project}-{task_id}-{assignment_id}"
    subprocess.run(["git", "-C", str(repository), "-c", "core.hooksPath=/dev/null",
                    "worktree", "add", "-q", "-b", branch, str(destination),
                    *([start_revision] if start_revision else [])],
                   check=True, timeout=20, env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
                                                "GIT_CONFIG_NOSYSTEM": "1"})
    return destination
