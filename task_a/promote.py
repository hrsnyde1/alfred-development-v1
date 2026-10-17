"""Staging-only source promotion into a versioned *lab* runtime copy."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import uuid

from .release import ReleaseError, _atomic, _safe_relative, sha256
from .transport import isolated_root


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def promote_lab_copy(repo: Path, approved_commit: str, hashes: dict[str, str], root: Path) -> Path:
    root = isolated_root(root)
    repo = isolated_root(repo)
    if len(approved_commit) != 40 or any(c not in "0123456789abcdef" for c in approved_commit):
        raise ReleaseError("full approved commit required")
    if _git(repo, "rev-parse", "HEAD") != approved_commit or _git(repo, "status", "--porcelain"):
        raise ReleaseError("source commit or clean-tree mismatch")
    if not hashes or any(len(value) != 64 for value in hashes.values()):
        raise ReleaseError("missing approved file hashes")
    versions = root / "versions"
    if versions.is_symlink():
        raise ReleaseError("runtime versions path is linked")
    versions.mkdir(mode=0o700, exist_ok=True)
    if not versions.resolve().is_relative_to(root):
        raise ReleaseError("runtime versions path escapes root")
    version = versions / approved_commit
    if version.exists():
        raise ReleaseError("approved version already staged")
    staging = versions / (".candidate-" + uuid.uuid4().hex)
    staging.mkdir(mode=0o700)
    try:
        for name, expected in sorted(hashes.items()):
            relative = _safe_relative(name)
            source = repo / relative
            if source.is_symlink() or not source.resolve(strict=True).is_relative_to(repo):
                raise ReleaseError("source link or escape")
            info = source.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ReleaseError("non-regular source")
            content = source.read_bytes()
            if sha256(content) != expected:
                raise ReleaseError("source hash mismatch")
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _atomic(target, content, 0o640)
        _atomic(staging / "manifest.json", json.dumps({"commit": approved_commit, "files": hashes}, sort_keys=True).encode())
        os.replace(staging, version)
        previous = None
        current = root / "current"
        if current.is_symlink():
            previous = os.readlink(current)
            if not (root / previous).resolve(strict=True).is_relative_to(versions):
                raise ReleaseError("unsafe previous version")
        elif current.exists():
            raise ReleaseError("current selector is not a symlink")
        _atomic(root / "previous.json", json.dumps({"before": previous, "after": f"versions/{approved_commit}"}).encode())
        temporary = root / (".selector-" + uuid.uuid4().hex)
        os.symlink(f"versions/{approved_commit}", temporary)
        os.replace(temporary, current)
        return version
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def promote_full_tracked_tree(repo: Path, approved_commit: str, root: Path) -> Path:
    """Stage all Git-tracked files, including the lab fixture's marker.

    Dependency environments and executable launchers outside Git still need a
    separate pinned package and independent review.
    """
    repo = isolated_root(repo)
    if _git(repo, "rev-parse", "HEAD") != approved_commit or _git(repo, "status", "--porcelain"):
        raise ReleaseError("source commit or clean-tree mismatch")
    names = subprocess.check_output(["git", "-C", str(repo), "ls-files", "-z"]).split(b"\0")
    hashes = {}
    for raw in names:
        if not raw:
            continue
        try:
            name = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseError("non-UTF-8 tracked path") from exc
        relative = _safe_relative(name)
        path = repo / relative
        if path.is_symlink() or not path.is_file():
            raise ReleaseError("tracked symlink or non-file refused")
        hashes[name] = sha256(path.read_bytes())
    return promote_lab_copy(repo, approved_commit, hashes, root)


def rollback_lab_copy(root: Path) -> None:
    root = isolated_root(root)
    record = json.loads((root / "previous.json").read_text())
    current = root / "current"
    if not current.is_symlink() or os.readlink(current) != record["after"]:
        raise ReleaseError("runtime selector changed")
    version = (root / record["after"]).resolve(strict=True)
    manifest = json.loads((version / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        if sha256((version / _safe_relative(name)).read_bytes()) != expected:
            raise ReleaseError("runtime copy changed")
    before = record["before"]
    if before is None:
        current.unlink()
    else:
        previous = (root / before).resolve(strict=True)
        if not previous.is_relative_to(root / "versions"):
            raise ReleaseError("unsafe previous version")
        old_manifest = json.loads((previous / "manifest.json").read_text())
        for name, expected in old_manifest["files"].items():
            if sha256((previous / _safe_relative(name)).read_bytes()) != expected:
                raise ReleaseError("previous runtime copy changed")
        temporary = root / (".selector-" + uuid.uuid4().hex)
        os.symlink(before, temporary)
        os.replace(temporary, current)
