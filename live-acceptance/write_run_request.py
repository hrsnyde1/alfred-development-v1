"""Create the one protected acceptance request after a real owner grant exists."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import pwd
import re
import stat
from pathlib import Path

from developer_v1.approval_transition import approval_request
from developer_v1.gateway_adapter import read_gateway_inputs
from developer_v1.owner_grants import ProtectedDevelopmentAuthority

ROOT = Path(__file__).resolve().parent
GATEWAY = Path("/home/alfred/Git/alfred")
STATE = Path("/var/lib/alfred-development-state")
GRANTS = Path("/var/lib/alfred-development-grants")
WORKTREES = Path("/var/lib/alfred-development-worktrees")
PROJECT = "dev-v1-accept"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    if os.geteuid() != pwd.getpwnam("alfred").pw_uid:
        raise PermissionError("run-request writer must run as alfred")
    if not re.fullmatch(r"T-[0-9]{4}", args.task):
        raise ValueError("invalid task ID")
    info = STATE.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise PermissionError("protected state root invalid")
    template = json.loads((ROOT / "run-request.template.json").read_text())
    template["task_id"] = args.task
    if template["project"] != PROJECT or template["worktree_root"] != str(WORKTREES):
        raise ValueError("acceptance request binding changed")
    inputs = read_gateway_inputs(gateway_root=GATEWAY,
        gateway_state=Path("/home/alfred/Alfred/gateway"),
        registry_path=GATEWAY / "registry" / "projects.yaml",
        project_id=PROJECT, task_id=args.task)
    review = approval_request(inputs.spec_raw, inputs.plan_raw,
        project=PROJECT, task_id=args.task, repository=inputs.repository,
        worktree_root=WORKTREES, scope=template["scope"],
        spec_decoder=inputs.spec_decoder)
    if review["specialists"] != ["backend"]:
        raise ValueError("CTO router did not select only Backend Developer")
    reference = getpass.getpass("Trusted owner grant reference (hidden): ")
    if not re.fullmatch(r"[0-9a-f]{32}", reference):
        raise ValueError("invalid grant reference")
    expected = {"schema": "alfred.development-grant/1",
                **{k: v for k, v in review.items() if k not in {"schema", "state"}}}
    ProtectedDevelopmentAuthority(GRANTS).verify(reference, expected)
    template["authorization_reference"] = reference
    target = STATE / f"request-{PROJECT}-{args.task}.json"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(template, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"state": "request_written", "path": str(target)}))


if __name__ == "__main__":
    main()
