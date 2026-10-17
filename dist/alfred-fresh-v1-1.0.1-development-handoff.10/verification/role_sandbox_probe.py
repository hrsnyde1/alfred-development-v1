"""One role identity's environment check inside the Evidence sandbox. Read-only.

Started by role_sandbox_preflight.py (root) on stdin, as one role user, inside a
transient unit carrying the Evidence service's own sandbox settings. It checks
what that role's stage reads, may write, and executes; it never reads secrets
aloud, calls a model, pushes, or writes anywhere but a private temporary dir.
Prints one JSON line: {"user", "checks", "failures"}.
"""

import json
import os
import pwd
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

USER = pwd.getpwuid(os.getuid()).pw_name
HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
REPO = Path("/home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo")
VIEW = Path("/run/alfred-fresh-v1-gateway")
LIBRARIES = (
    "/usr/local/lib/alfred-fresh-v1/fresh_v1",
    "/opt/alfred-developer-v1/developer_v1",
    "/opt/alfred-independent-qa-v1/independent_qa",
    "/opt/alfred-reviewer-v1/independent_reviewer",
    "/opt/alfred-draft-pr-publisher-v1",
)
failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(label + (f": {detail}" if detail else ""))


def attempt(label, action):
    try:
        result = action()
    except Exception as exc:  # noqa: BLE001 - report only the type and errno
        check(label, False, f"{type(exc).__name__} errno={getattr(exc, 'errno', None)}")
        return None
    check(label, True)
    return result


def readable_tree(root):
    def walk():
        for directory, dirs, files in os.walk(root, onerror=lambda e: (_ for _ in ()).throw(e)):
            for name in files:
                with open(Path(directory) / name, "rb") as stream:
                    stream.read(1)
    attempt(f"read {root}", walk)


def writable(path):
    check(f"write {path}", os.access(path, os.W_OK), "not writable in sandbox")


def runs(label, args, timeout=30):
    def go():
        proc = subprocess.run(args, capture_output=True, timeout=timeout, check=False,
                              stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin",
                                                             "HOME": str(HOME)})
        if proc.returncode:
            # Exit status and the first stderr words only; no tokens are printed.
            raise RuntimeError(f"exit {proc.returncode}: "
                               + proc.stderr.decode(errors="replace").strip()[:120])
    attempt(label, go)


# Every role: the PAUSE/STOP check, its libraries, the job root and private /tmp.
check("gateway view mounted", VIEW.is_dir())
for name in ("PAUSE", "STOP"):
    attempt(f"observe {name}", lambda name=name: (VIEW / name).exists())
for library in LIBRARIES:
    attempt(f"list {library}", lambda library=library: os.listdir(library))
check("traverse job root", os.access("/var/lib/alfred-v1-handoffs", os.X_OK))
attempt("private /tmp", lambda: tempfile.TemporaryDirectory().cleanup())

if USER == "alfred":
    readable_tree(REPO)
    for path in (REPO, REPO / ".git", "/var/lib/alfred-development-worktrees",
                 "/var/lib/alfred-development-state", "/var/lib/alfred-development-grants",
                 "/home/alfred/Alfred/completion-delivery", "/home/alfred/Alfred/gateway",
                 HOME / ".codex"):
        writable(path)
    attempt("list Gateway sources", lambda: os.listdir("/home/alfred/Git/alfred/src"))
    runs("codex login status", [str(HOME / ".local/bin/codex"), "login", "status"])
elif USER == "alfredqa":
    readable_tree(REPO)
    check("traverse worktree root",
          os.access("/var/lib/alfred-development-worktrees", os.X_OK))
    writable(HOME / ".codex")
    runs("codex login status", [str(HOME / ".local/bin/codex"), "login", "status"])
    runs("bwrap isolated test sandbox", [
        "/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin", "--ro-bind", "/lib", "/lib", "--ro-bind-try", "/lib64",
        "/lib64", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin", "/usr/bin/python3", "-c", "pass"])
elif USER == "alfredreview":
    writable(HOME / ".codex")
    config = Path("/opt/alfred-reviewer-v1/independent_reviewer/config.json")
    cli = attempt("reviewer config", lambda: json.loads(config.read_text())["model"]["cli"])
    if cli:
        runs("codex login status", [cli, "login", "status"])
elif USER == "alfredpublish":
    token = Path("/var/lib/alfred-draft-pr-private/github-token")

    def token_contract():
        info = token.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError(13, "token must be publisher-owned 0600")
        if not token.read_text().strip():
            raise ValueError("empty token")
    attempt("dedicated token file", token_contract)
    attempt("resolve github.com", lambda: socket.getaddrinfo("github.com", 443))
    attempt("reach github.com:443",
            lambda: socket.create_connection(("github.com", 443), timeout=10).close())
    attempt("reach api.github.com:443",
            lambda: socket.create_connection(("api.github.com", 443), timeout=10).close())
    runs("git available", ["/usr/bin/git", "--version"])
else:
    check("known role identity", False, USER)

print(json.dumps({"user": USER, "checks": checks, "failures": failures}))
sys.exit(1 if failures else 0)
