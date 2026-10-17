"""handoff.17 overlay (handoff.15 repackaged): the development team fixes its own work.

When Independent QA or the Reviewer finds problems, the same approved team redoes
the work with those findings and the previous attempt's files, from the same
approved baseline and within the same scope, for up to three rounds. Each round
claims the original approval once, only after the previous round completed. QA and
the Reviewer then check that round exactly as they check round 0. After the third
failed round the owner gets one plain-language text and the task stops; it no longer
blocks other requests. Tasks planned before handoff.12 keep the old behaviour.

QA also accepts a developer changing only some of its assigned files (at least one,
none outside them). The developer runner's claim scan no longer trips over reports
when a task has more than one agent or round.

Requires handoff.16 (team skills) and handoff.14. Repackaged from handoff.15, which
checked two Gateway-owned files as root-owned and so could not install. The intake is restarted.
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
DESTINATIONS = {
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py": "fresh_v1/host.py",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py": "fresh_v1/role.py",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py": "fresh_v1/handoffs.py",
    "/opt/alfred-developer-v1/developer_v1/pipeline.py": "developer_v1/pipeline.py",
    "/opt/alfred-developer-v1/developer_v1/run_task.py": "developer_v1/run_task.py",
    "/opt/alfred-developer-v1/developer_v1/owner_grants.py": "developer_v1/owner_grants.py",
    "/opt/alfred-developer-v1/developer_v1/execution.py": "developer_v1/execution.py",
    "/opt/alfred-independent-qa-v1/independent_qa/worker.py": "independent_qa/worker.py",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "developer_v1/trusted_intake_development.py",
    "/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py": "developer_v1/trusted_intake_development.py",
}
# Exactly the bytes handoffs 12, 13 and 14 leave behind.
BASE = {
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py": "8f080553b94e462ffb251159164c6be41d808dde5ff2230c5070909a52c3ddd3",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py": "7e8e4ee0495dbeaf8e812576f8f8c1ede0e16b1f8c426baaa973239dd522d0ab",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py": "1d612babbbfccd422b5ba7198ae01e5943f84f2f0cd6b4400c5425ec18caecbe",
    "/opt/alfred-developer-v1/developer_v1/pipeline.py": "2b78eaabfd5de738c921cd6f1377ee7ea192759bc2a3907014948702063f5599",
    "/opt/alfred-developer-v1/developer_v1/run_task.py": "dd93a1a89975b8a36bc0ce9108cee81dfb18afb131cae05e4dcdc1e95cb69266",
    "/opt/alfred-developer-v1/developer_v1/owner_grants.py": "f54d0f51bac5af08c85968da3d81b7ff419f0654d1326886dcc8140653b02fb9",
    "/opt/alfred-developer-v1/developer_v1/execution.py": "01a8aaba3ebad98cc47f3905ac146460ca0f79504ae9166cfac71ec4ef6f810c",
    "/opt/alfred-independent-qa-v1/independent_qa/worker.py": "709614f4ef24a8c4e45d323e1b921b8a2b7dac0a9531d5fb3deff89f0c37889b",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "d1f70a05cc82f64828e55e66ece75d594efca41323c2ad21c342c7843699426f",
    "/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py": "d1f70a05cc82f64828e55e66ece75d594efca41323c2ad21c342c7843699426f",
}
SEMANTIC = {}
# Everything else installed through handoff.14 must be unchanged.
INSTALLED = {
    "/opt/alfred-developer-v1/developer_v1/publication_approval.py": "118e66841b8736f469da546d42043f6e2841d9bece9d20fa8124e7bac80024cf",
    "/opt/alfred-draft-pr-publisher-v1/worker.py": "1c31211c1d1306ba03926f547e5aba093a3f1d1f7d0b679837a959e2293ecd98",
    "/opt/alfred-developer-v1/developer_v1/schemas/publication-plan.schema.json": "80cbbde11a0a72ce5e86bd8d797663f61ebed2c5b912ba6b6c76649bf650d83e",
    "/usr/local/lib/alfred-completion-v1/completion_integration/completion.py": "c269d3ee1003cb26722619420cde0718a634dca21feaa914d56210c064c0e545",
    "/usr/local/sbin/alfred-dev-ops": "0966e652667410920323a5f6b8d47a8ed2c574da4a4006166d3191641babd2ff",
    "/opt/alfred-independent-qa-v1/independent_qa/config.json": "2337732171fab329438a26ef09ba9f69c23d3d5d406d53c65e13524738ca5cea",
    "/etc/alfred-development/delegation.json": "6bc1befaf2d4df3320cab7d16aef2e2d2b75feb286869bfd14d98cdb601ed157",
    "/etc/alfred-fresh-v1/policy.json": "b33d66fc4f19ad3f9a772f53833e758d411fa4e305eef702e5fe733cd4dfc9d6",
    "/opt/alfred-developer-v1/developer_v1/router.py": "69c70a8326bc20b129a80d6413ffe0581807c28d73b14f4c11a94d36370f4649",
    "/opt/alfred-developer-v1/developer_v1/gateway_adapter.py": "64b1cb2a78614ca09e1e9166d5fae3c26bdec8d2bae0e733af0b0309f2274a8e",
    "/usr/local/lib/alfred-fresh-v1/v1_cto/cto.py": "d60da3f6c230ef741c97f9689cd6fe85825b376c6e7029935165adb79b684ec1",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/diagnostics.py": "c5862c14b39b22b7e6faef07aea1d4c32b5ab0df20aab987d4a0fed33b763e0e",
    "/usr/local/lib/alfred-fresh-v1/v1_cto/plan.schema.json": "922a477d0d9c9cd46a0f23cc32b92f0f7881314315e185cca8661664ce03387c",
    "/opt/alfred-developer-v1/developer_v1/team_skills.py": "42a701e0b52ab65792d8d1d8837bdb69e5879bae9060810a0ad6b369b5f95c8e",
    "/opt/alfred-developer-v1/developer_v1/real_worker.py": "2363384faaaa9c14d0c148e0d0d879f39a2d372e76b87be90a3f1c86dcc33840",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/qa_recovery.py": "0dfb91ff0265d8ddb669a33edf34824213118c97bd6fd334a31a81ca1c88d1c6",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/recovery.py": "d6e3f3627f5f6c82223fe16dab7ef43d619cda4d98c4edf99467a76c0df688c4",
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
BACKUP_SCHEMA = "alfred.development-handoff17-backup/1"


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
    return {"status": "ROLLED_BACK_HELD", "service_action": "restart alfred-development-intake required"}


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
