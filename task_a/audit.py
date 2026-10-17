"""Privacy-safe operational audit events for the protected Photon process."""

from __future__ import annotations

import json
import errno
import os
from pathlib import Path
import stat
import threading
import time


ALLOWED_CODES = frozenset({
    "event_accepted", "event_held", "event_rejected", "event_unavailable", "event_retried",
    "feed_failed", "reply_sent", "reply_delivery_failed", "restricted_unavailable",
    "restricted_capacity_denied", "restricted_peer_denied", "restricted_consumer_denied",
    "restricted_request_denied", "forged_handle_denied", "sidecar_started", "sidecar_stopped", "sidecar_failed",
    "sidecar_restarted", "read_receipt_failed", "delivery_delayed", "reconciliation_required",
    "recovery_pending", "event_expired_unresolved", "inbox_retry_failed", "inbox_recovered",
})
MAX_AUDIT_BYTES = 4 * 1024 * 1024


class AuditLog:
    def __init__(self, path: Path):
        parent = path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            raise ValueError("unsafe audit directory")
        self._fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(self._fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            os.close(self._fd)
            raise ValueError("unsafe audit file")
        self._lock = threading.Lock()

    def emit(self, code: str) -> None:
        if code not in ALLOWED_CODES:
            raise ValueError("invalid audit code")
        with self._lock:
            # Record every handled denial. Exhausting the fixed audit budget
            # fails closed instead of silently dropping security events.
            line = (json.dumps({"time_ns": time.time_ns(), "code": code}, separators=(",", ":")) + "\n").encode()
            if os.fstat(self._fd).st_size + len(line) > MAX_AUDIT_BYTES:
                raise OSError(errno.ENOSPC, "protected audit capacity reached")
            if os.write(self._fd, line) != len(line):
                raise OSError(errno.EIO, "short protected audit write")
            os.fsync(self._fd)

    def close(self) -> None:
        os.close(self._fd)
