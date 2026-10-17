"""Manual host entry point for one already approved Gateway task.

This module creates no listener, timer, approval request or Photon message.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from .pipeline import execute_gateway_task
from .router import Denied


def _protected_json(path: Path, maximum: int) -> dict:
    parent = path.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) != 0o700):
        raise Denied("run request directory is not private to the authorized runner")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > maximum):
            raise Denied("untrusted host request or model configuration")
        obj = json.load(stream)
    if type(obj) is not dict:
        raise Denied("host request must be JSON object")
    return obj


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--gateway-root", type=Path, required=True)
    parser.add_argument("--gateway-state", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--grant-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args(argv)
    # Fix rounds carry findings and the previous attempt's files (bounded by the host).
    request = _protected_json(args.request, 65536)
    required = {"schema", "project", "task_id", "worktree_root", "scope",
                "authorization_reference", "items", "total_cost_limit"}
    if not required <= set(request) or set(request) - required - {"model_overrides", "baseline_revision", "fix_round"}:
        raise Denied("host run request fields invalid")
    if request["schema"] != "alfred.developer-run-request/1":
        raise Denied("host run request schema invalid")
    models = _protected_json(args.models, 32768)
    reports, qa = execute_gateway_task(
        gateway_root=args.gateway_root, gateway_state=args.gateway_state,
        registry_path=args.registry, project=request["project"], task_id=request["task_id"],
        worktree_root=Path(request["worktree_root"]), scope=request["scope"],
        grant_reference=request["authorization_reference"], grant_root=args.grant_root,
        items=request["items"], models=models, state_root=args.state_root,
        total_cost_limit=request["total_cost_limit"],
        overrides=request.get("model_overrides"), baseline_revision=request.get("baseline_revision"),
        fix_round=request.get("fix_round", 0))
    fix_round = request.get("fix_round", 0)
    output = (args.state_root / request["project"] / request["task_id"]
              / ("qa-input.json" if fix_round == 0 else f"qa-input-r{fix_round}.json"))
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(qa, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"state": "ready_for_independent_qa", "report_count": len(reports),
                      "qa_input": str(output)}))


if __name__ == "__main__":
    main()
