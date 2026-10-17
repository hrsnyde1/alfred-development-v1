"""Read-only Evidence Bridge v0.2.1 inventory and isolated-copy rehearsal."""

from __future__ import annotations

import json
from pathlib import Path
import stat

from .release import ReleaseError, _atomic, sha256
from .transport import isolated_root


PINNED = Path(__file__).resolve().parents[1] / "templates/permissions/evidence-v0.2.1-sha256.json"


def verify_plugin(source: Path) -> dict[str, str]:
    expected = json.loads(PINNED.read_text())
    if source.is_symlink() or not source.is_dir():
        raise ReleaseError("Evidence Bridge directory missing or linked")
    observed = {}
    for name, digest in expected.items():
        path = source / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ReleaseError("Evidence Bridge payload is not a regular file")
        observed[name] = sha256(path.read_bytes())
        if observed[name] != digest:
            raise ReleaseError("Evidence Bridge v0.2.1 checksum mismatch")
    if {p.name for p in source.iterdir() if not p.name.startswith("__pycache__")} != set(expected):
        raise ReleaseError("unexpected Evidence Bridge payload")
    return observed


def copy_into_isolated_root(root: Path, source: Path, destination: Path) -> None:
    root = isolated_root(root)
    verify_plugin(source)
    if not destination.resolve().is_relative_to(root) or destination.exists():
        raise ReleaseError("Evidence Bridge target must be new and isolated")
    destination.mkdir(parents=True, mode=0o750)
    for name in json.loads(PINNED.read_text()):
        _atomic(destination / name, (source / name).read_bytes(), 0o640)
    verify_plugin(destination)
