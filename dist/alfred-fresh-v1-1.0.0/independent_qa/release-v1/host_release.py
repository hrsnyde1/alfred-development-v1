"""Build and verify a pinned, minimal Independent QA host release."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from pathlib import Path

PACKAGE_FILES = (
    "__init__.py", "worker.py", "config.json", "host_preflight.py", "host_release.py",
    "host_install.py", "README.md",
    "schemas/qa-report.schema.json", "schemas/reviewer-handoff.schema.json",
    "schemas/correction-request.schema.json",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(root: Path, expected_manifest_sha: str | None = None) -> str:
    manifest = root / "release.sha256"
    raw = manifest.read_bytes()
    actual = sha(raw)
    if expected_manifest_sha is not None and actual != expected_manifest_sha:
        raise ValueError("release manifest pin mismatch")
    expected = [f"{sha((root / name).read_bytes())}  {name}" for name in PACKAGE_FILES]
    if raw != ("\n".join(expected) + "\n").encode():
        raise ValueError("release file digest mismatch")
    found = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    if found != set(PACKAGE_FILES) | {"release.sha256"}:
        raise ValueError("release file inventory mismatch")
    for name in PACKAGE_FILES:
        mode = (root / name).lstat().st_mode
        if not stat.S_ISREG(mode) or (root / name).is_symlink():
            raise ValueError("release includes nonregular file")
    return actual


def build(source: Path, target: Path) -> str:
    if target.exists():
        raise FileExistsError(target)
    target.mkdir(mode=0o700, parents=True)
    for name in PACKAGE_FILES:
        src = source / name
        if not stat.S_ISREG(src.lstat().st_mode) or src.is_symlink():
            raise ValueError(f"invalid source file: {name}")
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
        with os.fdopen(fd, "wb") as stream:
            stream.write(src.read_bytes())
        dest.chmod(0o555 if name in {"worker.py", "host_preflight.py", "host_install.py", "host_release.py"} else 0o444)
    lines = [f"{sha((target / name).read_bytes())}  {name}" for name in PACKAGE_FILES]
    (target / "release.sha256").write_text("\n".join(lines) + "\n")
    (target / "release.sha256").chmod(0o444)
    return verify(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.source, args.output))
