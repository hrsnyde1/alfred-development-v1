"""Build and verify an exact Reviewer package inventory in staging."""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

FILES = (
    "__init__.py", "worker.py", "host_release.py", "config.json", "README.md",
    "schemas/review-report.schema.json", "schemas/publication-handoff.schema.json",
    "schemas/correction-request.schema.json", "schemas/model-output.schema.json",
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build(source: Path, target: Path) -> str:
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.mkdir(parents=True)
    lines = []
    for name in FILES:
        src, dst = source / name, target / name
        if not src.is_file() or src.is_symlink():
            raise ValueError(f"invalid package source: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        lines.append(f"{sha(dst.read_bytes())}  {name}")
    (target / "release.sha256").write_text("\n".join(lines) + "\n")
    return verify(target)


def verify(root: Path, pin: str | None = None) -> str:
    manifest = root / "release.sha256"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("release manifest missing or symlinked")
    raw = manifest.read_bytes()
    found = sha(raw)
    if pin is not None and found != pin:
        raise ValueError("release manifest digest mismatch")
    lines = raw.decode().splitlines()
    expected = []
    for name in FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or symlinked release file: {name}")
        expected.append(f"{sha(path.read_bytes())}  {name}")
    if lines != expected:
        raise ValueError("release contents differ from manifest")
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() or p.is_symlink()}
    if actual != set(FILES) | {"release.sha256"}:
        raise ValueError("release has extra or missing files")
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--pin")
    args = parser.parse_args()
    if args.build and args.output:
        print(build(args.build, args.output))
    elif args.verify:
        print(verify(args.verify, args.pin))
    else:
        parser.error("use --build SOURCE --output TARGET or --verify TARGET [--pin SHA]")


if __name__ == "__main__":
    main()
