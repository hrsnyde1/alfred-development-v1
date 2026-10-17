"""Photon ingress policy and synthetic lab transport prototype.

No live Photon connection, Hermes tool, production socket listener or policy
loader is present. Only the sidecar-facing process may call ``admit_socket``;
``SO_PEERCRED`` comes from the kernel, never from JSON or model arguments.
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import secrets
import socket
import struct
from dataclasses import dataclass
from typing import Callable

from .transport import LabInboxTransport, TransportError, _object_pairs, inspect_envelope


class AdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class AdmittedEvent:
    sender: str
    space: str
    message: str
    text: str
    timestamp: dt.datetime

    @property
    def key(self) -> str:
        return "\0".join((self.sender, self.space, self.message))

    @property
    def conversation_ref(self) -> str:
        return f"{self.space}/{self.message}"


def peer_uid(connection: socket.socket) -> int:
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", credentials)
    return uid


class PhotonIngressPrototype:
    def __init__(self, *, sidecar_uid: int, hermes_uid: int, allowed_sender: str,
                 transport: LabInboxTransport, now: Callable[[], dt.datetime] | None = None,
                 ttl_seconds: int = 300, synthetic_submission_enabled: bool = False):
        if not allowed_sender or allowed_sender == "*" or not isinstance(allowed_sender, str):
            raise AdmissionError("one explicit synthetic sender required")
        self.sidecar_uid = sidecar_uid
        self.hermes_uid = hermes_uid
        self.allowed_sender = allowed_sender
        self.transport = transport
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self.ttl_seconds = ttl_seconds
        self.synthetic_submission_enabled = synthetic_submission_enabled
        self._events: dict[str, AdmittedEvent] = {}
        self._event_keys: set[str] = set()

    def _prune_expired(self) -> None:
        current = self.now()
        expired = [handle for handle, event in self._events.items()
                   if (current - event.timestamp).total_seconds() > self.ttl_seconds]
        for handle in expired:
            self._event_keys.discard(self._events.pop(handle).key)

    def admit_socket(self, connection: socket.socket) -> str:
        """Read a single bounded normalized sidecar event on an already accepted UDS."""
        uid = peer_uid(connection)
        raw = connection.recv(16385)
        if len(raw) > 16384 or not raw:
            raise AdmissionError("event size refused")
        try:
            event = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_pairs)
        except (UnicodeDecodeError, json.JSONDecodeError, TransportError) as exc:
            raise AdmissionError("malformed sidecar event") from exc
        return self._admit(event, uid)

    def _admit(self, event: object, observed_uid: int) -> str:
        """Private pure core; observed_uid is injected only by tests or SO_PEERCRED."""
        if observed_uid != self.sidecar_uid or not isinstance(event, dict):
            raise AdmissionError("untrusted ingress process")
        sender = event.get("sender")
        space = event.get("space")
        content = event.get("content")
        if not isinstance(sender, dict) or not isinstance(space, dict) or not isinstance(content, dict):
            raise AdmissionError("missing explicit event fields")
        sender_id = sender.get("id")
        if not isinstance(sender_id, str) or not sender_id or not hmac.compare_digest(sender_id, self.allowed_sender):
            raise AdmissionError("explicit sender not allowlisted")
        if space.get("type") != "dm" or event.get("platform") != "iMessage":
            raise AdmissionError("not a direct Photon message")
        if content.get("type") != "text" or content.get("forwarded") or content.get("quoted"):
            raise AdmissionError("not plain direct-user text")
        space_id, message_id, body = space.get("id"), event.get("messageId"), content.get("text")
        if not all(isinstance(x, str) and 0 < len(x) <= 200 for x in (space_id, message_id)):
            raise AdmissionError("missing bounded event identity")
        if not isinstance(body, str) or not body.strip() or len(body) > 8000:
            raise AdmissionError("invalid event text")
        try:
            timestamp = dt.datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, ValueError) as exc:
            raise AdmissionError("missing event time") from exc
        if timestamp.tzinfo is None or not 0 <= (self.now() - timestamp).total_seconds() <= self.ttl_seconds:
            raise AdmissionError("stale or future event")
        admitted = AdmittedEvent(sender_id, space_id, message_id, body, timestamp)
        self._prune_expired()
        if admitted.key in self._event_keys:
            raise AdmissionError("replayed Photon event")
        if len(self._events) >= 1024:
            raise AdmissionError("event handle capacity reached")
        handle = secrets.token_urlsafe(32)
        self._events[handle] = admitted
        self._event_keys.add(admitted.key)
        return handle

    def submit_synthetic_fixture(self, handle: str, envelope: bytes, *, observed_uid: int) -> str:
        """Test-only: exercise binding and transport; not an exposed Hermes tool."""
        if not self.synthetic_submission_enabled:
            raise AdmissionError("synthetic submission disabled")
        return self.submit_bound(handle, envelope, observed_uid=observed_uid)

    def submit_bound(self, handle: str, envelope: bytes, *, observed_uid: int) -> str:
        """Accept only the admitted event's exact origin, text and lab project."""
        if observed_uid != self.hermes_uid or not isinstance(handle, str) or handle not in self._events:
            raise AdmissionError("unknown handle or caller")
        admitted = self._events[handle]
        if not 0 <= (self.now() - admitted.timestamp).total_seconds() <= self.ttl_seconds:
            raise AdmissionError("expired event")
        document = inspect_envelope(envelope)
        if document["origin"] != {"interface": "photon", "conversation_ref": admitted.conversation_ref}:
            raise AdmissionError("origin not bound to admitted event")
        if document["utterance"] != admitted.text or document["project_hint"] != "dev-001":
            raise AdmissionError("event text or lab project mismatch")
        return self.transport.submit(admitted.key, envelope)
