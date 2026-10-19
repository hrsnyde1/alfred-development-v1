"""handoff.33 overlay: the owner's one approval is the CTO's plan, not the request preview.

Owner-authorized 2026-10-19: "separate planning approval from routine development ...
That's too much human-in-the-loop." "All I want is a simple approval text of the plan
that is being mapped out. I don't want the first one where it's development task
created." Choices: every request waits for the owner's yes on the plan; the plan text is
the goal, who does what and which files, in a few lines, ending "Reply yes to start."
- delegation.json: development_approval "mode": "owner" (the project list and the
  publication and merge delegation are unchanged).
- owner_grants.py: the policy's new mode; for those projects the CTO plan goes to the
  owner as one short text, valid 12 hours, approved by a native in-thread "yes".
- trusted_intake_development.py (both installed copies): a request for such a project is
  filed with no preview (owner identity, DM, binding to the owner's own message, the
  registered project and the wording rule are all still checked); the plan text names
  the project by its registry name.
- independent_qa worker.py: accepts that owner-reply grant and the new policy shape.
- host.py: the 12-hour window counts as open; the poll accepts the direct-filing route.
- squads.py: the squad chat says the plan went to the owner.
Installs only after handoff.32. The intake is restarted to load the new code. Rollback
restores every file, including the previous policy.
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
QA = "/opt/alfred-independent-qa-v1/independent_qa/"
POLICY = "/etc/alfred-development/delegation.json"
DESTINATIONS = {
    POLICY: "development_handoff33/delegation.json",
    DEVELOPER + "owner_grants.py": "developer_v1/owner_grants.py",
    DEVELOPER + "trusted_intake_development.py": "developer_v1/trusted_intake_development.py",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "developer_v1/trusted_intake_development.py",
    QA + "worker.py": "independent_qa/worker.py",
    LIBRARY + "host.py": "fresh_v1/host.py",
    LIBRARY + "squads.py": "fresh_v1/squads.py",
}
# Exactly the bytes installed through handoff.32 (main at cc6263f), read from the host.
BASE = {
    POLICY: "5e0b0a62de362736695e8c2f46bf04c1d61c2116902ef5d11f1442e7edca05bc",
    DEVELOPER + "owner_grants.py": "cca55707f1854b9fdb4a5698f2672af33f1400e478033953869dd512b3ad7c11",
    DEVELOPER + "trusted_intake_development.py": "0bc7230ae993046f68993f2b089528d32d8fb12dc4ca42709ceb261251954bc4",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "0bc7230ae993046f68993f2b089528d32d8fb12dc4ca42709ceb261251954bc4",
    QA + "worker.py": "5aa8aaa3bb7c84371a6012c2d56525b200f3ae4db936ee9d3749e13b600fe2e1",
    LIBRARY + "host.py": "a97095c318a35224d777b2f1ffa8d5031a48d37ba72576859efd83f8616cd818",
    LIBRARY + "squads.py": "8c18094ab8090ebbb76d8b6074cc671debef06a23396af34fa66889a5416f1e8",
}
NEW_MODE = 0o644
# Unchanged code the changed files call into, as installed now.
DEPENDENCIES = {
    LIBRARY + "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
    LIBRARY + "protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
    LIBRARY + "handoffs.py": "fe3023677b36f9d7a81148ebcb1877f00bc5e72d23a208de131f64da2e7f65cf",
    LIBRARY + "role.py": "bdcb9017d9bf56cacec72ccc52a68152bd864b7eee351167634870f15a425d52",
    DEVELOPER + "router.py": "aeb37188326f7ce6ffc7e51c2a288f13fb2520db20112e1381a31fcb86b4680c",
    DEVELOPER + "approval_transition.py": "bbb4fdcf97e245af26ce9ab7fa3942c6a238770b6574d3e9e592094b93bb9f7c",
    DEVELOPER + "publication_approval.py": "153b1a457680f34b093e6eed5d7c2e2a812a2889db97f43ac873c2e52327b2b5",
    DEVELOPER + "owner_approval.py": "8ca48230354ead6855992fd013b28fd7d6f7ee64f406de388baf56322c2a2026",
    DEVELOPER + "owner_passkey.py": "918b8c8ac9e0b3fbb268f68df42d7bc4b519a270c750b5ad2d1e5df6f0a3444a",
    DEVELOPER + "undo_approval.py": "421a62b04e68e0d687fba518b0dace08b11bcecc2c3919bb64f9148e46684e2a",
    DEVELOPER + "gateway_adapter.py": "64b1cb2a78614ca09e1e9166d5fae3c26bdec8d2bae0e733af0b0309f2274a8e",
    DEVELOPER + "pipeline.py": "4034f55dfda08de718bf28b124bb2be7c6f218289041391051443dba8834ff10",
}
BACKUP_SCHEMA = "alfred.development-handoff33-backup/1"


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
        "next": "listed projects: no preview; the owner replies yes to the CTO plan text",
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
