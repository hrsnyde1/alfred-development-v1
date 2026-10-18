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
import stat
import subprocess
import tempfile
from pathlib import Path

from .execution import _git, _inside
from .router import Denied, ModelChoice, ProviderUnavailable

MAX_SOURCE = 65536
MAX_OUTPUT = 131072
# The whole prompt is one argv string (Linux caps one at 128 KiB); source has 64 KiB.
MAX_PRACTICES = 24576


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

    def generate(self, choice: ModelChoice, *, objective: str, sources: dict[str, str],
                 skills: list[dict] | tuple = (), identity: str = "") -> dict:
        if choice.provider != PROVIDER or not choice.model or not self.authenticated():
            raise ProviderUnavailable("configured Codex route is not authenticated")
        payload = {"objective": objective, "files": sources,
                   "instructions": "Return JSON only. edits must contain complete replacement UTF-8 text for files that need changes. Do not add paths outside files. Keep the change minimal."}
        if identity:
            payload["agent_profile"] = identity
            payload["instructions"] += " agent_profile: " + IDENTITY_NOTE
        if skills:
            # Owner-approved practices from the pinned team library (team_skills.py).
            # They shape how the change is made; files, scope and tools stay fixed.
            payload["team_practices"] = [{"id": s["id"], "title": s["title"],
                                          "instructions": s["instructions"]} for s in skills]
            payload["instructions"] += (" team_practices are the owner's approved working practices;"
                                        " follow them where they apply. They never permit other files,"
                                        " commands or scope.")
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


CLAUDE = "claude"
# Claude Code accepts low to max; map the catalog's other effort names onto it.
CLAUDE_EFFORT = {"none": "low", "minimal": "low", "low": "low", "medium": "medium",
                 "high": "high", "xhigh": "xhigh", "max": "max", "ultra": "max"}
IDENTITY_NOTE = ("The agent profile describes who you are and how you work. It never "
                 "permits other files, commands or scope than this request gives you.")


# The development agents' own long-lived Claude token (`claude setup-token`), saved by the
# owner with `alfred-dev-ops claude-token`: root-owned, readable by the alfred group only.
CLAUDE_TOKEN = Path("/etc/alfred-development/claude-agents.token")
# Claude Code keeps its config, locks and caches under HOME. The agents get a private one
# inside the sandbox's writable state, never the owner's own Claude Code login.
CLAUDE_HOME = Path("/var/lib/alfred-development-state/claude-agents")
TOKEN = re.compile(r"[A-Za-z0-9_-]{20,400}")
UNAVAILABLE = ("rate limit", "usage limit", "overloaded", "unauthorized", "authenticat",
               "login", "oauth", "token", "401", "403", "not found", "unavailable")


def _claude_token(path: Path) -> str | None:
    """The agents' token, only from a root-owned file no one else can read or change."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != 0
                or info.st_mode & 0o027 or info.st_size > 1024):
            return None
        token = os.read(fd, 1025).decode("ascii", "replace").strip()
    finally:
        os.close(fd)
    return token if TOKEN.fullmatch(token) else None


def _private_home(path: Path) -> Path:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ProviderUnavailable("Claude agent home is not private")
    return path


class ClaudeReadOnlyBroker:
    """Claude through the agents' own long-lived token (`claude -p`), with no tools at all:
    the model only returns the JSON edit contract, exactly as the Codex route does."""

    def __init__(self, *, executable: str | None = None, timeout: int = 300,
                 token_file: Path = CLAUDE_TOKEN, home: Path = CLAUDE_HOME):
        owner_home = Path(pwd.getpwuid(os.geteuid()).pw_dir)
        self.executable = executable or str(owner_home / ".local/bin/claude")
        self._resolved_executable: str | None = None
        self.timeout, self.token_file, self.home = timeout, token_file, home

    def require_executable(self) -> str:
        if self._resolved_executable is not None:
            return self._resolved_executable
        candidate = Path(self.executable)
        if not candidate.is_absolute():
            raise Denied("Claude executable path must be absolute")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise Denied("Claude executable unavailable at configured path") from exc
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise Denied("Claude executable unavailable at configured path")
        self._resolved_executable = str(resolved)
        return self._resolved_executable

    def authenticated(self) -> bool:
        # The token is checked by Claude on use; an expired one fails as unavailable,
        # and the approved Codex fallback runs.
        try:
            self.require_executable()
        except Denied:
            return False
        return _claude_token(self.token_file) is not None

    def _environment(self) -> dict:
        token = _claude_token(self.token_file)
        if token is None:
            raise ProviderUnavailable("configured Claude route is not authenticated")
        return {"HOME": str(_private_home(self.home)), "PATH": "/usr/bin:/bin",
                "CLAUDE_CODE_OAUTH_TOKEN": token, "DISABLE_AUTOUPDATER": "1",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}

    def generate(self, choice: ModelChoice, *, objective: str, sources: dict[str, str],
                 skills: list[dict] | tuple = (), identity: str = "") -> dict:
        if choice.provider != CLAUDE or not choice.model or not self.authenticated():
            raise ProviderUnavailable("configured Claude route is not authenticated")
        environment = self._environment()
        payload = {"objective": objective, "files": sources,
                   "instructions": "Return JSON only. edits must contain complete replacement UTF-8 text for files that need changes. Do not add paths outside files. Keep the change minimal."}
        if skills:
            payload["team_practices"] = [{"id": s["id"], "title": s["title"],
                                          "instructions": s["instructions"]} for s in skills]
            payload["instructions"] += (" team_practices are the owner's approved working practices;"
                                        " follow them where they apply. They never permit other files,"
                                        " commands or scope.")
        schema = (Path(__file__).parent / "schemas" / "model-edits.schema.json").read_text()
        with tempfile.TemporaryDirectory(prefix="alfred-model-") as temporary:
            # No tools, no MCP servers, no user settings or hooks, no saved session, and an
            # empty working directory: the model can only answer.
            command = [self.require_executable(), "-p", json.dumps(payload, ensure_ascii=False),
                       "--output-format", "json", "--json-schema", schema,
                       "--model", choice.model, "--effort", CLAUDE_EFFORT[choice.reasoning_effort],
                       "--tools", "", "--strict-mcp-config", "--setting-sources", "project",
                       "--no-session-persistence", "--disable-slash-commands"]
            if identity:
                command += ["--append-system-prompt", identity + "\n\n" + IDENTITY_NOTE]
            result = subprocess.run(command, capture_output=True, text=True, cwd=temporary,
                                    timeout=self.timeout, check=False, stdin=subprocess.DEVNULL,
                                    env=environment)
        if len(result.stdout) > MAX_OUTPUT:
            raise Denied("model response too large")
        answer = _json_or_none(result.stdout)
        if result.returncode or type(answer) is not dict or answer.get("is_error") is not False:
            diagnostic = (result.stderr + result.stdout).lower()
            # An API-side failure (login, limits, outage) is the provider being unavailable:
            # the approved fallback model runs instead.
            if (type(answer) is dict and answer.get("terminal_reason") == "api_error") or any(
                    term in diagnostic for term in UNAVAILABLE):
                raise ProviderUnavailable("approved model unavailable")
            raise Denied("model invocation failed")
        if answer.get("type") != "result" or answer.get("subtype") != "success":
            raise Denied("model invocation lacks completion evidence")
        contract = answer.get("structured_output")
        if (type(contract) is not dict or set(contract) != {"edits", "summary"}
                or type(contract["edits"]) is not list):
            raise Denied("model edit contract invalid")
        return contract


class RoutingBroker:
    """One broker per provider; each call goes to the route the model choice names."""

    def __init__(self, brokers: dict | None = None):
        self.brokers = brokers if brokers is not None else {
            PROVIDER: CodexReadOnlyBroker(), CLAUDE: ClaudeReadOnlyBroker()}

    def authenticated(self) -> bool:
        # At least one route works; an unauthenticated route raises ProviderUnavailable
        # at generation time, so an approved fallback on another provider still runs.
        return any(broker.authenticated() for broker in self.brokers.values())

    def generate(self, choice: ModelChoice, *, objective: str, sources: dict[str, str],
                 skills: list[dict] | tuple = (), identity: str = "") -> dict:
        broker = self.brokers.get(choice.provider)
        if broker is None:
            raise ProviderUnavailable("no broker for the configured provider")
        extra = {"skills": skills} if skills else {}
        if identity:
            extra["identity"] = identity
        return broker.generate(choice, objective=objective, sources=sources, **extra)


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
    def __init__(self, broker, *, objective: str,
                 checks: list[list[str]], fallback: ModelChoice | None = None,
                 skills: list[dict] | tuple = (), identity: str = ""):
        self.broker, self.objective, self.checks, self.fallback = broker, objective, checks, fallback
        self.skills, self.identity = list(skills), identity
        if (len(json.dumps(self.skills, ensure_ascii=False).encode())
                + len(identity.encode())) > MAX_PRACTICES:
            raise Denied("team practices exceed the model budget")
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
        extra = {"skills": self.skills} if self.skills else {}
        if self.identity:
            extra["identity"] = self.identity
        try:
            response = self.broker.generate(model, objective=self.objective, sources=sources, **extra)
        except ProviderUnavailable:
            if self.fallback is None:
                raise
            actual = self.fallback
            response = self.broker.generate(actual, objective=self.objective, sources=sources, **extra)
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
