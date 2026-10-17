"""One-time operator binding of the original Photon DM to the existing sidecar send path."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
from pathlib import Path

from alfred.gateway.envelope import parse_envelope
from alfred.gateway.journal import Journal

try:
    from .cto import CTOError, _regular_bytes
except ImportError:  # installed beside cto.py in the Gateway bin directory
    from cto import CTOError, _regular_bytes

REQUEST = "a7881a72-b1d8-5179-973b-6e84efa4e62b"
# Read-only captured from the already filed T-0001 request in staging. This
# pins the original DM independently of the later processed request file.
ORIGINAL_DM_DIGEST = "83c0898ee538d76629260ffc9fe0d9a1"
GATEWAY = Path.home() / "Alfred/gateway"
PROCESSED = Path.home() / "Alfred/projects/hermes-requests/processed"


def bind(space_id: str, gateway: Path = GATEWAY, processed: Path = PROCESSED) -> Path:
    if not 1 <= len(space_id) <= 200 or any(ord(c) < 32 for c in space_id):
        raise CTOError("invalid Photon space ID")
    rows = [
        r
        for r in Journal(gateway / "journal.jsonl").entries()
        if r.get("kind") == "outcome"
        and r.get("outcome") == "filed"
        and r.get("request_id") == REQUEST
    ]
    if (
        len(rows) != 1
        or rows[0].get("project") != "dev-001"
        or rows[0].get("task_id") != "T-0001"
    ):
        raise CTOError("T-0001 filed binding is missing or conflicting")
    name = rows[0].get("file")
    if name != f"{REQUEST}.json":
        raise CTOError("unexpected processed request name")
    envelope = parse_envelope(json.loads(_regular_bytes(processed / name, 64 * 1024)))
    digest = hashlib.sha256(space_id.encode()).hexdigest()[:32]
    if (
        envelope.request_id != REQUEST
        or envelope.origin.interface != "photon"
        or envelope.origin.conversation_ref != digest
        or digest != ORIGINAL_DM_DIGEST
    ):
        raise CTOError("space ID does not match the originally filed Photon DM")
    intake = json.loads(_regular_bytes(gateway / "v1-1-intake.json", 32 * 1024))
    port, token = intake.get("sidecar_port"), intake.get("sidecar_token")
    if (
        not isinstance(port, int)
        or not 1 <= port <= 65535
        or not isinstance(token, str)
        or not token
    ):
        raise CTOError("existing intake send configuration is incomplete")
    target = gateway / "v1-cto-delivery.json"
    data = (
        json.dumps(
            {"owner_space_id": space_id, "sidecar_port": port, "sidecar_token": token},
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return target


if __name__ == "__main__":
    destination = getpass.getpass("Original SDK Photon DM space.id (hidden): ")
    try:
        bind(destination)
    except (CTOError, OSError, ValueError) as exc:
        raise SystemExit(f"delivery binding refused: {exc}") from None
    print("Original owner DM bound for CTO delivery; destination and token suppressed.")
