"""Atomic, reversible opt-in for the already installed Intake extension.

Never copies or replaces the Intake program. The installed source hash is
pinned to the exact source reviewed with this release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import uuid
from pathlib import Path

from .router import Denied

EXPECTED_INTAKE_SHA256 = "01c8911332d2314ccbe8db187a4a6d3ba63ceb9d2475c2ad252af7c9a1855ef0"
FIELDS = ("development_grant_root", "gateway_root", "registry_path")


def _regular(path: Path, maximum: int, *, owner: int | None = None,
             mode: int | None = None) -> tuple[bytes, os.stat_result]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum
                or (owner is not None and info.st_uid != owner)
                or (mode is not None and stat.S_IMODE(info.st_mode) != mode)):
            raise Denied("untrusted installation artifact")
        return stream.read(), info


def _write_once(path: Path, raw: bytes, info: os.stat_result) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        if os.geteuid() == 0:
            os.fchown(stream.fileno(), info.st_uid, info.st_gid)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _replace(path: Path, raw: bytes, info: os.stat_result) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_once(temporary, raw, info)
        check, _ = _regular(temporary, 4096, owner=info.st_uid, mode=0o600)
        if check != raw:
            raise Denied("temporary config verification failed")
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _backup(path: Path, original: bytes, info: os.stat_result) -> Path:
    backup = path.with_name(path.name + ".pre-developer-v1")
    if not backup.exists() and not backup.is_symlink():
        _write_once(backup, original, info)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    saved, saved_info = _regular(backup, 4096, owner=info.st_uid, mode=0o600)
    if saved_info.st_gid != info.st_gid or saved != original:
        raise Denied("rollback backup does not match current Intake config")
    return backup


def _reviewed_source(source: Path) -> None:
    raw, _ = _regular(source, 65536)
    if hashlib.sha256(raw).hexdigest() != EXPECTED_INTAKE_SHA256:
        raise Denied("installed Intake source differs from reviewed release")


def install(config_path: Path, *, intake_source: Path, grant_root: Path,
            gateway_root: Path, registry: Path) -> dict:
    _reviewed_source(intake_source)
    for path in (grant_root, gateway_root, registry):
        if not path.is_absolute() or path.is_symlink() or not path.exists():
            raise Denied("installation path unavailable")
    config_raw, info = _regular(config_path, 4096, mode=0o600)
    grant_info = grant_root.lstat()
    if (not stat.S_ISDIR(grant_info.st_mode) or grant_info.st_uid != info.st_uid
            or stat.S_IMODE(grant_info.st_mode) != 0o700):
        raise Denied("grant store ownership or mode invalid")
    old = json.loads(config_raw)
    if type(old) is not dict:
        raise Denied("invalid protected Intake config")
    additions = {"development_grant_root": str(grant_root),
                 "gateway_root": str(gateway_root), "registry_path": str(registry)}
    if any(key in old for key in FIELDS):
        backup_path = config_path.with_name(config_path.name + ".pre-developer-v1")
        saved, saved_info = _regular(backup_path, 4096, owner=info.st_uid, mode=0o600)
        if saved_info.st_gid != info.st_gid:
            raise Denied("rollback backup group mismatch")
        before = json.loads(saved)
        if old != {**before, **additions} or any(key in before for key in FIELDS):
            raise Denied("existing development config differs from reviewed install")
        return {"state": "already_installed", "backup": str(backup_path)}
    _backup(config_path, config_raw, info)
    updated = {**old, **additions}
    new_raw = (json.dumps(updated, separators=(",", ":")) + "\n").encode()
    if len(new_raw) > 4096:
        raise Denied("protected Intake config exceeds size limit")
    _replace(config_path, new_raw, info)
    actual, _ = _regular(config_path, 4096, owner=info.st_uid, mode=0o600)
    if json.loads(actual) != updated:
        raise Denied("installed Intake config verification failed")
    return {"state": "installed", "backup": str(config_path) + ".pre-developer-v1"}


def rollback(config_path: Path) -> dict:
    current, info = _regular(config_path, 4096, mode=0o600)
    backup = config_path.with_name(config_path.name + ".pre-developer-v1")
    saved, saved_info = _regular(backup, 4096, owner=info.st_uid, mode=0o600)
    if saved_info.st_gid != info.st_gid:
        raise Denied("rollback backup ownership mismatch")
    old, new = json.loads(saved), json.loads(current)
    if type(old) is not dict or type(new) is not dict or any(key in old for key in FIELDS):
        raise Denied("rollback backup invalid")
    if any(key not in new for key in FIELDS) or {k: v for k, v in new.items() if k not in FIELDS} != old:
        raise Denied("Intake config changed outside Development V1 fields")
    _replace(config_path, saved, info)
    restored, _ = _regular(config_path, 4096, owner=info.st_uid, mode=0o600)
    if restored != saved:
        raise Denied("rollback verification failed")
    return {"state": "rolled_back", "backup": str(backup)}


def main() -> None:
    if os.geteuid() != 0:
        raise PermissionError("administrator required")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--intake-source", type=Path)
    parser.add_argument("--grant-root", type=Path)
    parser.add_argument("--gateway-root", type=Path)
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args()
    if args.rollback:
        result = rollback(args.config)
    else:
        if any(value is None for value in (args.intake_source, args.grant_root,
                                           args.gateway_root, args.registry)):
            parser.error("install requires source, grant root, Gateway root and registry")
        result = install(args.config, intake_source=args.intake_source,
                         grant_root=args.grant_root, gateway_root=args.gateway_root,
                         registry=args.registry)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
