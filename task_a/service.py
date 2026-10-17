"""Protected Photon service entry point for a future, separately approved host.

The service has fixed production paths and requires systemd socket activation
and LoadCredential files. This module is packaged for review, not invoked by
the staging release. No account or service provisioning occurs here.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import stat
import subprocess
import threading
import time

from .audit import AuditLog
from .broker import PhotonIngressPrototype
from .durable import DurableEventJournal
from .photon_front import FrontError, HermesRestrictedServer, ProtectedSidecarClient, StagingPhotonFront
from .transport import LabInboxTransport


STATE = Path("/var/lib/alfred-photon-intake")
RUNTIME = Path("/run/alfred-photon-intake")
PRIVATE_SOCKET = RUNTIME / "private.sock"
SIDECAR = Path("/opt/alfred-photon-intake/photon/sidecar/index.mjs")
NODE = Path("/opt/alfred-photon-intake/node/bin/node")


def _private_directory(path: Path, *, mode: int = 0o700) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode:
        raise FrontError("unsafe protected service directory")


def _credential(directory: Path, name: str, *, binary: bool = False) -> bytes | str:
    if not name.isidentifier() or not directory.is_absolute():
        raise FrontError("invalid credential path")
    path = directory / name
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid not in (0, os.getuid())
                or info.st_mode & 0o077 or info.st_size > 8192):
            raise FrontError("unsafe protected credential")
        value = os.read(fd, 8193)
    finally:
        os.close(fd)
    if not value or len(value) > 8192:
        raise FrontError("invalid protected credential")
    return value if binary else value.decode("utf-8").strip()


class ProtectedSidecarSupervisor:
    """Owns exactly one Node process; cleans stale own-UID socket on restart."""

    def __init__(self, node: Path, sidecar: Path, socket_path: Path, spool: Path,
                 *, project_id: str, project_secret: str, token: str, audit):
        self.node, self.sidecar, self.socket_path, self.spool = node, sidecar, socket_path, spool
        self.project_id, self.project_secret, self.token = project_id, project_secret, token
        self.audit = audit
        self.process: subprocess.Popen | None = None

    def _remove_stale_socket(self) -> None:
        try:
            info = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise FrontError("unsafe stale private socket")
        self.socket_path.unlink()

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            raise FrontError("protected sidecar already running")
        if not self.node.is_file() or not self.sidecar.is_file():
            raise FrontError("pinned protected sidecar payload missing")
        self._remove_stale_socket()
        env = {
            "HOME": str(STATE), "PATH": str(self.node.parent) + ":/usr/bin:/bin",
            "PHOTON_PROJECT_ID": self.project_id, "PHOTON_PROJECT_SECRET": self.project_secret,
            "PHOTON_SIDECAR_TOKEN": self.token, "PHOTON_PRIVATE_SOCKET": str(self.socket_path),
            "PHOTON_EVENT_SPOOL": str(self.spool), "PHOTON_READ_RECEIPTS": "true",
        }
        self.process = subprocess.Popen([str(self.node), str(self.sidecar)], cwd=self.sidecar.parent,
                                        env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        start_new_session=True)
        self.audit("sidecar_started")

    def wait_ready(self, client: ProtectedSidecarClient, *, seconds: float = 30) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.process is None or self.process.poll() is not None:
                raise FrontError("protected sidecar exited during startup")
            try:
                if self.socket_path.is_socket():
                    client.health()
                    return
            except (OSError, FrontError, ValueError):
                pass
            time.sleep(0.2)
        raise FrontError("protected sidecar startup deadline exceeded")

    def stop(self) -> None:
        proc = self.process
        self.process = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        self.audit("sidecar_stopped")


def main() -> int:
    # Socket activation and static paths are mandatory. A shell command or
    # model cannot choose the inbox, identities, sidecar path or SDK endpoint.
    if os.environ.get("LISTEN_FDS") != "1" or os.environ.get("LISTEN_PID") != str(os.getpid()):
        raise FrontError("one systemd activated restricted socket required")
    credentials = Path(os.environ.get("CREDENTIALS_DIRECTORY", ""))
    if not credentials.is_absolute() or not str(credentials).startswith("/run/credentials/"):
        raise FrontError("systemd credential directory required")
    _private_directory(STATE)
    _private_directory(RUNTIME, mode=0o751)
    for child in ("spool", "journal", "ledger", "audit"):
        directory = STATE / child
        if not directory.exists() and not directory.is_symlink():
            directory.mkdir(mode=0o700)
        _private_directory(directory)
    token = _credential(credentials, "sidecar_token")
    project_id = _credential(credentials, "project_id")
    project_secret = _credential(credentials, "project_secret")
    allowed_sender = _credential(credentials, "allowed_sender")
    ledger_key = _credential(credentials, "ledger_key", binary=True)
    if not all(isinstance(x, str) and x for x in (token, project_id, project_secret, allowed_sender)):
        raise FrontError("missing protected Photon credential")
    audit = AuditLog(STATE / "audit/events.jsonl")
    stop = threading.Event()

    def stop_signal(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    transport = LabInboxTransport.protected_runtime(secret=ledger_key, audit=audit.emit)
    ingress = PhotonIngressPrototype(sidecar_uid=os.getuid(), hermes_uid=31012,
                                     allowed_sender=allowed_sender, transport=transport)
    journal = DurableEventJournal(STATE / "journal", ingress, key=ledger_key, audit=audit.emit)
    if journal.unresolved_count():
        audit.emit("recovery_pending")
    client = ProtectedSidecarClient(PRIVATE_SOCKET, sidecar_uid=os.getuid(), token=token)
    front = StagingPhotonFront(ingress, client, journal=journal, audit=audit.emit)
    server = HermesRestrictedServer(RUNTIME, "hermes.sock", front, activated_fd=3, _protected=True)
    supervisor = ProtectedSidecarSupervisor(NODE, SIDECAR, PRIVATE_SOCKET, STATE / "spool",
                                           project_id=project_id, project_secret=project_secret,
                                           token=token, audit=audit.emit)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)

    def feed_loop() -> None:
        while not stop.is_set():
            try:
                front.read_private_feed()
            except (OSError, FrontError, ValueError):
                audit.emit("feed_failed")
                stop.wait(1)

    feed_thread = threading.Thread(target=feed_loop, daemon=True)
    try:
        server_thread.start()
        feed_thread.start()
        failures = 0
        while not stop.is_set():
            try:
                supervisor.start()
                supervisor.wait_ready(client)
                failures = 0
                while not stop.wait(5):
                    if not feed_thread.is_alive() or not server_thread.is_alive():
                        raise RuntimeError("protected intake worker exited")
                    if supervisor.process is None or supervisor.process.poll() is not None:
                        raise FrontError("protected sidecar exited")
                    health = client.health()
                    if (health.get("stream") or {}).get("ok") is False:
                        raise FrontError("protected Photon stream degraded")
            except (OSError, FrontError, ValueError):
                audit.emit("sidecar_failed")
                failures += 1
                supervisor.stop()
                stop.wait(min(30, 2 ** min(failures, 4)))
                audit.emit("sidecar_restarted")
    finally:
        stop.set()
        supervisor.stop()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)
        feed_thread.join(timeout=3)
        audit.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
