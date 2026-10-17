"""Seven-file overlay using existing atomic file primitives; no service actions."""

import argparse
import json
import os
import pwd
import stat
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, "/usr/local/lib/alfred-fresh-v1")
from fresh_v1 import upgrade

DEVELOPER = "/opt/alfred-developer-v1/"
PHOTON = "/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/"
DESTINATIONS = {
    DEVELOPER + "developer_v1/owner_grants.py": "developer_v1/owner_grants.py",
    DEVELOPER
    + "developer_v1/trusted_intake_development.py": "developer_v1/trusted_intake_development.py",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "developer_v1/trusted_intake_development.py",
    DEVELOPER + "developer_v1/stage_approval.py": "developer_v1/stage_approval.py",
    DEVELOPER + "developer_v1/release.sha256": "developer_v1/release.sha256",
    "/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py": "fresh_v1/host.py",
    PHOTON
    + "development-observe.mjs": "development_challenge/sidecar/development-observe.mjs",
}
BASE = dict(
    zip(
        DESTINATIONS,
        (
            "d8e88bf8f42a0eb19e3f3d5a80d1985daf33ced47c318cd1826210799a40e463",
            "d3e1677cb8d7ee17ab801448e85db48fee12d88bbf21a3561e9e755eef742168",
            "d3e1677cb8d7ee17ab801448e85db48fee12d88bbf21a3561e9e755eef742168",
            "98990b9e8c9ed142d9bc6d330f8521b583758f7bc523facd12ab3f99097bcdf8",
            "c23cb89acc0ddc17fe382c4ea3e985c8404ebbf2dace1d20bbad19da81fa9edd",
            "9cb19786ec25b87de5012704fb739b7c8bce9bacdad38469c41b774909ce2b73",
            "bea7beb14530739c523b67780ce0d40537665b441e13bea56cb17ca5c29ed009",
        ),
        strict=True,
    )
)
DEPENDENCIES = {
    PHOTON
    + "index.mjs": "ef019d1d50e4ca680aede49276181f8eff8d396d9b7c22a73bb5da2b2d7bb8e4",
    **{
        "/usr/local/lib/alfred-fresh-v1/fresh_v1/" + name: sha
        for name, sha in {
            "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
            "handoffs.py": "09568b8de620b61c28dbf4c4a3be824c7e4eecd3800aaa47d6858a13ad066ebb",
            "role.py": "99d43e22ace57b1cf4f97972e2e3755a8a2269d66f53f9078220b859407cd109",
            "diagnostics.py": "c5862c14b39b22b7e6faef07aea1d4c32b5ab0df20aab987d4a0fed33b763e0e",
            "protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
            "recovery.py": "d6e3f3627f5f6c82223fe16dab7ef43d619cda4d98c4edf99467a76c0df688c4",
        }.items()
    },
}
# Unchanged dependencies whose established host owner is not the installer.
# Only the owner differs: each must still be a regular, single-link file without
# group/other write permission and with its exact pinned digest. No destination
# or other dependency may use this exception.
DEPENDENCY_OWNERS = {PHOTON + "index.mjs": "alfred"}
if not set(DEPENDENCY_OWNERS) <= set(DEPENDENCIES) or set(DEPENDENCY_OWNERS) & set(
    DESTINATIONS
):
    raise RuntimeError("dependency owner exception outside unchanged dependencies")


def paused(root):
    upgrade.validate_root(root)
    path = upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE")
    if not path.is_file():
        raise ValueError("operator PAUSE and idle workers required")


def dependency_uid(name):
    owner = DEPENDENCY_OWNERS.get(name)
    if owner is None:
        return os.geteuid()
    uid = pwd.getpwnam(owner).pw_uid
    if uid == 0:
        raise ValueError("dependency owner exception must name an unprivileged user")
    return uid


def checked(path, sha, uid=None):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != (os.geteuid() if uid is None else uid)
        or info.st_mode & 0o022
        or upgrade.digest(path.read_bytes()) != sha
    ):
        raise ValueError("installed contract mismatch: " + str(path))
    return info, path.read_bytes()


def inventory(raw):
    result = {}
    for line in raw.decode().splitlines():
        sha, name = line.split("  ", 1)
        if (
            not name.startswith("developer_v1/")
            or ".." in Path(name).parts
            or name in result
        ):
            raise ValueError("invalid Developer inventory")
        result[name] = sha
    return result


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
        index.get("schema") != "alfred.development-handoff-backup/1"
        or index.get("root") != str(root)
        or upgrade.marker(root) != index["activation_sha256"]
        or [e["path"] for e in index["files"]] != list(DESTINATIONS)
    ):
        raise ValueError("rollback inventory/root/activation mismatch")
    content = []
    for i, entry in enumerate(index["files"]):
        if (
            entry["backup"] != "file-" + str(i)
            or entry["sha256"] != BASE[entry["path"]]
        ):
            raise ValueError("rollback backup contract mismatch")
        path = backup / entry["backup"]
        _, raw = checked(path, entry["sha256"])
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
    content = {n: (release / n).read_bytes() for n in set(DESTINATIONS.values())}
    if any(upgrade.digest(raw) != verified[n] for n, raw in content.items()):
        raise ValueError("release changed after verification")
    previous = {n: checked(upgrade.target(root, n), sha) for n, sha in BASE.items()}
    for name, sha in DEPENDENCIES.items():
        checked(upgrade.target(root, name), sha, dependency_uid(name))
    old = inventory(previous[DEVELOPER + "developer_v1/release.sha256"][1])
    new = inventory(content["developer_v1/release.sha256"])
    expected = {
        **old,
        **{
            n: upgrade.digest(content[n])
            for n in (
                "developer_v1/owner_grants.py",
                "developer_v1/trusted_intake_development.py",
                "developer_v1/stage_approval.py",
            )
        },
    }
    if new != expected:
        raise ValueError("unexpected Developer inventory delta")
    for name, sha in old.items():
        checked(upgrade.target(root, DEVELOPER + name), sha)
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
                    "schema": "alfred.development-handoff-backup/1",
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
