"""Administrator preflight using the real alfredqa UID and actual OS access.

No protected file is changed: denied write probes use O_WRONLY without
O_TRUNC or O_CREAT. Only the dedicated QA output directory gets a probe file.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import stat
import subprocess
from pathlib import Path

from .worker import verify

PROJECT = "dev-v1-accept"
TASK = "T-0002"
REFERENCE = "445759a699d9423bbb5a8f1dd589689a"
QA_INPUT = Path("/var/lib/alfred-development-state/dev-v1-accept/T-0002/qa-input.json")
REPOSITORY = Path("/home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo")
FINAL = Path("/var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final")
DEVELOPER = Path("/var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-backend-subtract")
REGISTRY = Path("/home/alfred/Git/alfred/registry/projects.yaml")
GATEWAY = Path("/home/alfred/Alfred/gateway")
GRANTS = Path("/var/lib/alfred-development-grants")
STATE = Path("/var/lib/alfred-development-state")
GRANT_FILES = tuple(GRANTS / f"{kind}-{REFERENCE}.json" for kind in
                    ("grant", "challenge", "decision", "issuance", "execution", "execution-result"))
READ_FILES = (QA_INPUT, QA_INPUT.with_name("report-backend-subtract.json"),
              STATE / f"request-{PROJECT}-{TASK}.json", REGISTRY,
              GATEWAY / "cto-plans" / f"{PROJECT}-{TASK}.json",
              REPOSITORY / ".dev/tasks/T-0002-backend-calculator-subtract-helper.md",
              REPOSITORY / "calculator.py", DEVELOPER / "calculator.py", FINAL / "calculator.py",
              *GRANT_FILES)
PROTECTED_DIRS = (STATE, QA_INPUT.parent, GRANTS, GATEWAY, GATEWAY / "cto-plans",
                  REGISTRY.parent, REPOSITORY, REPOSITORY / ".git", DEVELOPER, FINAL)
OTHER_PROJECTS = (Path("/home/alfred/alfred-development-lab/repo"),
                  Path("/home/alfred/alfred-development-lab/worktrees/dev-001"),
                  Path("/home/alfred/Alfred/projects"))
SERVICE_USERS = ("alfredmsg", "alfredphoton", "alfreddev")
ACCESS_SCHEMA = "alfred.qa-effective-access/1"

# This fixed probe runs under the actual target UID. It never creates or writes
# a file; opening with O_WRONLY tests the kernel's effective access decision.
ACCESS_PROBE = r'''
import json, os, sys
out = {}
for item in json.load(sys.stdin):
    path, kind = item
    def opened(flags):
        try:
            fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError:
            return False
        os.close(fd)
        return True
    if kind == "dir":
        out[path] = [os.access(path, os.R_OK, effective_ids=True),
                     os.access(path, os.W_OK, effective_ids=True),
                     os.access(path, os.X_OK, effective_ids=True)]
    else:
        out[path] = [opened(os.O_RDONLY), opened(os.O_WRONLY),
                     os.access(path, os.X_OK, effective_ids=True)]
print(json.dumps(out, sort_keys=True))
'''


def observe_access(paths: tuple[Path, ...], users: tuple[str, ...] = SERVICE_USERS) -> dict:
    items = [[str(path), "dir" if path.is_dir() else "file"] for path in paths]
    access = {}
    for user in users:
        identity = pwd.getpwnam(user)
        prefix = [] if identity.pw_uid == os.geteuid() else ["/usr/sbin/runuser", "-u", user, "--"]
        result = subprocess.run([*prefix, "/usr/bin/python3", "-I", "-c", ACCESS_PROBE], input=json.dumps(items),
                                capture_output=True, text=True, timeout=45, check=False)
        if result.returncode:
            raise RuntimeError(f"effective access probe failed for {user}: {result.stderr[:300]}")
        access[user] = json.loads(result.stdout)
    return {"schema": ACCESS_SCHEMA, "users": list(users), "access": access}


def assert_access_preserved(baseline: dict, actual: dict) -> None:
    if baseline.get("schema") != ACCESS_SCHEMA or actual.get("schema") != ACCESS_SCHEMA or \
            baseline.get("users") != list(SERVICE_USERS) or actual.get("users") != list(SERVICE_USERS):
        raise ValueError("invalid service access baseline")
    if baseline["access"] != actual["access"]:
        differences = []
        for user in SERVICE_USERS:
            old, new = baseline["access"].get(user, {}), actual["access"].get(user, {})
            differences.extend(f"{user}:{path}" for path in sorted(set(old) | set(new)) if old.get(path) != new.get(path))
        raise PermissionError("QA ACL changed service account effective access: " + ", ".join(differences[:12]))


def assert_other_evidence_denied() -> int:
    parents = (STATE, QA_INPUT.parent, GRANTS, GATEWAY / "cto-plans", REGISTRY.parent)
    allowed = set(READ_FILES)
    other = tuple(sorted({path for parent in parents for path in parent.iterdir()
                          if path.is_file() and path not in allowed}))
    access = observe_access(other, ("alfredqa",))["access"]["alfredqa"]
    for path, rights in access.items():
        if rights[0] or rights[1]:
            raise PermissionError(f"QA can read or write unrelated evidence: {path}")
    return len(other)


def child(output_root: Path) -> dict:
    qa = pwd.getpwnam("alfredqa")
    if os.geteuid() != qa.pw_uid:
        raise PermissionError("preflight did not run as alfredqa")
    context = verify(QA_INPUT, QA_INPUT.parent, REGISTRY, GATEWAY, GRANTS)
    if context["revision"] != "89ba188f8a2f801d433a30c9c21363efb3e1043d" or \
            context["commits"] != ["867fde90acf3f0055af79bda53a0fccb55f6bf34"]:
        raise ValueError("T-0002 Git identity mismatch")
    for path in READ_FILES:
        with path.open("rb") as stream:
            stream.read(1)
    denied = []
    for path in READ_FILES:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
        except PermissionError:
            denied.append(str(path))
        else:
            os.close(fd)
            raise PermissionError(f"QA can open protected file for writing: {path}")
    for directory in PROTECTED_DIRS:
        if os.access(directory, os.W_OK, effective_ids=True):
            raise PermissionError(f"QA can write protected directory: {directory}")
    for directory in OTHER_PROJECTS:
        if os.access(directory, os.R_OK, effective_ids=True) or \
                os.access(directory, os.X_OK, effective_ids=True) or \
                os.access(directory, os.W_OK, effective_ids=True):
            raise PermissionError(f"QA can access another project: {directory}")
    root = output_root / PROJECT / TASK
    root.mkdir(parents=True, exist_ok=True)
    probe = root / f".permission-probe-{os.getpid()}"
    fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    probe.unlink()
    groups = set(os.getgroups())
    if 0 in groups or 27 in groups or 1000 in groups:
        raise PermissionError("QA belongs to a privileged or Developer group")
    return {"identity": "alfredqa", "uid": qa.pw_uid, "read_files": len(READ_FILES),
            "write_denied_files": len(denied), "write_denied_directories": len(PROTECTED_DIRS),
            "other_projects_denied": len(OTHER_PROJECTS), "git_revision": context["revision"],
            "qa_output_writable": True, "result": "PASS"}


def administrator(install_root: Path, output_root: Path, baseline_path: Path) -> dict:
    if os.geteuid() != 0:
        raise PermissionError("administrator preflight requires root")
    qa = pwd.getpwnam("alfredqa")
    package = install_root / "independent_qa"
    from .host_release import PACKAGE_FILES, verify as verify_release
    release_sha = verify_release(package)
    for path in (install_root, package, package / "schemas", *(package / name for name in PACKAGE_FILES),
                 package / "release.sha256"):
        info = path.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise PermissionError(f"QA installation is not root-owned and read-only: {path}")
    output_info = output_root.stat()
    if output_info.st_uid != qa.pw_uid or stat.S_IMODE(output_info.st_mode) != 0o700:
        raise PermissionError("QA output root must be private to alfredqa")
    baseline_info = baseline_path.lstat()
    if baseline_info.st_uid != 0 or stat.S_IMODE(baseline_info.st_mode) != 0o600 or \
            not stat.S_ISREG(baseline_info.st_mode):
        raise PermissionError("service access baseline is not root-private")
    baseline = json.loads(baseline_path.read_text())
    first_user = SERVICE_USERS[0]
    paths = tuple(Path(path) for path in baseline["access"][first_user])
    assert_access_preserved(baseline, observe_access(paths))
    unrelated_denied = assert_other_evidence_denied()
    result = subprocess.run(["/usr/sbin/runuser", "-u", "alfredqa", "--", "/usr/bin/env",
                             f"PYTHONPATH={install_root}", "/usr/bin/python3", "-B", "-m",
                             "independent_qa.host_preflight", "--child", "--output-root", str(output_root)],
                            capture_output=True, text=True, timeout=45, check=False)
    if result.returncode:
        raise RuntimeError("QA identity preflight failed: " + (result.stderr or result.stdout)[:1200])
    child_result = json.loads(result.stdout)
    child_result["release_manifest_sha256"] = release_sha
    child_result["service_effective_access_preserved"] = list(SERVICE_USERS)
    child_result["unrelated_evidence_denied"] = unrelated_denied
    return child_result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--install-root", type=Path, default=Path("/opt/alfred-independent-qa-v1"))
    parser.add_argument("--output-root", type=Path, default=Path("/var/lib/alfred-independent-qa-state"))
    parser.add_argument("--baseline", type=Path, help="protected pre-ACL effective-access snapshot")
    args = parser.parse_args()
    if not args.child and args.baseline is None:
        parser.error("--baseline is required for administrator preflight")
    result = child(args.output_root) if args.child else administrator(args.install_root, args.output_root, args.baseline)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
