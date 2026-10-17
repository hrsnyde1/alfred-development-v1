"""File-only recovery extension over installed planning fix.1. No task execution."""

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
FILES = ("recovery.py", "host.py", "handoffs.py")
BASE = {
    "host.py": "162d553df4512e235ba9a0a8ab8adb4187dde2a140c9c728c6e41c0958647954",
    "role.py": "99d43e22ace57b1cf4f97972e2e3755a8a2269d66f53f9078220b859407cd109",
    "diagnostics.py": "c5862c14b39b22b7e6faef07aea1d4c32b5ab0df20aab987d4a0fed33b763e0e",
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
    if upgrade.target(root, PREFIX + "recovery.py").exists():
        raise ValueError("patch already present or unexpected recovery module")
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
