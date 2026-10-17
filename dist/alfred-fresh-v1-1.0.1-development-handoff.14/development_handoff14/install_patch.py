"""One-file handoff.14 overlay: a held task no longer blocks later requests.

After handoff.12, demo-site T-0001 was filed but never started: every poll stopped
at dev-v1-accept T-0010, held because its Reviewer did not approve. A held task does
nothing more until someone acts on it, so the poll now moves past it (as it already
does for tasks waiting on the owner) and reports it only when nothing else ran. Its
evidence is untouched and nothing is retried. The Evidence poll imports host.py on
each run, so nothing restarts.
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
POLICY = "/etc/alfred-fresh-v1/policy.json"
DELEGATION = "/etc/alfred-development/delegation.json"
DESTINATIONS = {
    LIBRARY + "host.py": "fresh_v1/host.py",
}
# Exactly the handoff.12 host.
BASE = {
    LIBRARY + "host.py": "1999463059d2617796183dd0c1517bb2be1d8da0f93a45fde7e70a5b34dd9e08",
}
SEMANTIC = {}
# Everything handoff.8 to handoff.12 installed must be unchanged, except the files
# handoff.13 (team skills) replaces, so this installs before or after it.
INSTALLED = {
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py": "1d612babbbfccd422b5ba7198ae01e5943f84f2f0cd6b4400c5425ec18caecbe",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "d1f70a05cc82f64828e55e66ece75d594efca41323c2ad21c342c7843699426f",
    "/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py": "d1f70a05cc82f64828e55e66ece75d594efca41323c2ad21c342c7843699426f",
    "/opt/alfred-independent-qa-v1/independent_qa/config.json": "2337732171fab329438a26ef09ba9f69c23d3d5d406d53c65e13524738ca5cea",
    "/etc/alfred-development/delegation.json": "6bc1befaf2d4df3320cab7d16aef2e2d2b75feb286869bfd14d98cdb601ed157",
    "/etc/alfred-fresh-v1/policy.json": "b33d66fc4f19ad3f9a772f53833e758d411fa4e305eef702e5fe733cd4dfc9d6",
    "/opt/alfred-developer-v1/developer_v1/owner_grants.py": "f54d0f51bac5af08c85968da3d81b7ff419f0654d1326886dcc8140653b02fb9",
    "/opt/alfred-developer-v1/developer_v1/publication_approval.py": "118e66841b8736f469da546d42043f6e2841d9bece9d20fa8124e7bac80024cf",
    "/opt/alfred-independent-qa-v1/independent_qa/worker.py": "709614f4ef24a8c4e45d323e1b921b8a2b7dac0a9531d5fb3deff89f0c37889b",
    "/opt/alfred-draft-pr-publisher-v1/worker.py": "1c31211c1d1306ba03926f547e5aba093a3f1d1f7d0b679837a959e2293ecd98",
    "/opt/alfred-developer-v1/developer_v1/schemas/publication-plan.schema.json": "80cbbde11a0a72ce5e86bd8d797663f61ebed2c5b912ba6b6c76649bf650d83e",
    "/usr/local/lib/alfred-completion-v1/completion_integration/completion.py": "c269d3ee1003cb26722619420cde0718a634dca21feaa914d56210c064c0e545",
    "/usr/local/sbin/alfred-dev-ops": "0966e652667410920323a5f6b8d47a8ed2c574da4a4006166d3191641babd2ff",
}
# The handoff.5 drop-in and every other fresh V1 runtime file; each must still match.
DEPENDENCIES = {
    **INSTALLED,
    DROP_IN: "436dde472b64e6f2e64a1a44fe573e59157aeea0e4000c30f3212ba15f7ef484",
    **{
        LIBRARY + name: sha
        for name, sha in {
            "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
            "qa_recovery.py": "0dfb91ff0265d8ddb669a33edf34824213118c97bd6fd334a31a81ca1c88d1c6",
            "diagnostics.py": "c5862c14b39b22b7e6faef07aea1d4c32b5ab0df20aab987d4a0fed33b763e0e",
            "protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
            "recovery.py": "d6e3f3627f5f6c82223fe16dab7ef43d619cda4d98c4edf99467a76c0df688c4",
        }.items()
    },
}
BACKUP_SCHEMA = "alfred.development-handoff14-backup/1"


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


def expected_json(name):
    """The exact JSON a SEMANTIC file must hold, shipped beside this installer."""
    return json.loads((Path(__file__).resolve().parents[1] / SEMANTIC[name]).read_bytes())


def resolved_bases(root):
    """BASE with each SEMANTIC file pinned to its current bytes once its content matches."""
    bases = dict(BASE)
    for name in SEMANTIC:
        raw = upgrade.target(root, name).read_bytes()
        try:
            current = json.loads(raw)
        except ValueError:
            current = None
        if current != expected_json(name):
            raise ValueError("installed contract mismatch: " + name)
        bases[name] = upgrade.digest(raw)
    return bases


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
        semantic = entry["path"] in SEMANTIC
        if entry["backup"] != "file-" + str(i) or (
                not semantic and entry["sha256"] != BASE[entry["path"]]):
            raise ValueError("rollback backup contract mismatch")
        _, raw = checked(backup / entry["backup"], entry["sha256"])
        if semantic and json.loads(raw) != expected_json(entry["path"]):
            raise ValueError("rollback backup contract mismatch")
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
    return {"status": "ROLLED_BACK_HELD", "service_action": "none; the Evidence poll imports host.py on each run"}


def install(release, pin, root, backup, *, fail_after=None):
    paused(root)
    verified = upgrade.verify(release, pin)
    content = {n: (release / n).read_bytes() for n in DESTINATIONS.values()}
    if any(upgrade.digest(raw) != verified[n] for n, raw in content.items()):
        raise ValueError("release changed after verification")
    previous = {n: checked(upgrade.target(root, n), sha) for n, sha in resolved_bases(root).items()}
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
        "service_action": "none; the Evidence poll imports host.py on each run",
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
