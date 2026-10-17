"""File-only Intake diagnostics overlay; never stages or retries a challenge."""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, "/usr/local/lib/alfred-fresh-v1")
from fresh_v1 import upgrade

SOURCE = "developer_v1/trusted_intake_development.py"
MANIFEST = "developer_v1/release.sha256"
DESTINATIONS = {
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": SOURCE,
    "/opt/alfred-developer-v1/" + SOURCE: SOURCE,
    "/opt/alfred-developer-v1/" + MANIFEST: MANIFEST,
}
OLD_SOURCE = "d3e1677cb8d7ee17ab801448e85db48fee12d88bbf21a3561e9e755eef742168"
OLD_MANIFEST = "c23cb89acc0ddc17fe382c4ea3e985c8404ebbf2dace1d20bbad19da81fa9edd"


def paused(root):
    upgrade.validate_root(root)
    if not upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE").is_file():
        raise ValueError("operator PAUSE and idle workers required")


def inventory(raw):
    result = {}
    for line in raw.decode().splitlines():
        sha, name = line.split("  ", 1)
        if (
            not name.startswith("developer_v1/")
            or ".." in Path(name).parts
            or name in result
        ):
            raise ValueError("invalid Developer inventory")
        result[name] = sha
    return result


def rollback(root, backup):
    paused(root)
    index = json.loads((backup / "index.json").read_bytes())
    if [e["path"] for e in index["files"]] != list(DESTINATIONS):
        raise ValueError("unexpected diagnostics rollback inventory")
    upgrade.rollback(root, backup)
    return {"status": "ROLLED_BACK_HELD", "service_action": "none"}


def install(release, pin, root, backup, *, fail_after=None):
    paused(root)
    verified = upgrade.verify(release, pin)
    content = {name: (release / name).read_bytes() for name in {SOURCE, MANIFEST}}
    if any(upgrade.digest(raw) != verified[name] for name, raw in content.items()):
        raise ValueError("patch changed after verification")
    previous = {}
    for dest, name in DESTINATIONS.items():
        path = upgrade.target(root, dest)
        info, raw = path.lstat(), path.read_bytes()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o022
            or upgrade.digest(raw) != (OLD_SOURCE if name == SOURCE else OLD_MANIFEST)
        ):
            raise ValueError("installed diagnostics base mismatch: " + dest)
        previous[dest] = (info, raw)
    old = inventory(previous["/opt/alfred-developer-v1/" + MANIFEST][1])
    new = inventory(content[MANIFEST])
    expected = {**old, SOURCE: upgrade.digest(content[SOURCE])}
    if new != expected:
        raise ValueError("only Intake source may change in Developer inventory")
    for name, sha in old.items():
        if (
            upgrade.digest(
                upgrade.target(root, "/opt/alfred-developer-v1/" + name).read_bytes()
            )
            != sha
        ):
            raise ValueError("installed Developer inventory mismatch: " + name)
    activation = upgrade.marker(root)
    backup.mkdir(mode=0o700, parents=False, exist_ok=False)
    entries = []
    for i, (dest, (info, raw)) in enumerate(previous.items()):
        item = "file-" + str(i)
        upgrade.atomic(backup / item, raw, os.geteuid(), os.getegid(), 0o600)
        entries.append(
            {
                "path": dest,
                "backup": item,
                "sha256": upgrade.digest(raw),
                "uid": info.st_uid,
                "gid": info.st_gid,
                "mode": stat.S_IMODE(info.st_mode),
            }
        )
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
        for i, (dest, name) in enumerate(DESTINATIONS.items()):
            if fail_after == i:
                raise OSError("disposable fixture fault")
            info, _ = previous[dest]
            upgrade.atomic(
                upgrade.target(root, dest),
                content[name],
                info.st_uid,
                info.st_gid,
                stat.S_IMODE(info.st_mode),
            )
        if upgrade.marker(root) != activation:
            raise ValueError("activation marker changed")
    except BaseException:
        rollback(root, backup)
        raise
    return {
        "status": "INSTALLED_HELD",
        "service_action": "none",
        "retry_authorized": False,
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
