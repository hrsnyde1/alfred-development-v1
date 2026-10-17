"""Run the inactive Photon front only in a marked, disposable staging root."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import stat
import threading

from .broker import AdmissionError, PhotonIngressPrototype
from .audit import AuditLog
from .durable import DurableEventJournal
from .photon_front import FrontError, HermesRestrictedServer, ProtectedSidecarClient, StagingPhotonFront
from .transport import LabInboxTransport, TransportError, isolated_root


LAB_INBOX_RELATIVE = Path("home/Alfred/projects/hermes-requests/inbox")


def _private_file(root: Path, path: Path) -> bytes:
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
        raise FrontError("secret path outside staging root")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
        raise FrontError("secret file ownership or mode invalid")
    return path.read_bytes()


def _bound_inbox(root: Path, requested: Path) -> Path:
    expected = root / LAB_INBOX_RELATIVE
    if requested.is_symlink() or requested.resolve(strict=True) != expected.resolve(strict=True):
        raise FrontError("only the static lab Hermes inbox is permitted")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--private-socket", type=Path, required=True)
    parser.add_argument("--hermes-socket-name", default="hermes.sock")
    parser.add_argument("--sidecar-uid", type=int, required=True)
    parser.add_argument("--hermes-uid", type=int, required=True)
    parser.add_argument("--allowed-sender", required=True)
    parser.add_argument("--private-token-file", type=Path, required=True)
    parser.add_argument("--ledger-key-file", type=Path, required=True)
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    root = isolated_root(args.root)
    private_socket = args.private_socket.resolve(strict=True)
    if not private_socket.is_relative_to(root) or not stat.S_ISSOCK(private_socket.stat().st_mode):
        raise FrontError("private socket outside staging root")
    token = _private_file(root, args.private_token_file).decode().strip()
    ledger_key = _private_file(root, args.ledger_key_file)
    transport = LabInboxTransport(root, _bound_inbox(root, args.inbox), args.ledger, secret=ledger_key)
    ingress = PhotonIngressPrototype(sidecar_uid=args.sidecar_uid, hermes_uid=args.hermes_uid,
                                    allowed_sender=args.allowed_sender, transport=transport)
    client = ProtectedSidecarClient(private_socket, sidecar_uid=args.sidecar_uid, token=token)
    journal_dir = root / "event-journal"
    audit_dir = root / "audit"
    for directory in (journal_dir, audit_dir):
        if not directory.exists() and not directory.is_symlink():
            directory.mkdir(mode=0o700)
        if directory.is_symlink() or stat.S_IMODE(directory.stat().st_mode) != 0o700:
            raise FrontError("unsafe staging event state")
    audit = AuditLog(audit_dir / "events.jsonl")
    journal = DurableEventJournal(journal_dir, ingress, key=ledger_key, audit=audit.emit)
    if journal.unresolved_count():
        audit.emit("recovery_pending")
    front = StagingPhotonFront(ingress, client, journal=journal, audit=audit.emit)
    stop = threading.Event()

    def request_stop(_signal, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    activated_fd = None
    if "LISTEN_FDS" in os.environ or "LISTEN_PID" in os.environ:
        if os.environ.get("LISTEN_FDS") != "1" or os.environ.get("LISTEN_PID") != str(os.getpid()):
            raise FrontError("unexpected socket activation metadata")
        activated_fd = 3
    server = HermesRestrictedServer(root, args.hermes_socket_name, front, activated_fd=activated_fd)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while not stop.is_set():
            try:
                front.read_private_feed()
            except (AdmissionError, FrontError, TransportError, OSError, ValueError):
                # Refuse the failed event/feed, then reconnect; never log raw
                # event text, handles, token or credentials.
                audit.emit("feed_failed")
                stop.wait(1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        audit.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
