"""handoff.44 overlay: Photon stalls you can clear, and the Development board feed.

Two files from handoff.43 change, seven are new:
- fresh_v1/photon_watchdog.py: keeps a stall list (stalls.json, 0644) and answers owner
  requests (clear: restart Photon now; delete: drop one stall from the list).
- alfred-photon-watchdog.service: its state folder becomes 0711 so the bridges can read
  stalls.json, and it may remove request files from the spool.
- alfred-photon-requests.path: starts the watchdog as soon as a request lands.
- sysusers.d/alfred-photon.conf, tmpfiles.d/alfred-photon.conf: the alfredphoton group
  (alfredos, alfredmsg) and the sticky spool /var/lib/alfred-photon-requests.
- /usr/local/bin/alfred-photon-clear: what Alfred runs when Hayden asks.
- fresh_v1/dev_board.py, alfred-dev-board.service / .timer: every task's workflow for
  Alfred OS's Development board, written every 20 seconds to a file the bridge may read.
Then: systemd-sysusers, systemd-tmpfiles --create, daemon-reload, enable the path and the
board timer, and restart Alfred OS so it joins alfredphoton (see RELEASE.md).
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
DESTINATIONS = {
    LIBRARY + "photon_watchdog.py": "fresh_v1/photon_watchdog.py",
    UNITS + "alfred-photon-watchdog.service": "development_handoff44/alfred-photon-watchdog.service",
    UNITS + "alfred-photon-requests.path": "development_handoff44/alfred-photon-requests.path",
    "/etc/sysusers.d/alfred-photon.conf": "development_handoff44/alfred-photon.sysusers.conf",
    "/etc/tmpfiles.d/alfred-photon.conf": "development_handoff44/alfred-photon.tmpfiles.conf",
    "/usr/local/bin/alfred-photon-clear": "development_handoff44/alfred-photon-clear",
    LIBRARY + "dev_board.py": "fresh_v1/dev_board.py",
    UNITS + "alfred-dev-board.service": "development_handoff44/alfred-dev-board.service",
    UNITS + "alfred-dev-board.timer": "development_handoff44/alfred-dev-board.timer",
}
# handoff.43's two files must be exactly as it installed them; the rest are new.
BASE = {name: None for name in DESTINATIONS} | {
    LIBRARY + "photon_watchdog.py": "2188ae862289b413663e30db7f137c1dbce49496dff2a638162e1c6b21943c6f",
    UNITS + "alfred-photon-watchdog.service": "7b9725e56d3aa8f72e72475ced66e0f7542386b3e36b89dba17c589dc83e406d",
}
NEW_MODE = 0o644
MODES = {"/usr/local/bin/alfred-photon-clear": 0o755}
# The installer's own helper must be the one installed, and the board reuses squads.py.
DEPENDENCIES = {
    LIBRARY + "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
    LIBRARY + "squads.py": "27d5dc7efe8499be023ba139a78d53799e27f6446e37ec97347900e5bd64c79d",
}
BACKUP_SCHEMA = "alfred.development-handoff44-backup/1"


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
    return {"status": "ROLLED_BACK_HELD", "service_action": "systemctl daemon-reload"}


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
                               os.geteuid(), os.getegid(), MODES.get(name, NEW_MODE))
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
        "service_action": "systemctl daemon-reload",
        "next": "systemd-sysusers; systemd-tmpfiles --create; systemctl enable --now "
                "alfred-photon-requests.path alfred-dev-board.timer",
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
