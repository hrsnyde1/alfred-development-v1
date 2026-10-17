"""Two-file handoff.3 overlay using existing atomic file primitives; no service actions.

Replaces the fresh V1 host poll (a recorded stage failure no longer starves later
owner requests) and the Evidence drop-in (the grant store becomes writable in its
sandbox). The operator runs `systemctl daemon-reload` afterwards; nothing restarts.
"""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, "/usr/local/lib/alfred-fresh-v1")
from fresh_v1 import upgrade

LIBRARY = "/usr/local/lib/alfred-fresh-v1/fresh_v1/"
DROP_IN = "/etc/systemd/system/alfred-development-evidence.service.d/40-fresh-v1.conf"
DESTINATIONS = {
    LIBRARY + "host.py": "fresh_v1/host.py",
    DROP_IN: "fresh_v1/systemd/alfred-development-evidence.conf",
}
# Exactly the handoff.2 installed host and the original fresh V1 drop-in.
BASE = {
    LIBRARY + "host.py": "6a8e2e8f5c7749749bd7a139c068f3060cda67cddbf134e78d3f4b04dad61e53",
    DROP_IN: "e88438ab00345eab461fedbb485a3f2a27bfd6a4d1bcb69c0343da01d08b7ed9",
}
# Unchanged runtime the new host imports; each must still match handoff.2.
DEPENDENCIES = {
    LIBRARY + name: sha
    for name, sha in {
        "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
        "handoffs.py": "09568b8de620b61c28dbf4c4a3be824c7e4eecd3800aaa47d6858a13ad066ebb",
        "role.py": "99d43e22ace57b1cf4f97972e2e3755a8a2269d66f53f9078220b859407cd109",
        "diagnostics.py": "c5862c14b39b22b7e6faef07aea1d4c32b5ab0df20aab987d4a0fed33b763e0e",
        "protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
        "recovery.py": "d6e3f3627f5f6c82223fe16dab7ef43d619cda4d98c4edf99467a76c0df688c4",
    }.items()
}
BACKUP_SCHEMA = "alfred.development-handoff3-backup/1"


def paused(root):
    upgrade.validate_root(root)
    path = upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE")
    if not path.is_file():
        raise ValueError("operator PAUSE and idle workers required")


def checked(path, sha):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o022
        or upgrade.digest(path.read_bytes()) != sha
    ):
        raise ValueError("installed contract mismatch: " + str(path))
    return info, path.read_bytes()


def rollback(root, backup):
    paused(root)
    info = backup.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("unprotected backup")
    index_path = backup / "index.json"
    index_info = index_path.lstat()
    if (
        not stat.S_ISREG(index_info.st_mode)
        or index_info.st_uid != os.geteuid()
        or index_info.st_nlink != 1
        or index_info.st_mode & 0o077
    ):
        raise ValueError("unprotected backup index")
    index = json.loads(index_path.read_bytes())
    if (
        index.get("schema") != BACKUP_SCHEMA
        or index.get("root") != str(root)
        or upgrade.marker(root) != index["activation_sha256"]
        or [e["path"] for e in index["files"]] != list(DESTINATIONS)
    ):
        raise ValueError("rollback inventory/root/activation mismatch")
    content = []
    for i, entry in enumerate(index["files"]):
        if entry["backup"] != "file-" + str(i) or entry["sha256"] != BASE[entry["path"]]:
            raise ValueError("rollback backup contract mismatch")
        _, raw = checked(backup / entry["backup"], entry["sha256"])
        content.append(raw)
    for entry, raw in reversed(list(zip(index["files"], content, strict=True))):
        upgrade.atomic(
            upgrade.target(root, entry["path"]),
            raw,
            entry["uid"],
            entry["gid"],
            entry["mode"],
        )
    if upgrade.marker(root) != index["activation_sha256"]:
        raise ValueError("activation marker changed")
    return {"status": "ROLLED_BACK_HELD", "service_action": "daemon-reload required"}


def install(release, pin, root, backup, *, fail_after=None):
    paused(root)
    verified = upgrade.verify(release, pin)
    content = {n: (release / n).read_bytes() for n in DESTINATIONS.values()}
    if any(upgrade.digest(raw) != verified[n] for n, raw in content.items()):
        raise ValueError("release changed after verification")
    previous = {n: checked(upgrade.target(root, n), sha) for n, sha in BASE.items()}
    for name, sha in DEPENDENCIES.items():
        checked(upgrade.target(root, name), sha)
    activation = upgrade.marker(root)
    backup.mkdir(mode=0o700, parents=False, exist_ok=False)
    entries = []
    for i, (name, (info, raw)) in enumerate(previous.items()):
        item = "file-" + str(i)
        upgrade.atomic(backup / item, raw, os.geteuid(), os.getegid(), 0o600)
        entries.append(
            {
                "path": name,
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
                    "schema": BACKUP_SCHEMA,
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
        for i, (name, source) in enumerate(DESTINATIONS.items()):
            if i == fail_after:
                raise OSError("disposable fixture fault")
            info, _ = previous[name]
            upgrade.atomic(
                upgrade.target(root, name),
                content[source],
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
        "service_action": "daemon-reload required; no restart",
        "retry_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "verify", "rollback"))
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
