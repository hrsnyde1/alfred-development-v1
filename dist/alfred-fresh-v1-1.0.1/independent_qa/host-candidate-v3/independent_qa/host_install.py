"""One-shot root installation; no systemd unit is created or restarted."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import stat
import subprocess
import time
from pathlib import Path

from .host_preflight import (DEVELOPER, FINAL, GATEWAY, GRANT_FILES, GRANTS, QA_INPUT,
                             READ_FILES, REGISTRY, REPOSITORY, STATE, administrator)
from .host_release import PACKAGE_FILES, verify as verify_release

INSTALL = Path("/opt/alfred-independent-qa-v1")
OUTPUT = Path("/var/lib/alfred-independent-qa-state")
BACKUPS = Path("/var/lib/alfred-independent-qa-backups")

TRAVERSE = (
    Path("/home/alfred"), Path("/home/alfred/Git"), Path("/home/alfred/Git/alfred"),
    REGISTRY.parent, Path("/home/alfred/Alfred"), GATEWAY, GATEWAY / "cto-plans",
    Path("/home/alfred/alfred-development-lab"),
    Path("/home/alfred/alfred-development-lab/milestone2"),
    Path("/home/alfred/alfred-development-lab/milestone2/task-a"),
    Path("/home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance"),
    STATE, STATE / "dev-v1-accept", QA_INPUT.parent,
    GRANTS, FINAL.parent,
)
TREES = (REPOSITORY, DEVELOPER, FINAL)
EXACT_READ = tuple(path for path in READ_FILES if not any(path.is_relative_to(tree) for tree in TREES))


def command(*args: str, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(args, input=input_data, capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[:300].decode('utf-8', 'replace')}")
    return result.stdout


def stage_copy(release: Path, target: Path, expected_sha: str) -> str:
    if target.exists():
        raise FileExistsError(target)
    verify_release(release, expected_sha)
    package = target / "independent_qa"
    package.mkdir(parents=True, mode=0o755)
    for name in PACKAGE_FILES:
        src = release / name
        dest = package / name
        dest.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o555 if name in {"worker.py", "host_preflight.py", "host_install.py", "host_release.py", "host_acceptance.py"} else 0o444)
        with os.fdopen(fd, "wb") as stream:
            stream.write(src.read_bytes())
        dest.chmod(0o555 if name in {"worker.py", "host_preflight.py", "host_install.py", "host_release.py", "host_acceptance.py"} else 0o444)
    (package / "release.sha256").write_bytes((release / "release.sha256").read_bytes())
    (package / "release.sha256").chmod(0o444)
    target.chmod(0o755)
    package.chmod(0o755)
    return verify_release(package, expected_sha)


def acl_backup(target: Path) -> None:
    target.mkdir(parents=True, mode=0o700)
    target.chmod(0o700)
    (target / "acl-single.txt").write_bytes(command("/usr/bin/getfacl", "-p",
                                                        *(str(p) for p in (*TRAVERSE, *EXACT_READ))))
    (target / "acl-trees.txt").write_bytes(command("/usr/bin/getfacl", "-R", "-p",
                                                       *(str(p) for p in TREES)))
    for name in ("acl-single.txt", "acl-trees.txt"):
        (target / name).chmod(0o600)


def acl_apply() -> None:
    for path in TRAVERSE:
        command("/usr/bin/setfacl", "-m", "u:alfredqa:--x", str(path))
    for path in EXACT_READ:
        command("/usr/bin/setfacl", "-m", "u:alfredqa:r--", str(path))
    for tree in TREES:
        for base, directories, files in os.walk(tree, followlinks=False):
            command("/usr/bin/setfacl", "-m", "u:alfredqa:r-x", base)
            for name in directories:
                path = Path(base) / name
                if path.is_symlink():
                    raise ValueError(f"symlink in QA evidence tree: {path}")
            for name in files:
                path = Path(base) / name
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise ValueError(f"nonregular QA evidence file: {path}")
                command("/usr/bin/setfacl", "-m", "u:alfredqa:r--", str(path))


def acl_restore(backup: Path) -> None:
    for name in ("acl-trees.txt", "acl-single.txt"):
        command("/usr/bin/setfacl", "--restore=" + str(backup / name))


def install(release: Path, expected_sha: str) -> dict:
    if os.geteuid() != 0:
        raise PermissionError("host installation requires root")
    if INSTALL.exists() or OUTPUT.exists():
        raise FileExistsError("QA package or output root already exists; refuse overwrite")
    verify_release(release, expected_sha)
    backup = BACKUPS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if backup.exists():
        raise FileExistsError(backup)
    staged = INSTALL.with_name(".alfred-independent-qa-v1.staged-" + str(os.getpid()))
    stage_copy(release, staged, expected_sha)
    acl_backup(backup)
    acl_started = False
    try:
        acl_started = True
        acl_apply()
        qa = pwd.getpwnam("alfredqa")
        OUTPUT.mkdir(mode=0o700)
        os.chown(OUTPUT, qa.pw_uid, qa.pw_gid)
        OUTPUT.chmod(0o700)
        preflight = administrator(staged, OUTPUT)
        staged.rename(INSTALL)
        (backup / "release-manifest.sha256").write_text(expected_sha + "\n")
        (backup / "release-manifest.sha256").chmod(0o600)
        return {"result": "INSTALLED", "install": str(INSTALL), "output": str(OUTPUT),
                "backup": str(backup), "release_manifest_sha256": expected_sha,
                "preflight": preflight}
    except BaseException:
        if acl_started:
            acl_restore(backup)
        if staged.exists():
            staged.rename(backup / "unaccepted-package")
        if OUTPUT.exists():
            OUTPUT.rename(backup / "unaccepted-output")
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    if len(args.manifest_sha256) != 64 or any(c not in "0123456789abcdef" for c in args.manifest_sha256):
        raise ValueError("invalid manifest pin")
    print(json.dumps(install(args.release, args.manifest_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
