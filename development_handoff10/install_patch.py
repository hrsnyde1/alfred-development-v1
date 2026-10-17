"""Four-file handoff.10 overlay: informational Reviewer findings do not block.

T-0009 was held after an APPROVED review because the Fresh V1 poll required an empty
findings list, while the Reviewer only approves when every finding is "info". Now:
- fresh_v1/handoffs.py: advance only when decision is APPROVED, correctness and scope
  PASS, the next stage is draft PR preparation, every acceptance criterion is PASS,
  and every finding is exactly severity "info"; anything else holds as before.
- draft_pr_publisher/worker.py: independently refuses non-info findings and seals the
  informational ones into the publication plan as review_findings.
- developer_v1/publication_approval.py: the owner's publication approval text lists
  those notes; without notes it is byte-identical to before.
- developer_v1/schemas/publication-plan.schema.json: optional info-only review_findings.
The intake must be restarted to load publication_approval.py.
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
DROP_IN = "/etc/systemd/system/alfred-development-evidence.service.d/40-fresh-v1.conf"
INTAKE = "/usr/local/lib/alfred-v1.1/trusted_intake.py"
PUBLISHER = "/opt/alfred-draft-pr-publisher-v1/"
DESTINATIONS = {
    LIBRARY + "handoffs.py": "fresh_v1/handoffs.py",
    PUBLISHER + "worker.py": "draft_pr_publisher/worker.py",
    DEVELOPER + "publication_approval.py": "developer_v1/publication_approval.py",
    DEVELOPER + "schemas/publication-plan.schema.json": "developer_v1/schemas/publication-plan.schema.json",
}
# Exactly the files installed since handoff.2 / the Publisher v1.1.0 upgrade.
BASE = {
    LIBRARY + "handoffs.py": "a515f6e3ff0a4babe44a33c28541657544468f7a233ee8eeb70e4ab48037248c",
    PUBLISHER + "worker.py": "051ed86f1fe07260fd663636b665bbef5ddab6c2b8852ecc0a777264ee944ec3",
    DEVELOPER + "publication_approval.py": "827dbcaf8c3a7a420fb67acc102ff824725f1adf853134fd772100cdb52601e0",
    DEVELOPER + "schemas/publication-plan.schema.json": "7b034bbac34ad1d0726c0fcb5b559a922a5b0f965a2d7d2b9b9f85616a750a56",
}
# handoff.9 must be installed: the intake at both paths.
HANDOFF9 = {
    INTAKE: "883a779f82f760777d59761abd1b9125f61ce4522b184936d146d234f5149952",
    DEVELOPER + "trusted_intake_development.py": "883a779f82f760777d59761abd1b9125f61ce4522b184936d146d234f5149952",
}
# handoff.8 must be installed: its four files at their installed-after bytes.
HANDOFF8 = {
    LIBRARY + "host.py": "a287b682ffb6cc761df2adde7cb781b9e4278d154ec8c1ec05b33969bf3abf02",
    DEVELOPER + "owner_grants.py": "f54d0f51bac5af08c85968da3d81b7ff419f0654d1326886dcc8140653b02fb9",
    DEVELOPER + "pipeline.py": "e22bc7b0c334b243db38b22b87766862cad5b5a10a7aec6c26f60d8c0a97c91a",
    QA + "worker.py": "709614f4ef24a8c4e45d323e1b921b8a2b7dac0a9531d5fb3deff89f0c37889b",
}
# The handoff.5 drop-in and every other fresh V1 runtime file; each must still match.
DEPENDENCIES = {
    **HANDOFF8,
    **HANDOFF9,
    DROP_IN: "436dde472b64e6f2e64a1a44fe573e59157aeea0e4000c30f3212ba15f7ef484",
    **{
        LIBRARY + name: sha
        for name, sha in {
            "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
            "role.py": "3c2c3968cb858e4469ce11e82dd2bbfd7f61ea43f9dcc783145cbf21f524a688",
            "qa_recovery.py": "0dfb91ff0265d8ddb669a33edf34824213118c97bd6fd334a31a81ca1c88d1c6",
            "diagnostics.py": "c5862c14b39b22b7e6faef07aea1d4c32b5ab0df20aab987d4a0fed33b763e0e",
            "protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
            "recovery.py": "d6e3f3627f5f6c82223fe16dab7ef43d619cda4d98c4edf99467a76c0df688c4",
        }.items()
    },
}
BACKUP_SCHEMA = "alfred.development-handoff10-backup/1"


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
    return {"status": "ROLLED_BACK_HELD", "service_action": "restart alfred-development-intake required"}


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
        "service_action": "restart alfred-development-intake required",
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
