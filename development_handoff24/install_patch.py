"""handoff.24 overlay: the owner can confirm a completion text they received although its
delivery record stayed uncertain.

demo-site T-0003 (2026-10-18 17:57 UTC): the owner received the "All done" text, but the
sidecar's acknowledgement arrived after the old two-second bound (fixed for later sends by
handoff.23). The delivery record stayed `uncertain` with no receipt, the host recorded
`completion.failure.json`, and the poll holds the task for good.

- alfred-dev-ops: `confirm-delivered project/task` writes a root-owned confirmation and a
  byte-identical snapshot of delivery.json into the task directory, only for a task whose
  completion was attempted and whose single delivery record is `uncertain` with no
  receipt and names the task's published draft PR.
- host.py: the poll reads that confirmation as the task's completion and records
  complete.json. Nothing is sent or resent; the uncertain record, the attempt and the
  failure evidence are never changed.
Installs only after handoff.23 and handoff.26, which pin these files as they are now.
Nothing restarts. Existing delivery records are not changed.
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
COMPLETION = "/usr/local/lib/alfred-completion-v1/completion_integration/"
DESTINATIONS = {
    # The installed host.py plus this fix only (main also has unreleased work).
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py": "development_handoff24/host.py",
    "/usr/local/sbin/alfred-dev-ops": "ops/alfred_dev_ops.py",
}
# Exactly the bytes handoffs 22 (host.py) and 26 (alfred-dev-ops) leave behind.
BASE = {
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py": "d651db771116761d16c9c9d230ba8b7e7045f4bc488f5b87febfc87d02f3485d",
    "/usr/local/sbin/alfred-dev-ops": "4e460fe6c4452d65982e7f18f5eef61f8ddadf1fbfc3c9706395a9e47a2aa849",
}
SEMANTIC = {}
# Everything else installed through handoffs 23 and 26 must be unchanged.
INSTALLED = {
    COMPLETION + "runtime.py": "d34fad6928b5a6b7508678887e49ce9d6fc4cd2ddfb18382ba70be26f0207c61",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py": "f9ff7c6636e36be1273cbade85b6f153f40c2db43d6dda3908db4256679d0b70",
    COMPLETION + "delivery.py": "62abc66a9608a54505e5fba9595ec4e53b97511ee8e2b2e0d482239b25ef7eb2",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py": "71d74bc7c2523d06f4dff5248a98b6b4b59ee0ccc20b51ec8284dadbd69a5422",
    "/opt/alfred-developer-v1/developer_v1/pipeline.py": "4cf1e7a61622677144c8f3f33a4a14adae05daed0e4c6c436132c990c4c04b62",
    "/opt/alfred-developer-v1/developer_v1/run_task.py": "167f6035beec65c440fe1bac6ec341a2e7ae8b40aff33ed344d5e06b47e98843",
    "/opt/alfred-developer-v1/developer_v1/owner_grants.py": "5043fb42a6f017ec3561f7570aa1fb9997bed6f7dcbd284b8f9c9871bb254117",
    "/opt/alfred-developer-v1/developer_v1/execution.py": "b14d0162f61b9cc17d4b6fd06c1f5e2830c31803a43966198c59ced2f69288a7",
    "/opt/alfred-independent-qa-v1/independent_qa/worker.py": "50a5d0adca3967ec42bbd773d0fc53aee8e3a34a5ad977d155cba5d9c7c8f8c3",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "0fed5b5d6bfb52fd8483e7352c29d8a7b400eeaa8a41ab2ad4e9bcc8f5987f43",
    "/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py": "0fed5b5d6bfb52fd8483e7352c29d8a7b400eeaa8a41ab2ad4e9bcc8f5987f43",
    "/opt/alfred-developer-v1/developer_v1/publication_approval.py": "118e66841b8736f469da546d42043f6e2841d9bece9d20fa8124e7bac80024cf",
    "/opt/alfred-draft-pr-publisher-v1/worker.py": "1c31211c1d1306ba03926f547e5aba093a3f1d1f7d0b679837a959e2293ecd98",
    "/opt/alfred-developer-v1/developer_v1/schemas/publication-plan.schema.json": "80cbbde11a0a72ce5e86bd8d797663f61ebed2c5b912ba6b6c76649bf650d83e",
    "/usr/local/lib/alfred-completion-v1/completion_integration/completion.py": "c269d3ee1003cb26722619420cde0718a634dca21feaa914d56210c064c0e545",
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
    "/opt/alfred-developer-v1/developer_v1/real_worker.py": "3fba2a76b88c9b93a5217a4e69079178d02303d09137fe93228b2807a61e01c6",
    "/opt/alfred-developer-v1/developer_v1/agent_profiles.py": "d9731eae53ffc27b4d453d946d044f2b93bde04e53e47fd9ba3221745149c775",
    "/opt/alfred-developer-v1/developer_v1/agent_profiles.json": "1194c14f4b3260dce2f2baef7e87c330c13135e2b1db28de82d9dd9d788ffd7e",
    "/etc/systemd/system/alfred-development-evidence.service.d/60-claude-agents.conf": "f9c5eed1f71499771c40a2ea452dfb420e38f827eb3200290c44fe51c7b7be0a",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/qa_recovery.py": "0dfb91ff0265d8ddb669a33edf34824213118c97bd6fd334a31a81ca1c88d1c6",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/recovery.py": "d6e3f3627f5f6c82223fe16dab7ef43d619cda4d98c4edf99467a76c0df688c4",
    "/etc/systemd/system/alfred-development-evidence.service.d/50-project-repos.conf": "cf1ef2e0280c419dee9e9c48bac4d92a754a74f72f3aa59ccdcdaa09e2b82db2",
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
BACKUP_SCHEMA = "alfred.development-handoff24-backup/1"


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
    return {"status": "ROLLED_BACK_HELD", "service_action": "none"}


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
        "service_action": "none",
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
