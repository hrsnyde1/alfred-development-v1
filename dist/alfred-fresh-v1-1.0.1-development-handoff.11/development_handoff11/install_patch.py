"""Seven-file handoff.11 overlay: plain-language owner texts, "yes" approvals, resend.

The owner is the only person on this Photon line and asked for the simplest flow:
- intake (both paths): the request preview is plain language; "yes" confirms it.
- publication_approval.py: the publication approval is one plain line plus any
  informational Reviewer notes; reply "yes" in its thread within 12 hours. Older
  5-minute exact-phrase receipts still verify unchanged.
- host.py: passes the CTO plan's goal as that plain line; can read resend records.
- handoffs.py: an expired, unanswered approval is resent only after the owner runs
  `alfred-dev-ops resend <task>`, once per authorization.
- completion.py: the completion text is plain language without task numbers.
- /usr/local/sbin/alfred-dev-ops: gains `resend <task>`.
The intake must be restarted to load the intake and publication modules.
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
COMPLETION = "/usr/local/lib/alfred-completion-v1/completion_integration/"
OPS = "/usr/local/sbin/alfred-dev-ops"
DESTINATIONS = {
    INTAKE: "developer_v1/trusted_intake_development.py",
    DEVELOPER + "trusted_intake_development.py": "developer_v1/trusted_intake_development.py",
    DEVELOPER + "publication_approval.py": "developer_v1/publication_approval.py",
    LIBRARY + "handoffs.py": "fresh_v1/handoffs.py",
    LIBRARY + "host.py": "fresh_v1/host.py",
    COMPLETION + "completion.py": "completion_integration/completion.py",
    OPS: "ops/alfred_dev_ops.py",
}
# Exactly the bytes installed by handoff.8, 9 and 10 (and the completion module).
BASE = {
    INTAKE: "883a779f82f760777d59761abd1b9125f61ce4522b184936d146d234f5149952",
    DEVELOPER + "trusted_intake_development.py": "883a779f82f760777d59761abd1b9125f61ce4522b184936d146d234f5149952",
    DEVELOPER + "publication_approval.py": "3c5033c7f2d54e199cc2b7b9a39a680387966bd9b7bcafb100a8756f23ad1257",
    LIBRARY + "handoffs.py": "46045d3a67b6f2eaf8be8a1202db86b1032f3f53ba81a7bfd1adfa79a000204d",
    LIBRARY + "host.py": "a287b682ffb6cc761df2adde7cb781b9e4278d154ec8c1ec05b33969bf3abf02",
    COMPLETION + "completion.py": "24340918bf0331b127a99475286150545fb20fca1d5972887014cbe1374c325f",
    OPS: "3c4d70877793358f403092fc5f06a2b4ea70103a21bbf830dc017cc2b69c223b",
}
# Everything else handoff.8 and handoff.10 installed must be unchanged.
INSTALLED = {
    DEVELOPER + "owner_grants.py": "f54d0f51bac5af08c85968da3d81b7ff419f0654d1326886dcc8140653b02fb9",
    DEVELOPER + "pipeline.py": "e22bc7b0c334b243db38b22b87766862cad5b5a10a7aec6c26f60d8c0a97c91a",
    QA + "worker.py": "709614f4ef24a8c4e45d323e1b921b8a2b7dac0a9531d5fb3deff89f0c37889b",
    PUBLISHER + "worker.py": "1c31211c1d1306ba03926f547e5aba093a3f1d1f7d0b679837a959e2293ecd98",
    DEVELOPER + "schemas/publication-plan.schema.json": "80cbbde11a0a72ce5e86bd8d797663f61ebed2c5b912ba6b6c76649bf650d83e",
}
# The handoff.5 drop-in and every other fresh V1 runtime file; each must still match.
DEPENDENCIES = {
    **INSTALLED,
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
BACKUP_SCHEMA = "alfred.development-handoff11-backup/1"


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
