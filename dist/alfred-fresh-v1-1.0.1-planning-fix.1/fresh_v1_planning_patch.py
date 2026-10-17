"""File-only V1.0.1 planning correction. Never runs a worker or controls a service."""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

# Use the already installed, unchanged root-owned file-transaction primitives.
if __name__ == "__main__":
    sys.path.insert(0, "/usr/local/lib/alfred-fresh-v1")
from fresh_v1 import upgrade

PREFIX = "/usr/local/lib/alfred-fresh-v1/fresh_v1/"
FILES = ("diagnostics.py", "role.py", "host.py")  # Dependency first; dispatch last.
BASE = {
    "host.py": "86267e1615454475dbca30708d912c7a333c796ea9bfc0d95d1d721000aaa03b",
    "role.py": "0817a393b47a991831d88fde4935f425620971f55468eb0ea7d42cdd2a497a0f",
    "handoffs.py": "4a0ee3c9efeb3a2ef23368d4359d5a23162cfdfd0e17ab1fa94d97df9e1bcb9c",
    "protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
    "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
}


def paused(root):
    upgrade.validate_root(root)
    if not upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE").is_file():
        raise ValueError("operator PAUSE and idle workers required")


def rollback(root, backup):
    paused(root)
    index = json.loads((backup / "index.json").read_bytes())
    if [e["path"] for e in index["files"]] != [PREFIX + n for n in FILES]:
        raise ValueError("unexpected patch rollback inventory")
    upgrade.rollback(root, backup)
    return {"status": "ROLLED_BACK_HELD", "service_action": "none"}


def install(release, pin, root, backup, *, fail_after=None):
    paused(root)
    inventory = upgrade.verify(release, pin)
    content = {n: (release / "fresh_v1" / n).read_bytes() for n in FILES}
    if any(
        upgrade.digest(raw) != inventory["fresh_v1/" + n] for n, raw in content.items()
    ):
        raise ValueError("patch changed after verification")
    for name, expected in BASE.items():
        path = upgrade.target(root, PREFIX + name)
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o022
            or upgrade.digest(path.read_bytes()) != expected
        ):
            raise ValueError("installed V1.0.1 contract mismatch: " + name)
    if upgrade.target(root, PREFIX + "diagnostics.py").exists():
        raise ValueError("patch already present or unexpected diagnostics module")
    activation = upgrade.marker(root)
    backup.mkdir(mode=0o700, parents=False, exist_ok=False)
    entries = []
    for name in FILES:
        path = upgrade.target(root, PREFIX + name)
        if path.exists():
            info, raw = path.stat(), path.read_bytes()
            upgrade.atomic(backup / name, raw, os.geteuid(), os.getegid(), 0o600)
            entry = {
                "backup": name,
                "sha256": upgrade.digest(raw),
                "uid": info.st_uid,
                "gid": info.st_gid,
                "mode": stat.S_IMODE(info.st_mode),
            }
        else:
            entry = {"backup": None}
        entries.append({"path": PREFIX + name, **entry})
    upgrade.atomic(
        backup / "index.json",
        (
            json.dumps(
                {
                    "schema": "alfred.fresh-v1-backup/1",
                    "root": str(root),
                    "activation_sha256": activation,
                    "files": entries,
                },
                sort_keys=True,
            )
            + "\n"
        ).encode(),
        os.geteuid(),
        os.getegid(),
        0o600,
    )
    try:
        for i, name in enumerate(FILES):
            if fail_after == i:
                raise OSError("disposable fixture fault")
            upgrade.atomic(
                upgrade.target(root, PREFIX + name),
                content[name],
                os.geteuid(),
                os.getegid(),
                0o644,
            )
        if upgrade.marker(root) != activation:
            raise ValueError("activation marker changed")
    except BaseException:
        rollback(root, backup)
        raise
    return {
        "status": "INSTALLED_HELD",
        "service_action": "none",
        "manifest_sha256": pin,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "rollback", "verify"))
    parser.add_argument("--release", type=Path)
    parser.add_argument("--manifest")
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.action == "verify":
        result = {"files": len(upgrade.verify(args.release, args.manifest))}
    elif args.action == "install":
        result = install(args.release, args.manifest, args.root, args.backup)
    else:
        result = rollback(args.root, args.backup)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
