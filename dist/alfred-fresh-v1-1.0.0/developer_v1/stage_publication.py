"""Root-only client for the existing Intake's exact-plan publication approval."""

from __future__ import annotations

import argparse
import grp
import json
import os
import socket
import stat
from pathlib import Path

from .publication_approval import BOUND, PLAN_SHA, _validate_plan

PLAN_PATH = Path("/var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-plan.json")
AUTH_PATH = Path("/var/lib/alfred-draft-pr-authorizations/T-0002.json")
SOCKET_PATH = Path("/run/alfred-development-intake/intake.sock")


def _exchange(socket_path: Path, request: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(socket_path))
        client.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        response = bytearray()
        while b"\n" not in response and len(response) <= 4096:
            chunk = client.recv(1024)
            if not chunk:
                break
            response.extend(chunk)
    if b"\n" not in response or len(response) > 4096:
        raise RuntimeError("trusted Intake did not return a bounded result")
    result = json.loads(response.split(b"\n", 1)[0])
    if result.get("ok") is not True:
        raise RuntimeError("trusted Intake refused publication approval operation")
    return result


def _read_plan(path: Path) -> bytes:
    if path != PLAN_PATH:
        raise ValueError("unexpected publication plan path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o022 or info.st_size > 16384:
            raise ValueError("publication plan is not a protected regular file")
        raw = stream.read()
    _validate_plan(raw)
    return raw


def _install_authorization(record: dict) -> None:
    expected = {"schema": "alfred.github-draft-pr-authorization/1",
                "decision": "approved", **BOUND, "publication_plan_sha256": PLAN_SHA,
                "purpose": "one_github_draft_pr"}
    if (type(record) is not dict or set(record) != set(expected) | {"owner_event_id"}
            or any(record.get(key) != value for key, value in expected.items())
            or type(record.get("owner_event_id")) is not str
            or not record["owner_event_id"]):
        raise ValueError("Intake returned malformed authorization")
    parent = AUTH_PATH.parent
    gid = grp.getgrnam("alfredpublish").gr_gid
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != 0o750):
        raise ValueError("publication authorization directory is not root protected")
    raw = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    fd = os.open(AUTH_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        os.fchown(stream.fileno(), 0, gid)
        os.fchmod(stream.fileno(), 0o640)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> None:
    if os.geteuid() != 0:
        raise PermissionError("only the host administrator may stage or prepare publication approval")
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--stage", action="store_true")
    action.add_argument("--prepare", action="store_true")
    parser.add_argument("--space-id")
    parser.add_argument("--reference")
    args = parser.parse_args()
    if args.socket != SOCKET_PATH:
        parser.error("publication approval requires the reviewed Intake socket")
    if args.stage:
        if not args.space_id or args.reference:
            parser.error("stage requires only --space-id")
        raw = _read_plan(PLAN_PATH)
        result = _exchange(args.socket, {"op": "stage_publication_approval",
                      "plan_raw": raw.decode("utf-8"), "space_id": args.space_id})
        print(json.dumps({key: result[key] for key in ("state", "challenge", "message_id")}))
    else:
        if not args.reference or args.space_id:
            parser.error("prepare requires only --reference")
        result = _exchange(args.socket, {"op": "prepare_publication_authorization",
                                        "reference": args.reference})
        _install_authorization(result["authorization"])
        print(json.dumps({"state": "authorization_installed", "path": str(AUTH_PATH),
                          "owner_event_id": result["authorization"]["owner_event_id"]}))


if __name__ == "__main__":
    main()
