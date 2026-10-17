"""Four-file handoff.6 overlay using existing atomic file primitives; no service actions.

Codex may send progress notes (e.g. {"status": ...}) before its schema-bound final
message, and the Developer and Reviewer refused anything but exactly one message
(T-0007 Developer: "model produced ambiguous response"). Both now accept exactly
one contract-shaped message, which must be the final one. Their release inventories
are updated with them. Workers are invoked per stage, so no restart is needed.
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
DEVELOPER = "/opt/alfred-developer-v1/developer_v1/"
REVIEWER = "/opt/alfred-reviewer-v1/independent_reviewer/"
DESTINATIONS = {
    DEVELOPER + "real_worker.py": "developer_v1/real_worker.py",
    DEVELOPER + "release.sha256": "developer_v1/release.sha256",
    REVIEWER + "worker.py": "independent_reviewer/host-candidate-v5/independent_reviewer/worker.py",
    REVIEWER + "release.sha256":
        "independent_reviewer/host-candidate-v5/independent_reviewer/release.sha256",
}
# Exactly the handoff.2 Developer and the v4 Reviewer as installed.
BASE = {
    DEVELOPER + "real_worker.py": "0c29350880f3fc76af87790554afff2b3a20d974a3f94981fcc8b3cb8e460b3f",
    DEVELOPER + "release.sha256": "7e819693e2c514d2c346f9f58227a9dd8b95a6d0c3d10adc21246be3c11fe6c7",
    REVIEWER + "worker.py": "8ce51233d5c56c0db3ad1d7d185c33aace41ac21088107a860e8c5959359e39b",
    REVIEWER + "release.sha256": "f6f789de9a8bb5e4e6b9dd67db9decc5e8ee760c203ebba6a45ef61532cc5832",
}
# The fresh V1 runtime is unchanged by this release; each must still match handoff.5.
DEPENDENCIES = {
    LIBRARY + name: sha
    for name, sha in {
        "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
        "role.py": "3c2c3968cb858e4469ce11e82dd2bbfd7f61ea43f9dcc783145cbf21f524a688",
        "host.py": "9f96b4d7fca5e7635fb1ccc7d688d32604f514a9fe312b68d02a17c5ffe040ab",
        "handoffs.py": "a515f6e3ff0a4babe44a33c28541657544468f7a233ee8eeb70e4ab48037248c",
    }.items()
}
# Every other file each installed inventory lists must still match it, and the new
# inventory may differ from the old one only in its own package's worker line.
INVENTORIES = {
    DEVELOPER + "release.sha256": ("/opt/alfred-developer-v1/", "developer_v1/real_worker.py"),
    REVIEWER + "release.sha256": (REVIEWER, "worker.py"),
}
BACKUP_SCHEMA = "alfred.development-handoff6-backup/1"


def inventory_lines(raw):
    rows = {}
    for line in raw.decode().splitlines():
        sha, name = line.split("  ", 1)
        if name in rows or ".." in Path(name).parts or name.startswith("/"):
            raise ValueError("invalid release inventory")
        rows[name] = sha
    return rows


def check_inventories(root, previous, content):
    for destination, (base, changed) in INVENTORIES.items():
        old = inventory_lines(previous[destination][1])
        new = inventory_lines(content[DESTINATIONS[destination]])
        worker = next(d for d in DESTINATIONS if d == base + changed)
        if (
            set(old) != set(new)
            or {n for n in old if old[n] != new[n]} != {changed}
            or new[changed] != upgrade.digest(content[DESTINATIONS[worker]])
            or old[changed] != BASE[worker]
        ):
            raise ValueError("unexpected release inventory delta: " + destination)
        for name, sha in old.items():
            if name != changed:
                checked(upgrade.target(root, base + name), sha)


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
    check_inventories(root, previous, content)
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
