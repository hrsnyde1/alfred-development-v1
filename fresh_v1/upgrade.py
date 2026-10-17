"""Reviewed file transaction; never controls services or invokes a V1 worker.

The executable release manifest is pinned by the operator. Only destinations
listed below may be changed. Backups include private Intake configuration and
must remain private. The Developer activation marker is NEVER moved or removed.
"""

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

LIBRARY = "/usr/local/lib/alfred-fresh-v1"
POLICY = "/etc/alfred-fresh-v1/policy.json"
INTAKE_CONFIG = "/home/alfred/Alfred/gateway/v1-1-intake.json"
MARKER = "/opt/alfred-developer-v1/active"
PRIVATE = {INTAKE_CONFIG}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def verify(release, manifest_sha):
    raw = (release / "MANIFEST.sha256").read_bytes()
    if digest(raw) != manifest_sha:
        raise ValueError("release manifest pin mismatch")
    files = {}
    for line in raw.decode().splitlines():
        sha, name = line.split("  ", 1)
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or name in files:
            raise ValueError("invalid inventory path")
        file = release / path
        info = file.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or digest(file.read_bytes()) != sha
        ):
            raise ValueError("release file digest mismatch: " + name)
        files[name] = sha
    actual = set()
    for file in release.rglob("*"):
        if file.is_symlink():
            raise ValueError("symlink in release")
        if file.is_file():
            actual.add(str(file.relative_to(release)))
    if actual != set(files) | {"MANIFEST.sha256"}:
        raise ValueError("release inventory mismatch")
    return files


def mapping(release, content=None):
    def read(path):
        return (
            path.read_bytes()
            if content is None
            else content[str(path.relative_to(release))]
        )

    files = {}
    # Only five existing Developer code files, its schema/manifest, and Intake.
    for name in (
        "pipeline.py",
        "owner_grants.py",
        "run_task.py",
        "publication_approval.py",
        "trusted_intake_development.py",
        "schemas/publication-plan.schema.json",
        "release.sha256",
    ):
        files["/opt/alfred-developer-v1/developer_v1/" + name] = read(
            release / "developer_v1" / name
        )
    files["/usr/local/lib/alfred-v1.1/trusted_intake.py"] = read(
        release / "developer_v1/trusted_intake_development.py"
    )
    for name in ("cto.py", "plan.schema.json"):
        files["/home/alfred/Git/alfred/.dev/bin/" + name] = read(
            release / "v1_cto" / name
        )
    for directory in ("fresh_v1", "v1_cto"):
        for file in (release / directory).glob("*"):
            if file.suffix in {".py", ".json"}:
                files[LIBRARY + "/" + directory + "/" + file.name] = read(file)
    files[POLICY] = read(release / "fresh_v1/config.example.json")
    for file in (release / "fresh_v1/systemd").glob("*.conf"):
        unit = file.name.removesuffix(".conf") + ".service.d/40-fresh-v1.conf"
        files["/etc/systemd/system/" + unit] = read(file)
    return files


def validate_root(root):
    if root == Path("/"):
        if os.geteuid() != 0:
            raise PermissionError("host transaction requires root")
    elif (
        not root.is_absolute()
        or root.resolve() != root
        or not root.is_relative_to(Path("/tmp"))
        or (root / ".fresh-v1-disposable-fixture").read_bytes()
        != b"DISPOSABLE_V1_FIXTURE\n"
    ):
        raise ValueError("non-host root must be an isolated disposable fixture")


def allowed_destination(name):
    fixed = set(PRIVATE)
    fixed |= {POLICY, "/usr/local/lib/alfred-v1.1/trusted_intake.py"}
    fixed |= {
        "/opt/alfred-developer-v1/developer_v1/" + n
        for n in (
            "pipeline.py",
            "owner_grants.py",
            "run_task.py",
            "publication_approval.py",
            "trusted_intake_development.py",
            "schemas/publication-plan.schema.json",
            "release.sha256",
        )
    }
    fixed |= {
        "/home/alfred/Git/alfred/.dev/bin/" + n for n in ("cto.py", "plan.schema.json")
    }
    fixed |= {
        "/etc/systemd/system/alfred-development-" + n + ".service.d/40-fresh-v1.conf"
        for n in ("intake", "gateway", "evidence")
    }
    path = Path(name)
    library = str(path.parent) in {
        LIBRARY + "/fresh_v1",
        LIBRARY + "/v1_cto",
    } and path.suffix in {".py", ".json"}
    return name in fixed or library


def target(root, absolute):
    path = root / absolute.lstrip("/")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("symlink in installation path")
    return path


def atomic(path, raw, uid, gid, mode):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    temporary = path.with_name(path.name + ".fresh-v1-tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), uid, gid)
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def marker(root):
    path = target(root, MARKER)
    info = path.lstat()
    expected_uid = 0 if root == Path("/") else os.geteuid()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != expected_uid
        or stat.S_IMODE(info.st_mode) != 0o644
    ):
        raise ValueError("Developer activation marker invalid")
    return digest(path.read_bytes())


def rollback(root, backup):
    validate_root(root)
    info = backup.lstat()
    if (
        info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise ValueError("unprotected backup")
    index = json.loads((backup / "index.json").read_bytes())
    if (
        index.get("schema") != "alfred.fresh-v1-backup/1"
        or index["root"] != str(root)
        or marker(root) != index["activation_sha256"]
        or any(not allowed_destination(e["path"]) for e in index["files"])
    ):
        raise ValueError("rollback root or activation marker mismatch")
    for entry in index["files"]:
        if entry["backup"] is not None and (
            Path(entry["backup"]).name != entry["backup"]
            or digest((backup / entry["backup"]).read_bytes()) != entry["sha256"]
        ):
            raise ValueError("backup digest mismatch")
    for entry in reversed(index["files"]):
        path = target(root, entry["path"])
        # No grants, results, plans, credentials or delivery state occur in this list.
        if entry["backup"] is None:
            path.unlink(missing_ok=True)
        else:
            raw = (backup / entry["backup"]).read_bytes()
            if digest(raw) != entry["sha256"]:
                raise ValueError("backup digest mismatch")
            atomic(path, raw, entry["uid"], entry["gid"], entry["mode"])
    if marker(root) != index["activation_sha256"]:
        raise ValueError("activation marker changed")
    return {
        "status": "ROLLED_BACK",
        "service_action": "daemon-reload and restart Intake only, after operator authorization",
    }


def install(release, pin, root, backup, *, fail_after=None):
    validate_root(root)
    inventory = verify(release, pin)
    content = {name: (release / name).read_bytes() for name in inventory}
    if any(digest(content[name]) != sha for name, sha in inventory.items()):
        raise ValueError("release changed during verification")
    before = marker(root)
    contract = json.loads(content["host-contract.json"])
    for name, sha in contract["installed_sha256"].items():
        if digest(target(root, name).read_bytes()) != sha:
            raise ValueError("installed contract mismatch: " + name)
    if not target(root, "/home/alfred/Alfred/gateway/PAUSE").is_file():
        raise ValueError("operator PAUSE required; wait for existing workers to finish")
    # Verify every previously installed Developer file through its pinned manifest.
    for line in (
        target(root, "/opt/alfred-developer-v1/developer_v1/release.sha256")
        .read_text()
        .splitlines()
    ):
        sha, name = line.split("  ", 1)
        if not name.startswith("developer_v1/") or ".." in Path(name).parts:
            raise ValueError("invalid installed Developer inventory")
        if digest(target(root, "/opt/alfred-developer-v1/" + name).read_bytes()) != sha:
            raise ValueError("installed Developer file differs from manifest")
    files = mapping(release, content)
    if any(not allowed_destination(name) for name in files):
        raise ValueError("unexpected install destination")
    config_path = target(root, INTAKE_CONFIG)
    cfg = json.loads(config_path.read_bytes())
    cfg["fresh_handoff_root"] = "/var/lib/alfred-v1-handoffs"
    files[INTAKE_CONFIG] = (json.dumps(cfg, indent=2, sort_keys=True) + "\n").encode()
    # Root policy is disabled on every install; activation is a separate action.
    if json.loads(files[POLICY])["enabled"] is not False:
        raise ValueError("policy must be disabled")
    backup.mkdir(mode=0o700, parents=False, exist_ok=False)
    entries = []
    for i, name in enumerate(sorted(files)):
        path = target(root, name)
        if path.exists():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("unsafe installed file")
            raw = path.read_bytes()
            item = "file-" + str(i)
            atomic(backup / item, raw, os.geteuid(), os.getegid(), 0o600)
            entries.append(
                {
                    "path": name,
                    "backup": item,
                    "sha256": digest(raw),
                    "uid": info.st_uid,
                    "gid": info.st_gid,
                    "mode": stat.S_IMODE(info.st_mode),
                }
            )
        else:
            entries.append({"path": name, "backup": None})
    index = {
        "schema": "alfred.fresh-v1-backup/1",
        "root": str(root),
        "activation_sha256": before,
        "files": entries,
    }
    atomic(
        backup / "index.json",
        (json.dumps(index, indent=2) + "\n").encode(),
        os.geteuid(),
        os.getegid(),
        0o600,
    )
    try:
        for i, entry in enumerate(entries):
            path = target(root, entry["path"])
            uid, gid = entry.get("uid", os.geteuid()), entry.get("gid", os.getegid())
            mode = entry.get("mode", 0o644)
            if entry["path"] in PRIVATE:
                mode = 0o600
            atomic(path, files[entry["path"]], uid, gid, mode)
            if fail_after == i:
                raise OSError("disposable partial-failure injection")
        if marker(root) != before:
            raise ValueError("activation marker changed")
    except BaseException:
        rollback(root, backup)
        raise
    return {
        "status": "INSTALLED_DISABLED",
        "activation_marker": "preserved",
        "backup": str(backup),
        "service_action": "daemon-reload and restart Intake only, after operator authorization",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("verify", "install", "rollback"))
    parser.add_argument("--release", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args()
    if args.operation == "verify":
        print(
            json.dumps(
                {
                    "status": "VERIFIED",
                    "files": len(verify(args.release, args.manifest_sha256)),
                }
            )
        )
        return
    if os.geteuid() != 0 and args.root == Path("/"):
        raise PermissionError("root required for host transaction")
    if args.operation == "install":
        result = install(args.release, args.manifest_sha256, args.root, args.backup)
    else:
        result = rollback(args.root, args.backup)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
