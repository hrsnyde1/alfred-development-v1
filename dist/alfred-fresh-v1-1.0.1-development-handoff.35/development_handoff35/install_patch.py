"""handoff.35 overlay: agent identities may include Escalation.md.

Hayden's request (2026-10-19), after the Development CTO identity added Escalation.md
(alfred-team-skills PR #11): "add Escalation.md to both identity loaders and raise the
profile cap, as a pinned release."
- agent_profiles.py: reads Escalation.md when an agent has one (after the eight files);
  the cap per identity goes from 8,192 to 12,288 bytes.
- team_snapshot.py: Alfred OS snapshots may list Escalation.md; it goes after Quality.
No identity content changes here (agent_profiles.json is untouched). Installs only after
handoff.34, which pins these two files as they are now. Nothing restarts.
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
UNITS = "/etc/systemd/system/"
DEVELOPER = "/opt/alfred-developer-v1/developer_v1/"
DESTINATIONS = {
    DEVELOPER + "agent_profiles.py": "developer_v1/agent_profiles.py",
    DEVELOPER + "team_snapshot.py": "developer_v1/team_snapshot.py",
}
# Exactly the bytes installed today (handoffs 21 and 25), which handoff.34 also pins.
BASE = {
    DEVELOPER + "agent_profiles.py": "d9731eae53ffc27b4d453d946d044f2b93bde04e53e47fd9ba3221745149c775",
    DEVELOPER + "team_snapshot.py": "db5e8d845e50399c24e275004f100df6e48b6ae3223f0e4debfb7218214985fa",
}
NEW_MODE = 0o644
DEPENDENCIES = {
    LIBRARY + "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
    # handoff.34 first: it pins the two files this release replaces.
    DEVELOPER + "repo_intelligence.py": "fec05e8bf3ddc9594fd9cf0e07640da5b296523abc15db19ccbd7d0f79112064",
}
BACKUP_SCHEMA = "alfred.development-handoff35-backup/1"


def paused(root):
    upgrade.validate_root(root)
    path = upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE")
    if not path.is_file():
        raise ValueError("operator PAUSE and idle workers required")


def checked(root, name, sha):
    path = upgrade.target(root, name)
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


def absent(root, name):
    path = upgrade.target(root, name)
    if os.path.lexists(path):
        raise ValueError("new file already exists: " + str(path))
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
        raise ValueError("unprotected directory for new file: " + str(path.parent))


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
        if entry["sha256"] != BASE[entry["path"]]:
            raise ValueError("rollback backup contract mismatch")
        if entry["sha256"] is None:
            content.append(None)
            continue
        if entry["backup"] != "file-" + str(i):
            raise ValueError("rollback backup contract mismatch")
        path = backup / entry["backup"]
        stored = path.lstat()
        if (not stat.S_ISREG(stored.st_mode) or stored.st_uid != os.geteuid()
                or upgrade.digest(path.read_bytes()) != entry["sha256"]):
            raise ValueError("rollback backup contract mismatch")
        content.append(path.read_bytes())
    for entry, raw in reversed(list(zip(index["files"], content, strict=True))):
        target = upgrade.target(root, entry["path"])
        if raw is None:
            if os.path.lexists(target):
                target.unlink()
        else:
            upgrade.atomic(target, raw, entry["uid"], entry["gid"], entry["mode"])
    if upgrade.marker(root) != index["activation_sha256"]:
        raise ValueError("activation marker changed")
    return {"status": "ROLLED_BACK_HELD", "service_action": "none"}


def install(release, pin, root, backup, *, fail_after=None):
    paused(root)
    verified = upgrade.verify(release, pin)
    content = {n: (release / n).read_bytes() for n in DESTINATIONS.values()}
    if any(upgrade.digest(raw) != verified[n] for n, raw in content.items()):
        raise ValueError("release changed after verification")
    previous = {}
    for name, sha in BASE.items():
        if sha is None:
            absent(root, name)
            previous[name] = None
        else:
            previous[name] = checked(root, name, sha)
    for name, sha in DEPENDENCIES.items():
        checked(root, name, sha)
    activation = upgrade.marker(root)
    backup.mkdir(mode=0o700, parents=False, exist_ok=False)
    entries = []
    for i, (name, value) in enumerate(previous.items()):
        if value is None:
            entries.append({"path": name, "backup": None, "sha256": None})
            continue
        info, raw = value
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
            if previous[name] is None:
                upgrade.atomic(upgrade.target(root, name), content[source],
                               os.geteuid(), os.getegid(), NEW_MODE)
            else:
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
        "service_action": "none",
        "next": "identities are read with Escalation.md from the next task",
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
