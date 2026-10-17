"""Inactive Task A Photon front for isolated staging roots.

One protected sidecar owns the sole Spectrum connection. This process reads its
private Unix HTTP event stream and exposes only inbound events and handle-bound
text replies on a separate Hermes Unix socket. The sidecar socket is never
forwarded to Hermes. Deployment still needs OS-level review and integration.
"""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import queue
import socket
import socketserver
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler
from typing import Iterator

from .broker import AdmissionError, PhotonIngressPrototype, peer_uid
from .durable import DurableEventJournal, JournalError
from .transport import MAX_BYTES, TransportError, _object_pairs, isolated_root


MAX_EVENT_LINE = 64 * 1024
MAX_REPLY_BYTES = 8 * 1024
MAX_REPLY_CHARS = 4000
MAX_REQUEST_BYTES = MAX_BYTES + 4096


class FrontError(ValueError):
    pass


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: Path, *, timeout: float = 30):
        super().__init__("localhost", timeout=timeout)
        self.path = str(path)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        try:
            self.sock.connect(self.path)
        except BaseException:
            self.sock.close()
            raise


class ProtectedSidecarClient:
    """Private UDS client. The kernel peer UID is checked before any response."""

    def __init__(self, path: Path, *, sidecar_uid: int, token: str):
        if not token or len(token) < 32:
            raise FrontError("private sidecar token required")
        self.path = path
        self.sidecar_uid = sidecar_uid
        self._token = token

    def _request(self, method: str, route: str, body: bytes | None = None) -> tuple[UnixHTTPConnection, http.client.HTTPResponse]:
        connection = UnixHTTPConnection(self.path)
        connection.connect()
        try:
            if peer_uid(connection.sock) != self.sidecar_uid:
                raise FrontError("private sidecar peer UID mismatch")
            headers = {"X-Hermes-Sidecar-Token": self._token}
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, route, body=body, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                raise FrontError(f"private sidecar status {response.status}")
            return connection, response
        except BaseException:
            connection.close()
            raise

    def events(self) -> Iterator[dict]:
        connection, response = self._request("GET", "/inbound")
        try:
            while True:
                line = response.readline(MAX_EVENT_LINE + 1)
                if not line:
                    return
                if len(line) > MAX_EVENT_LINE:
                    raise FrontError("private event line too large")
                if not line.strip():
                    continue
                try:
                    event = json.loads(line, object_pairs_hook=_object_pairs)
                except (ValueError, UnicodeDecodeError, TransportError) as exc:
                    raise FrontError("malformed private event") from exc
                if not isinstance(event, dict):
                    raise FrontError("private event must be an object")
                yield event
        finally:
            connection.close()

    def send_text(self, space_id: str, text: str) -> str | None:
        body = json.dumps({"spaceId": space_id, "text": text, "format": "text"}, separators=(",", ":")).encode()
        connection, response = self._request("POST", "/send", body)
        try:
            raw = response.read(MAX_REPLY_BYTES + 1)
            if len(raw) > MAX_REPLY_BYTES:
                raise FrontError("private reply too large")
            result = json.loads(raw, object_pairs_hook=_object_pairs)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise FrontError("private send failed")
            message_id = result.get("messageId")
            if message_id is not None and (not isinstance(message_id, str) or len(message_id) > 200):
                raise FrontError("invalid private send receipt")
            return message_id
        except (ValueError, TransportError) as exc:
            raise FrontError("invalid private send response") from exc
        finally:
            connection.close()

    def acknowledge(self, delivery_id: str, decision: str) -> bool:
        if decision not in ("accepted", "rejected", "held"):
            raise FrontError("invalid private delivery decision")
        body = json.dumps({"deliveryId": delivery_id, "decision": decision}, separators=(",", ":")).encode()
        connection, response = self._request("POST", "/ack", body)
        try:
            result = json.loads(response.read(MAX_REPLY_BYTES + 1), object_pairs_hook=_object_pairs)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise FrontError("private acknowledgement failed")
            return result.get("readReceiptOk") is not False
        finally:
            connection.close()

    def health(self) -> dict:
        connection, response = self._request("POST", "/healthz", b"{}")
        try:
            result = json.loads(response.read(MAX_REPLY_BYTES + 1), object_pairs_hook=_object_pairs)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise FrontError("private sidecar unhealthy")
            return result
        finally:
            connection.close()


class StagingPhotonFront:
    def __init__(self, ingress: PhotonIngressPrototype, sidecar: ProtectedSidecarClient,
                 *, journal: DurableEventJournal | None = None, audit=None):
        if ingress.sidecar_uid != sidecar.sidecar_uid:
            raise FrontError("sidecar UID disagreement")
        self.ingress = ingress
        self.sidecar = sidecar
        self.journal = journal
        self.audit = audit or (lambda _code: None)
        self._forwarded: queue.Queue[dict] = queue.Queue(maxsize=1024)
        self._replied: set[str] = set()
        self._lock = threading.Lock()
        self._consumer_lock = threading.Lock()
        self._queued_handles: set[str] = set()
        self._last_forwarded: dict[str, float] = {}
        self._forward_attempts: dict[str, int] = {}
        self._delayed_reported: set[str] = set()
        if journal is not None:
            for handle in journal.recoverable():
                self._queue_handle(handle)

    def _queue_handle(self, handle: str) -> None:
        admitted = self.ingress._events[handle]
        if handle in self._queued_handles:
            return
        forwarded = {
            "handle": handle, "messageId": admitted.message, "platform": "iMessage",
            "space": {"id": admitted.space, "type": "dm"}, "sender": {"id": admitted.sender},
            "content": {"type": "text", "text": admitted.text}, "timestamp": admitted.timestamp.isoformat(),
        }
        self._queued_handles.add(handle)
        try:
            self._forwarded.put_nowait(forwarded)
        except queue.Full:
            self._queued_handles.discard(handle)
            raise FrontError("Hermes event queue full")

    def ingest_protected_event(self, event: dict, *, observed_uid: int) -> str:
        """Called only by the private feed reader; observed_uid is kernel data."""
        if self._forwarded.full():
            raise FrontError("Hermes event queue full")
        with self._lock:
            if self.journal is None:
                handle = self.ingress._admit(event, observed_uid)
            else:
                handle, is_new = self.journal.accept(event, observed_uid=observed_uid)
            self._replied.intersection_update(self.ingress._events)
            if self.journal is not None and is_new and not self.journal.is_reconciled(handle):
                self.audit("reconciliation_required")
            if (self.journal is None or (self.journal.is_reconciled(handle)
                    and self.journal.records[handle]["reply_state"] == "ready")) and self._forward_attempts.get(handle, 0) < 3:
                self._queue_handle(handle)
            return handle

    def read_private_feed(self, *, limit: int | None = None) -> int:
        """Consume one protected stream connection; SDK simulation can serve it."""
        count = 0
        for event in self.sidecar.events():
            delivery_id = event.get("deliveryId") if self.journal is not None else None
            if self.journal is not None and (not isinstance(delivery_id, str) or len(delivery_id) != 32):
                raise FrontError("missing protected delivery identity")
            try:
                handle = self.ingest_protected_event(event, observed_uid=self.sidecar.sidecar_uid)
            except AdmissionError:
                if self.journal is None:
                    raise
                self.audit("event_rejected")
                if delivery_id is not None:
                    self.sidecar.acknowledge(delivery_id, "rejected")
                continue
            except (FrontError, OSError, JournalError):
                self.audit("event_unavailable")
                raise
            if delivery_id is not None:
                decision = "accepted" if self.journal.is_reconciled(handle) else "held"
                if self.sidecar.acknowledge(delivery_id, decision) is False:
                    self.audit("read_receipt_failed")
            self.audit("event_accepted" if self.journal is None or self.journal.is_reconciled(handle)
                       else "event_held")
            count += 1
            if limit is not None and count >= limit:
                break
        return count

    def next_forwarded(self, timeout: float = 25) -> dict | None:
        try:
            event = self._forwarded.get(timeout=timeout)
            handle = event["handle"]
            with self._lock:
                self._queued_handles.discard(handle)
                self._last_forwarded[handle] = time.monotonic()
                self._forward_attempts[handle] = self._forward_attempts.get(handle, 0) + 1
            return event
        except queue.Empty:
            if self.journal is not None:
                with self._lock:
                    for handle in self.journal.recoverable():
                        last = self._last_forwarded.get(handle, 0)
                        if (self._forward_attempts.get(handle, 0) >= 3
                                and handle not in self._delayed_reported):
                            self._delayed_reported.add(handle)
                            self.audit("delivery_delayed")
                        if (handle not in self._queued_handles and self._forward_attempts.get(handle, 0) < 3
                                and time.monotonic() - last >= 30 and not self._forwarded.full()):
                            self._queue_handle(handle)
                            self.audit("event_retried")
            return None

    def reply(self, handle: str, text: str, *, observed_uid: int) -> str | None:
        if observed_uid != self.ingress.hermes_uid:
            raise FrontError("unauthorized Hermes peer")
        if not isinstance(handle, str) or not isinstance(text, str) or not text.strip() or len(text) > MAX_REPLY_CHARS:
            raise FrontError("invalid bounded text reply")
        with self._lock:
            admitted = self.ingress._events.get(handle)
            if admitted is None or handle in self._replied:
                raise FrontError("unknown or used event handle")
            if self.journal is not None and not self.journal.is_reconciled(handle):
                raise FrontError("event reconciliation required")
            if not 0 <= (self.ingress.now() - admitted.timestamp).total_seconds() <= self.ingress.ttl_seconds:
                raise FrontError("expired event handle")
            # Consume before the external send. An uncertain send result must
            # never permit replay and accidental duplicate delivery.
            if self.journal is not None:
                try:
                    self.journal.reserve_reply(handle)
                except JournalError as exc:
                    raise FrontError("unknown or used event handle") from exc
            self._replied.add(handle)
        try:
            result = self.sidecar.send_text(admitted.space, text)
            self.audit("reply_sent")
            return result
        except BaseException:
            self.audit("reply_delivery_failed")
            raise

    def restricted_call(self, method: str, route: str, body: object, *, observed_uid: int) -> tuple[int, dict]:
        """Complete finite request surface; no generic sidecar forwarding."""
        if observed_uid != self.ingress.hermes_uid:
            self.audit("restricted_peer_denied")
            return 403, {"ok": False, "error": "forbidden"}
        if method == "POST" and route == "/healthz":
            return 200, {"ok": True}
        if method != "POST" or route not in ("/reply", "/submit"):
            self.audit("restricted_request_denied")
            return 404, {"ok": False}
        expected = {"handle", "text"} if route == "/reply" else {"handle", "envelope"}
        if not isinstance(body, dict) or set(body) != expected:
            self.audit("restricted_request_denied")
            return 400, {"ok": False, "error": "invalid reply"}
        if not isinstance(body["handle"], str) or len(body["handle"]) > 128:
            self.audit("restricted_request_denied")
            return 400, {"ok": False, "error": "invalid reply"}
        if body["handle"] not in self.ingress._events:
            self.audit("forged_handle_denied")
            return 400, {"ok": False, "error": "invalid reply"}
        try:
            if route == "/submit":
                if self.ingress.transport is None:
                    raise FrontError("lab transport unavailable")
                if self.journal is not None and not self.journal.is_reconciled(body["handle"]):
                    raise FrontError("event reconciliation required")
                envelope = body["envelope"]
                if not isinstance(envelope, str) or len(envelope.encode()) > MAX_BYTES:
                    raise FrontError("invalid envelope bytes")
                request_id = self.ingress.submit_bound(body["handle"], envelope.encode(), observed_uid=observed_uid)
                return 200, {"ok": True, "request_id": request_id}
            message_id = self.reply(body["handle"], body["text"], observed_uid=observed_uid)
        except (FrontError, AdmissionError, TransportError, JournalError):
            self.audit("restricted_request_denied")
            return 400, {"ok": False, "error": "invalid reply"}
        except OSError:
            self.audit("restricted_unavailable")
            return 503, {"ok": False, "error": "unavailable"}
        return 200, {"ok": True, "messageId": message_id}


class _ThreadedUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = 32
    max_handlers = 32

    def process_request(self, request, client_address):
        if not self._handler_slots.acquire(blocking=False):
            self.front.audit("restricted_capacity_denied")
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._handler_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._handler_slots.release()


class HermesRestrictedServer(_ThreadedUnixServer):
    """Only /inbound, /reply and /healthz are reachable on the Hermes socket."""

    def __init__(self, root: Path, socket_name: str, front: StagingPhotonFront,
                 *, activated_fd: int | None = None, _protected: bool = False):
        if _protected:
            if root != Path("/run/alfred-photon-intake") or socket_name != "hermes.sock":
                raise FrontError("protected restricted socket path mismatch")
            info = root.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or (info.st_mode & 0o022):
                raise FrontError("unsafe protected runtime directory")
            self.root = root
        else:
            self.root = isolated_root(root)
        if not socket_name or "/" in socket_name or socket_name in (".", ".."):
            raise FrontError("invalid restricted socket name")
        self.path = self.root / socket_name
        if activated_fd is None and (self.path.exists() or self.path.is_symlink()):
            raise FrontError("restricted socket path already exists")
        self.front = front
        self._handler_slots = threading.BoundedSemaphore(self.max_handlers)
        if activated_fd is None:
            super().__init__(str(self.path), _HermesHandler)
            os.chmod(self.path, 0o660)
            self._socket_inode = self.path.stat().st_ino
        else:
            # The socket manager chooses the Hermes-visible group; the broker
            # never needs membership in Hermes' group or permission to chgrp.
            super().__init__(str(self.path), _HermesHandler, bind_and_activate=False)
            self.socket.close()
            self.socket = socket.fromfd(activated_fd, socket.AF_UNIX, socket.SOCK_STREAM)
            if self.socket.getsockname() != str(self.path):
                self.socket.close()
                raise FrontError("activated socket path mismatch")
            info = self.path.lstat()
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o660 or
                    not self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)):
                self.socket.close()
                raise FrontError("unsafe activated restricted socket")
            self._socket_inode = None

    def server_close(self) -> None:
        super().server_close()
        if self._socket_inode is None:
            return
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(info.st_mode) and info.st_ino == self._socket_inode:
            self.path.unlink()


class _HermesHandler(BaseHTTPRequestHandler):
    server: HermesRestrictedServer
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        pass

    def handle(self) -> None:
        # A socket timeout alone is per read and permits endless slow trickle.
        # The absolute timer covers request-line, headers and POST body.
        deadline = threading.Timer(5, self._expire_request)
        deadline.daemon = True
        self._request_deadline = deadline
        deadline.start()
        try:
            super().handle()
        finally:
            deadline.cancel()

    def _expire_request(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if peer_uid(self.connection) == self.server.front.ingress.hermes_uid:
            return True
        self.server.front.audit("restricted_peer_denied")
        self._json(403, {"ok": False, "error": "forbidden"})
        return False

    def do_GET(self) -> None:
        self.connection.settimeout(35)
        if not self._authorized():
            return
        if self.path != "/inbound":
            self._json(404, {"ok": False})
            return
        self._request_deadline.cancel()
        if not self.server.front._consumer_lock.acquire(blocking=False):
            self.server.front.audit("restricted_consumer_denied")
            self._json(409, {"ok": False, "error": "consumer already connected"})
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            while True:
                item = self.server.front.next_forwarded()
                line = (json.dumps(item, separators=(",", ":")) if item is not None else "") + "\n"
                self.wfile.write(line.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.front._consumer_lock.release()

    def do_POST(self) -> None:
        self.connection.settimeout(5)
        if not self._authorized():
            return
        if self.path not in ("/reply", "/submit"):
            status, response = self.server.front.restricted_call("POST", self.path, None, observed_uid=peer_uid(self.connection))
            self._json(status, response)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
            max_bytes = MAX_REPLY_BYTES if self.path == "/reply" else MAX_REQUEST_BYTES
            if length < 1 or length > max_bytes:
                raise FrontError("invalid request size")
            request = json.loads(self.rfile.read(length), object_pairs_hook=_object_pairs)
            status, response = self.server.front.restricted_call("POST", self.path, request, observed_uid=peer_uid(self.connection))
        except (ValueError, TransportError, FrontError, KeyError, TimeoutError, OSError):
            self.server.front.audit("restricted_request_denied")
            self._json(400, {"ok": False, "error": "invalid reply"})
            return
        self._json(status, response)
