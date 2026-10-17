"""No-import edit applier, executed only inside the restricted bwrap mount tree."""

from __future__ import annotations

import json
import os
import re
import sys

MAX_PACKET = 131072
NAME = re.compile(r"[^/\x00]+\Z")


def _parts(value: str) -> list[str]:
    if not isinstance(value, str) or value.startswith("/") or "\\" in value:
        raise ValueError("invalid relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or not NAME.fullmatch(part) for part in parts):
        raise ValueError("invalid relative path")
    return parts


def apply(payload: dict) -> None:
    if type(payload) is not dict or set(payload) != {"allowed", "edits"}:
        raise ValueError("invalid edit packet")
    allowed, edits = payload["allowed"], payload["edits"]
    if type(allowed) is not list or type(edits) is not list or not edits:
        raise ValueError("invalid edit list")
    if len(set(allowed)) != len(allowed) or len(edits) > len(allowed):
        raise ValueError("invalid file ownership")
    seen = set()
    for edit in edits:
        if (type(edit) is not dict or set(edit) != {"path", "content"}
                or edit["path"] not in allowed or edit["path"] in seen
                or type(edit["content"]) is not str or len(edit["content"].encode()) > 65536):
            raise ValueError("edit exceeds scope")
        seen.add(edit["path"])
        parts = _parts(edit["path"])
        directory = os.open("/workspace", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, 0o755, dir_fd=directory)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
                os.close(directory)
                directory = child
            name = parts[-1]
            try:
                existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                os.close(existing)
            temporary = f".alfred-edit-{os.getpid()}-{len(seen)}"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o644, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                stream.write(edit["content"].encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            os.close(directory)


if __name__ == "__main__":
    packet = sys.stdin.buffer.read(MAX_PACKET + 1)
    if len(packet) > MAX_PACKET:
        raise ValueError("edit packet too large")
    apply(json.loads(packet))
