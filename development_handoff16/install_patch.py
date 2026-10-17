"""handoff.16 overlay (team skills, rebuilt from handoff.13): the Central CTO's specialists use the owner-approved team skills.

- developer_v1/team_skills.py (new): loads a root-owned snapshot of the merged
  alfred-team-skills library at one pinned commit, re-checks its manifest and the
  library's format, safety and budget rules, and selects the skills a plan uses.
- fresh_v1/role.py: the CTO plan records the selected skills (commit, ids, SHA-256).
  The development grant binds the plan digest, so approval fixes the skill text.
- developer_v1/pipeline.py: reloads exactly the plan's skills before the grant is
  claimed; any difference refuses the run and leaves the grant unused.
- developer_v1/real_worker.py: adds them to the model payload as team_practices,
  which never widen files, scope or tools.
- both copies of v1_cto/plan.schema.json: accept the optional team_skills record.
Nothing changes until the owner creates /usr/local/lib/alfred-team-skills/cto/ACTIVE
with the library's deploy tool. No service needs a restart: each stage is a new process.
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

LIBRARY = "/usr/local/lib/alfred-fresh-v1/"
DEVELOPER = "/opt/alfred-developer-v1/developer_v1/"
GATEWAY_BIN = "/home/alfred/Git/alfred/.dev/bin/"
DROP_IN = "/etc/systemd/system/alfred-development-evidence.service.d/40-fresh-v1.conf"
OPS = "/usr/local/sbin/alfred-dev-ops"
# Schemas first, so no plan with team_skills exists before every reader accepts it.
DESTINATIONS = {
    LIBRARY + "v1_cto/plan.schema.json": "v1_cto/plan.schema.json",
    GATEWAY_BIN + "plan.schema.json": "v1_cto/plan.schema.json",
    DEVELOPER + "team_skills.py": "developer_v1/team_skills.py",
    DEVELOPER + "real_worker.py": "developer_v1/real_worker.py",
    DEVELOPER + "pipeline.py": "developer_v1/pipeline.py",
    LIBRARY + "fresh_v1/role.py": "fresh_v1/role.py",
}
# Exactly the bytes on the host after handoff.12 (source commit 8e634d6). None: new file.
BASE = {
    LIBRARY + "v1_cto/plan.schema.json": "18209b70573b8f068e77fe49f8fc25034bb849d1cc30cb05ce1cb6a38b1367b8",
    GATEWAY_BIN + "plan.schema.json": "18209b70573b8f068e77fe49f8fc25034bb849d1cc30cb05ce1cb6a38b1367b8",
    DEVELOPER + "team_skills.py": None,
    DEVELOPER + "real_worker.py": "bc5fc4134cdc0b407bc47727ddddd0a900dfcd82a39a06422be03c18862781ee",
    DEVELOPER + "pipeline.py": "e22bc7b0c334b243db38b22b87766862cad5b5a10a7aec6c26f60d8c0a97c91a",
    LIBRARY + "fresh_v1/role.py": "9126c93694cfd51dce41cfdcb8abc6477c19ecc35e055e9c470759ed2e0481ec",
}
# The Gateway's own copy stays owned by the Gateway operator; everything else by root.
# handoff.13 required root to own the Gateway's cto.py too, which the Gateway
# operator owns like the rest of its checkout, so it could never install.
GATEWAY_OWNED = {GATEWAY_BIN + "plan.schema.json", GATEWAY_BIN + "cto.py"}
NEW_MODE = 0o644
# Code the changed files import or are driven by; each must still match.
DEPENDENCIES = {
    DEVELOPER + "router.py": "69c70a8326bc20b129a80d6413ffe0581807c28d73b14f4c11a94d36370f4649",
    DEVELOPER + "execution.py": "01a8aaba3ebad98cc47f3905ac146460ca0f79504ae9166cfac71ec4ef6f810c",
    DEVELOPER + "gateway_adapter.py": "64b1cb2a78614ca09e1e9166d5fae3c26bdec8d2bae0e733af0b0309f2274a8e",
    DEVELOPER + "owner_grants.py": "f54d0f51bac5af08c85968da3d81b7ff419f0654d1326886dcc8140653b02fb9",
    DEVELOPER + "run_task.py": "dd93a1a89975b8a36bc0ce9108cee81dfb18afb131cae05e4dcdc1e95cb69266",
    LIBRARY + "v1_cto/cto.py": "d60da3f6c230ef741c97f9689cd6fe85825b376c6e7029935165adb79b684ec1",
    GATEWAY_BIN + "cto.py": "d60da3f6c230ef741c97f9689cd6fe85825b376c6e7029935165adb79b684ec1",
    LIBRARY + "fresh_v1/host.py": "8f080553b94e462ffb251159164c6be41d808dde5ff2230c5070909a52c3ddd3",  # the handoff.14 host
    LIBRARY + "fresh_v1/handoffs.py": "1d612babbbfccd422b5ba7198ae01e5943f84f2f0cd6b4400c5425ec18caecbe",
    LIBRARY + "fresh_v1/upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
    LIBRARY + "fresh_v1/protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
    LIBRARY + "fresh_v1/diagnostics.py": "c5862c14b39b22b7e6faef07aea1d4c32b5ab0df20aab987d4a0fed33b763e0e",
    DROP_IN: "436dde472b64e6f2e64a1a44fe573e59157aeea0e4000c30f3212ba15f7ef484",
    OPS: "0966e652667410920323a5f6b8d47a8ed2c574da4a4006166d3191641babd2ff",
}
BACKUP_SCHEMA = "alfred.development-handoff16-backup/1"


def paused(root):
    upgrade.validate_root(root)
    path = upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE")
    if not path.is_file():
        raise ValueError("operator PAUSE and idle workers required")


def owner(root, name):
    """Root, or the Gateway operator (owner of the Gateway checkout) for its schema copy."""
    if name in GATEWAY_OWNED:
        return upgrade.target(root, GATEWAY_BIN).lstat().st_uid
    return os.geteuid()


def checked(root, name, sha):
    path = upgrade.target(root, name)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != owner(root, name)
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
        "team_skills": "inactive until /usr/local/lib/alfred-team-skills/cto/ACTIVE exists",
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
