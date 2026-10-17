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
            "git_revision": context["revision"], "qa_output_writable": True, "result": "PASS"}


def administrator(install_root: Path, output_root: Path) -> dict:
    if os.geteuid() != 0:
        raise PermissionError("administrator preflight requires root")
    qa = pwd.getpwnam("alfredqa")
    package = install_root / "independent_qa"
    from .host_release import PACKAGE_FILES, verify as verify_release
    release_sha = verify_release(package)
    for path in (install_root, package, *(package / name for name in PACKAGE_FILES), package / "release.sha256"):
        info = path.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise PermissionError(f"QA installation is not root-owned and read-only: {path}")
    output_info = output_root.stat()
    if output_info.st_uid != qa.pw_uid or stat.S_IMODE(output_info.st_mode) != 0o700:
        raise PermissionError("QA output root must be private to alfredqa")
    result = subprocess.run(["/usr/sbin/runuser", "-u", "alfredqa", "--", "/usr/bin/env",
                             f"PYTHONPATH={install_root}", "/usr/bin/python3", "-B", "-m",
                             "independent_qa.host_preflight", "--child", "--output-root", str(output_root)],
                            capture_output=True, text=True, timeout=45, check=False)
    if result.returncode:
        raise RuntimeError("QA identity preflight failed: " + (result.stderr or result.stdout)[:1200])
    child_result = json.loads(result.stdout)
    child_result["release_manifest_sha256"] = release_sha
    return child_result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--install-root", type=Path, default=Path("/opt/alfred-independent-qa-v1"))
    parser.add_argument("--output-root", type=Path, default=Path("/var/lib/alfred-independent-qa-state"))
    args = parser.parse_args()
    result = child(args.output_root) if args.child else administrator(args.install_root, args.output_root)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
