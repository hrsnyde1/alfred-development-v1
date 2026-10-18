"""handoff.31 overlay: the pipeline merges its own approved work, and "undo" takes it back.

Owner-authorized 2026-10-18: "I want ... the CTO to be able to merge the repositories on
each GitHub. I don't want to have to be the one to do it. It should automatically do it
and update the code." Choices: auto-merge yes; undo by replying "undo"; squash merges.
- delegation.json: "merge_approval": "delegated" (the project list is unchanged).
- owner_grants.py / independent_qa worker.py: both copies of the policy check accept the
  new key; "owner" (or absent) keeps merging the owner's step.
- publication_approval.py: records the delegated merge decision once per plan.
- undo_approval.py (new): the owner's native "undo" reply to the merged change's text,
  within 24 hours, single use.
- trusted_intake_development.py (both installed copies): the merge and undo operations.
- Publisher worker.py: marks the task's own draft PR ready and squash-merges it; reverts
  exactly that squash commit after "undo", refusing if main changed in a clashing way.
- handoffs.py / host.py / role.py / diagnostics.py: the recorded merge and undo stages.
- completion.py / runtime.py: "merged into main", the commit link and how to undo.
- squads.py: the squad chat says merged into main, and undone.
Installs only after handoff.30 (QA's worker is pinned at handoff.30's bytes). The intake
is restarted to load the new code. Rollback restores every file and removes the new one.
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
COMPLETION = "/usr/local/lib/alfred-completion-v1/completion_integration/"
PUBLISHER = "/opt/alfred-draft-pr-publisher-v1/"
QA = "/opt/alfred-independent-qa-v1/independent_qa/"
POLICY = "/etc/alfred-development/delegation.json"
DESTINATIONS = {
    POLICY: "development_handoff31/delegation.json",
    DEVELOPER + "owner_grants.py": "developer_v1/owner_grants.py",
    DEVELOPER + "publication_approval.py": "developer_v1/publication_approval.py",
    DEVELOPER + "undo_approval.py": "developer_v1/undo_approval.py",
    DEVELOPER + "trusted_intake_development.py": "developer_v1/trusted_intake_development.py",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "developer_v1/trusted_intake_development.py",
    QA + "worker.py": "independent_qa/worker.py",
    PUBLISHER + "worker.py": "draft_pr_publisher/worker.py",
    COMPLETION + "completion.py": "completion_integration/completion.py",
    COMPLETION + "runtime.py": "completion_integration/runtime.py",
    LIBRARY + "handoffs.py": "fresh_v1/handoffs.py",
    LIBRARY + "host.py": "fresh_v1/host.py",
    LIBRARY + "role.py": "fresh_v1/role.py",
    LIBRARY + "diagnostics.py": "fresh_v1/diagnostics.py",
    LIBRARY + "squads.py": "fresh_v1/squads.py",
}
# Exactly the bytes installed through handoff.29, plus handoff.30's QA worker.
BASE = {
    POLICY: "3c3f9eae99fcd55ea339da7410f7b2b8cd30341937501d114c33910b9ee790e2",
    DEVELOPER + "owner_grants.py": "8b67f513809d5af4c097c54d7edffa4145dab22e2ba49dac0a42e00c4bd26b4f",
    DEVELOPER + "publication_approval.py": "c531cc2c4cf98405b0818139271cfe6c367bad597ee7f1519246009121fb6a78",
    DEVELOPER + "undo_approval.py": None,
    DEVELOPER + "trusted_intake_development.py": "553dfe1d3ea87cd011ecb328167d68ddf8f3bf97bc4f7105fe85c1b39bf9644e",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "553dfe1d3ea87cd011ecb328167d68ddf8f3bf97bc4f7105fe85c1b39bf9644e",
    QA + "worker.py": "e31d82750f6258042c2b47b2d62bf5bf9505c407e24b4852b33d11e3c1267e37",
    PUBLISHER + "worker.py": "1c31211c1d1306ba03926f547e5aba093a3f1d1f7d0b679837a959e2293ecd98",
    COMPLETION + "completion.py": "47e86025b68f9453a7eb61dd02bf989015c3df242ed01306eb540fdcb55d07b6",
    COMPLETION + "runtime.py": "d34fad6928b5a6b7508678887e49ce9d6fc4cd2ddfb18382ba70be26f0207c61",
    LIBRARY + "handoffs.py": "f9ff7c6636e36be1273cbade85b6f153f40c2db43d6dda3908db4256679d0b70",
    LIBRARY + "host.py": "f73a6ec5f9320b23daafc3a53df919cbbdc5cf354f33d8cf4cffa1edbd961546",
    LIBRARY + "role.py": "00a2349ba3ecb5b835c9a3bf89725d0082feb3fc9c2c471bfaaae24d4efe598a",
    LIBRARY + "diagnostics.py": "c5862c14b39b22b7e6faef07aea1d4c32b5ab0df20aab987d4a0fed33b763e0e",
    LIBRARY + "squads.py": "e45a1d99d11667fab2b896030d06a770bc66932375873c6ce19c2ee9323bae21",
}
NEW_MODE = 0o644
# Unchanged code the new stages call into, as installed now.
DEPENDENCIES = {
    LIBRARY + "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
    LIBRARY + "protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
    DEVELOPER + "router.py": "aeb37188326f7ce6ffc7e51c2a288f13fb2520db20112e1381a31fcb86b4680c",
    COMPLETION + "delivery.py": "62abc66a9608a54505e5fba9595ec4e53b97511ee8e2b2e0d482239b25ef7eb2",
    PUBLISHER + "askpass.py": "fd1e750d34feb26f7c6bf90e0862b46f356d7b1c051713f9c858cfd8faaabe35",
}
BACKUP_SCHEMA = "alfred.development-handoff31-backup/1"


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
    return {"status": "ROLLED_BACK_HELD", "service_action": "restart alfred-development-intake.service"}


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
        "service_action": "restart alfred-development-intake.service",
        "next": "delegated projects are squash-merged after QA and review; reply undo to take one back",
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
