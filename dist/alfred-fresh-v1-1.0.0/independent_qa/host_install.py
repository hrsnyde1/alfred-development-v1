"""One-shot root installation; no systemd unit is created or restarted."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import stat
import subprocess
import time
from pathlib import Path

from .host_preflight import (DEVELOPER, EVIDENCE, FINAL, HANDOFF_FILES, OTHER_PROJECTS,
                             PINNED_HANDOFF, REPOSITORY, administrator, observe_access,
                             verify_handoff)
from .host_release import PACKAGE_FILES, verify as verify_release

INSTALL = Path("/opt/alfred-independent-qa-v1")
OUTPUT = Path("/var/lib/alfred-independent-qa-state")
BACKUPS = Path("/var/lib/alfred-independent-qa-backups")

TRAVERSE = (
    Path("/home/alfred"),
    Path("/home/alfred/alfred-development-lab"),
    Path("/home/alfred/alfred-development-lab/milestone2"),
    Path("/home/alfred/alfred-development-lab/milestone2/task-a"),
    Path("/home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance"),
    FINAL.parent,
)
TREES = (REPOSITORY, DEVELOPER, FINAL)
EXACT_READ = ()
QA_DENY = OTHER_PROJECTS


def acl_paths() -> tuple[Path, ...]:
    paths = set((*TRAVERSE, *EXACT_READ, *QA_DENY))
    for tree in TREES:
        for base, directories, files in os.walk(tree, followlinks=False):
            paths.add(Path(base))
            paths.update(Path(base) / name for name in (*directories, *files))
    return tuple(sorted(paths))


def trusted_release(release: Path, expected_sha: str) -> None:
    verify_release(release, expected_sha)
    paths = (release, release.parent, release / "schemas", release / "release.sha256",
             *(release / name for name in PACKAGE_FILES))
    for path in paths:
        info = path.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise PermissionError(f"release is not root-owned and non-user-writable: {path}")
    for parent in release.parents:
        info = parent.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError(f"untrusted release ancestor: {parent}")


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


def stage_evidence(target: Path = EVIDENCE, files: tuple = HANDOFF_FILES,
                   pins: dict = PINNED_HANDOFF, *, require_root: bool = True) -> str:
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.mkdir(mode=0o700)
    lines = []
    parents = {target}
    for source, relative in files:
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"nonregular canonical evidence: {source}")
        raw = source.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if relative in pins and sha != pins[relative]:
            raise ValueError(f"pinned canonical evidence changed: {relative}")
        dest = target / relative
        parent = target
        for part in Path(relative).parts[:-1]:
            parent = parent / part
            try:
                info = parent.lstat()
            except FileNotFoundError:
                parent.mkdir(mode=0o700)
                info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError(f"unexpected QA evidence directory state: {parent}")
            parents.add(parent)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        command("/usr/bin/setfacl", "-m", "u:alfredqa:r--", str(dest))
        lines.append(f"{sha}  {relative}")
    manifest = target / "evidence.sha256"
    manifest.write_text("\n".join(lines) + "\n")
    manifest.chmod(0o600)
    for directory in sorted(parents, key=lambda path: len(path.parts), reverse=True):
        command("/usr/bin/setfacl", "-m", "u:alfredqa:r-x", str(directory))
    return verify_handoff(target, files, pins, require_root=require_root)


def acl_backup(target: Path) -> None:
    target.mkdir(parents=True, mode=0o700)
    target.chmod(0o700)
    (target / "acl-single.txt").write_bytes(command("/usr/bin/getfacl", "-p",
                                                        *(str(p) for p in (*TRAVERSE, *EXACT_READ, *QA_DENY))))
    (target / "acl-trees.txt").write_bytes(command("/usr/bin/getfacl", "-R", "-p",
                                                       *(str(p) for p in TREES)))
    for name in ("acl-single.txt", "acl-trees.txt"):
        (target / name).chmod(0o600)


def acl_apply() -> None:
    for path in TRAVERSE:
        command("/usr/bin/setfacl", "-m", "u:alfredqa:--x", str(path))
    for path in EXACT_READ:
        command("/usr/bin/setfacl", "-m", "u:alfredqa:r--", str(path))
    for path in QA_DENY:
        command("/usr/bin/setfacl", "-m", "u:alfredqa:---", str(path))
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
    if INSTALL.exists() or OUTPUT.exists() or EVIDENCE.exists():
        raise FileExistsError("QA package, output, or evidence root already exists; refuse overwrite")
    trusted_release(release, expected_sha)
    backup = BACKUPS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if backup.exists():
        raise FileExistsError(backup)
    staged = INSTALL.with_name(".alfred-independent-qa-v1.staged-" + str(os.getpid()))
    stage_copy(release, staged, expected_sha)
    acl_started = False
    try:
        BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
        BACKUPS.chmod(0o700)
        acl_backup(backup)
        (backup / "service-access-before.json").write_text(
            json.dumps(observe_access(acl_paths()), sort_keys=True) + "\n")
        (backup / "service-access-before.json").chmod(0o600)
        acl_started = True
        evidence_sha = stage_evidence(EVIDENCE)
        acl_apply()
        qa = pwd.getpwnam("alfredqa")
        OUTPUT.mkdir(mode=0o700)
        os.chown(OUTPUT, qa.pw_uid, qa.pw_gid)
        OUTPUT.chmod(0o700)
        preflight = administrator(staged, OUTPUT, backup / "service-access-before.json")
        staged.rename(INSTALL)
        (backup / "release-manifest.sha256").write_text(expected_sha + "\n")
        (backup / "release-manifest.sha256").chmod(0o600)
        return {"result": "INSTALLED", "install": str(INSTALL), "output": str(OUTPUT),
                "evidence": str(EVIDENCE), "evidence_manifest_sha256": evidence_sha,
                "backup": str(backup), "release_manifest_sha256": expected_sha,
                "preflight": preflight}
    except BaseException:
        if acl_started:
            acl_restore(backup)
        if staged.exists():
            backup.mkdir(parents=True, exist_ok=True, mode=0o700)
            staged.rename(backup / "unaccepted-package")
        if OUTPUT.exists():
            OUTPUT.rename(backup / "unaccepted-output")
        if EVIDENCE.exists():
            EVIDENCE.rename(backup / "unaccepted-evidence")
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
