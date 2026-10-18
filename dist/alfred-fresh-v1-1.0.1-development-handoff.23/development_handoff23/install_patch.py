"""handoff.23 overlay: the development agents use their own long-lived Claude token.

demo-site T-0004 (2026-10-18 18:03 UTC): the frontend agent failed in seconds. The
owner's Claude Code login needed a token refresh, which writes a lock and temporary
files beside ~/.claude.json, and the Evidence sandbox keeps /home read-only.
- real_worker.py: Claude runs with the agents' own token (`claude setup-token`, saved
  root-owned by `alfred-dev-ops claude-token`) and a private HOME under
  /var/lib/alfred-development-state. Login, token and API errors count as the provider
  being unavailable, so the approved Codex fallback runs instead of failing the task.
- alfred-dev-ops: `claude-token` saves that token (hidden input, never logged).
- 60-claude-agents.conf: no longer opens the owner's own Claude login to the sandbox.
Run `systemctl daemon-reload`. Nothing restarts.
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

DEVELOPER = "/opt/alfred-developer-v1/developer_v1/"
DROP_INS = "/etc/systemd/system/alfred-development-evidence.service.d/"
DROP_IN = DROP_INS + "40-fresh-v1.conf"
CLAUDE_LOGIN = DROP_INS + "60-claude-agents.conf"
DESTINATIONS = {
    DEVELOPER + "real_worker.py": "developer_v1/real_worker.py",
    "/usr/local/sbin/alfred-dev-ops": "ops/alfred_dev_ops.py",
    CLAUDE_LOGIN: "development_handoff23/60-claude-agents.conf",
}
# Exactly the bytes handoffs 21 and 22 leave behind.
BASE = {
    DEVELOPER + "real_worker.py": "e4365dec95162b4789a66cd530863011d8c9f0569027132abc39ce6b6c62097a",
    "/usr/local/sbin/alfred-dev-ops": "060860679e6b4a23aa742ea9b65b481837e1f76dc6116786bdc4076ec85d65f0",
    CLAUDE_LOGIN: "701a3e3380bae95289d0cc0ca2076a10a0003a124577f30791cae20aeec8d2fe",
}
NEW_MODE = 0o644
# What the changed files work with must be what is installed now.
DEPENDENCIES = {
    DEVELOPER + "pipeline.py": "4cf1e7a61622677144c8f3f33a4a14adae05daed0e4c6c436132c990c4c04b62",
    DEVELOPER + "agent_profiles.py": "d9731eae53ffc27b4d453d946d044f2b93bde04e53e47fd9ba3221745149c775",
    DEVELOPER + "agent_profiles.json": "1194c14f4b3260dce2f2baef7e87c330c13135e2b1db28de82d9dd9d788ffd7e",
    DEVELOPER + "router.py": "69c70a8326bc20b129a80d6413ffe0581807c28d73b14f4c11a94d36370f4649",
    DEVELOPER + "execution.py": "b14d0162f61b9cc17d4b6fd06c1f5e2830c31803a43966198c59ced2f69288a7",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py": "f9ff7c6636e36be1273cbade85b6f153f40c2db43d6dda3908db4256679d0b70",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py": "d651db771116761d16c9c9d230ba8b7e7045f4bc488f5b87febfc87d02f3485d",
    DROP_IN: "436dde472b64e6f2e64a1a44fe573e59157aeea0e4000c30f3212ba15f7ef484",
    DROP_INS + "50-project-repos.conf": "cf1ef2e0280c419dee9e9c48bac4d92a754a74f72f3aa59ccdcdaa09e2b82db2",
}
BACKUP_SCHEMA = "alfred.development-handoff23-backup/1"


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
        "service_action": "systemctl daemon-reload",
        "claude_token": "run `alfred-dev-ops claude-token`; until then Codex builds",
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
