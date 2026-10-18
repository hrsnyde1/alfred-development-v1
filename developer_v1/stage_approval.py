"""Administrator-only client for an exact native-reply approval challenge."""

from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path


def main() -> None:
    if os.geteuid() != 0:
        raise PermissionError("only the host administrator may stage development approval")
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--revoke", action="store_true")
    parser.add_argument("--project", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--worktree-root", type=Path)
    parser.add_argument("--scope", action="append")
    parser.add_argument("--space-id")
    # Default: /etc/alfred-development/approval-channel.json (absent: iMessage).
    parser.add_argument("--channel", choices=("alfred_os", "imessage"))
    args = parser.parse_args()
    if args.revoke:
        if args.worktree_root or args.scope or args.space_id or args.channel:
            parser.error("revocation takes only project and task")
        request = {"op": "revoke_development_grant", "project": args.project,
                   "task_id": args.task}
    else:
        if not args.worktree_root or not args.scope or not args.space_id:
            parser.error("challenge requires worktree root, scope, and space ID")
        request = {"op": "stage_development_approval", "project": args.project,
                   "task_id": args.task, "worktree_root": str(args.worktree_root),
                   "scope": args.scope, "space_id": args.space_id,
                   **({"channel": args.channel} if args.channel else {})}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        # Longer than Intake's bounded 30s development send; no client retries.
        client.settimeout(40)
        client.connect(str(args.socket))
        client.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        response = bytearray()
        while b"\n" not in response and len(response) <= 4096:
            chunk = client.recv(1024)
            if not chunk:
                break
            response.extend(chunk)
    if b"\n" not in response or len(response) > 4096:
        raise RuntimeError("trusted intake did not return a bounded result")
    result = json.loads(response.split(b"\n", 1)[0])
    if result.get("ok") is not True:
        raise RuntimeError("development approval challenge was refused")
    if args.revoke:
        print(json.dumps({"state": result["state"], "project": args.project,
                          "task_id": args.task}))
    else:
        print(json.dumps({"state": result["state"], "challenge": result["challenge"],
                          "message_id": result.get("message_id")}))


if __name__ == "__main__":
    main()
