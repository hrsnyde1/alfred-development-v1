"""Root-pinned job inputs shared with the existing Intake and role adapters."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path

MAX_BYTES = 1024 * 1024


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def protected_json(path: Path, *, trusted_uid=0, trusted_root=Path("/")):
    """Descriptor-pinned, bounded input from a non-writable protected path."""
    if (
        not path.is_absolute()
        or not path.is_relative_to(trusted_root)
        or ".." in path.parts
        or path == trusted_root
    ):
        raise ValueError("input outside protected root")
    fd = os.open(trusted_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        components = path.relative_to(trusted_root).parts
        for i, component in enumerate(components):
            parent = os.fstat(fd)
            if parent.st_uid != trusted_uid or parent.st_mode & 0o022:
                raise ValueError("unprotected input directory")
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if i != len(components) - 1:
                flags |= os.O_DIRECTORY
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != trusted_uid
            or info.st_mode & 0o022
            or info.st_nlink != 1
            or info.st_size > MAX_BYTES
        ):
            raise ValueError("unprotected input file")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("input exceeds size bound")
        value = json.loads(raw, object_pairs_hook=unique)
        if type(value) is not dict:
            raise ValueError("JSON object required")
        return value, hashlib.sha256(raw).hexdigest()
    finally:
        if fd != -1:
            os.close(fd)


def identity(project, task):
    if (
        type(project) is not str
        or re.fullmatch(r"[a-z][a-z0-9-]{1,31}", project) is None
        or type(task) is not str
        or re.fullmatch(r"T-[0-9]{4}", task) is None
    ):
        raise ValueError("invalid canonical job identity")
    return project, task


def publication_plan_loader(root: Path, *, trusted_uid=0, trusted_root=Path("/")):
    def load(project, task):
        identity(project, task)
        path = root / project / task / "publication" / "approved-plan.json"
        plan, digest = protected_json(
            path, trusted_uid=trusted_uid, trusted_root=trusted_root
        )
        seal, _ = protected_json(
            path.with_name("seal.json"),
            trusted_uid=trusted_uid,
            trusted_root=trusted_root,
        )
        if (
            seal.get("publication_plan_sha256") != digest
            or plan.get("project") != project
            or plan.get("task_id") != task
        ):
            raise ValueError("prepared publication evidence mismatch")
        # The Publisher writes this exact canonical encoding; reject alternate bytes.
        raw = (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode()
        import hashlib

        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("noncanonical publication bytes")
        return raw

    return load
