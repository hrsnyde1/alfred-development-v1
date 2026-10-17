"""Protected, bounded Photon event journal for at-least-once front delivery.

The journal is owned by the protected Photon identity. It records an event
before the sidecar is acknowledged and records a reply reservation before any
external send. A replay after a crash reuses the same handle and destination.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import tempfile

from .broker import AdmittedEvent, AdmissionError, PhotonIngressPrototype
from .transport import _atomic, _object_pairs


class JournalError(ValueError):
    pass


class DurableEventJournal:
    def __init__(self, directory: Path, ingress: PhotonIngressPrototype, *, key: bytes,
                 synthetic_verified: bool = False, audit=None):
        if len(key) < 32:
            raise JournalError("journal key too short")
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise JournalError("unsafe protected event journal")
        # There is no supported provider continuity proof yet. This flag exists
        # solely for isolated synthetic fixtures and cannot activate on the
        # proposed protected state path.
        temporary = Path(tempfile.gettempdir()).resolve()
        if synthetic_verified and not directory.resolve().is_relative_to(temporary):
            raise JournalError("synthetic verification requires temporary state")
        self.directory = directory
        self.ingress = ingress
        self.key = key
        self.synthetic_verified = synthetic_verified
        self.audit = audit or (lambda _code: None)
        self.records: dict[str, dict] = {}
        self.by_event: dict[str, str] = {}
        self._load()

    def _name(self, event_key: str) -> str:
        return hmac.new(self.key, event_key.encode(), hashlib.sha256).hexdigest() + ".json"

    def _persist(self, record: dict) -> None:
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            _atomic(fd, self._name(record["event_key"]), json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
        finally:
            os.close(fd)

    def _load(self) -> None:
        paths = list(self.directory.iterdir())
        if len(paths) > 1024:
            raise JournalError("event journal capacity exceeded")
        for path in paths:
            if not path.name.endswith(".json"):
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_size > 65536:
                raise JournalError("unsafe event record")
            record = json.loads(path.read_bytes(), object_pairs_hook=_object_pairs)
            legacy = {"event_key", "handle", "sender", "space", "message", "text", "timestamp", "reply_state"}
            if not isinstance(record, dict) or set(record) not in (legacy, legacy | {"continuity", "lifecycle"}):
                raise JournalError("invalid event record")
            if set(record) == legacy:
                # Existing v0.1.3 records have no provider continuity proof.
                record = {**record, "continuity": "unverified", "lifecycle": "open"}
                self._persist(record)
            if record["continuity"] == "synthetic_verified" and not self.synthetic_verified:
                record = {**record, "continuity": "unverified"}
                self._persist(record)
            if (path.name != self._name(record["event_key"]) or record["reply_state"] not in ("ready", "reserved")
                    or record["continuity"] not in ("unverified", "synthetic_verified")
                    or record["lifecycle"] not in ("open", "expired")):
                raise JournalError("invalid event record identity")
            event = AdmittedEvent(record["sender"], record["space"], record["message"], record["text"],
                                  dt.datetime.fromisoformat(record["timestamp"]))
            if event.key != record["event_key"] or record["handle"] in self.records or event.key in self.by_event:
                raise JournalError("conflicting event record")
            # Keep old records for deduplication, but only live handles can be
            # used for replies or replay to Hermes.
            self.records[record["handle"]] = record
            self.by_event[event.key] = record["handle"]
            if record["lifecycle"] == "open" and 0 <= (self.ingress.now() - event.timestamp).total_seconds() <= self.ingress.ttl_seconds:
                self.ingress._events[record["handle"]] = event
                self.ingress._event_keys.add(event.key)
        self._refresh_expired()

    def _refresh_expired(self) -> None:
        """Preserve unresolved work and its immutable event identity past TTL."""
        for handle, record in list(self.records.items()):
            if handle not in self.ingress._events and record["lifecycle"] == "open":
                updated = {**record, "lifecycle": "expired"}
                self._persist(updated)
                self.records[handle] = updated
                self.audit("event_expired_unresolved")

    def is_reconciled(self, handle: str) -> bool:
        record = self.records.get(handle)
        admitted = self.ingress._events.get(handle)
        if record and admitted is not None and record["lifecycle"] == "open":
            age = (self.ingress.now() - admitted.timestamp).total_seconds()
            if not 0 <= age <= self.ingress.ttl_seconds:
                self.ingress._events.pop(handle, None)
                self.ingress._event_keys.discard(admitted.key)
                self._refresh_expired()
                return False
        return bool(record and record["lifecycle"] == "open" and
                    record["continuity"] == "synthetic_verified" and admitted is not None)

    def unresolved_count(self) -> int:
        return sum(record["continuity"] == "unverified" or record["lifecycle"] == "expired"
                   for record in self.records.values())

    def accept(self, event: dict, *, observed_uid: int) -> tuple[str, bool]:
        if observed_uid != self.ingress.sidecar_uid:
            raise AdmissionError("untrusted ingress process")
        try:
            key = "\0".join((event["sender"]["id"], event["space"]["id"], event["messageId"]))
        except (TypeError, KeyError, AttributeError) as exc:
            raise AdmissionError("invalid event identity") from exc
        existing = self.by_event.get(key)
        if existing:
            record = self.records[existing]
            content = event.get("content")
            if (not isinstance(content, dict) or record["text"] != content.get("text")
                    or content.get("type") != "text" or content.get("forwarded") or content.get("quoted")
                    or event.get("platform") != "iMessage" or not isinstance(event.get("space"), dict)
                    or event["space"].get("type") != "dm"
                    or event.get("timestamp") not in (record["timestamp"], record["timestamp"].replace("+00:00", "Z"))):
                raise AdmissionError("conflicting replay")
            admitted = self.ingress._events.get(existing)
            if admitted is None or not 0 <= (self.ingress.now() - admitted.timestamp).total_seconds() <= self.ingress.ttl_seconds:
                raise AdmissionError("expired event replay")
            return existing, False
        self.ingress._prune_expired()
        if len(self.records) >= 1024:
            raise JournalError("event journal capacity reached; reconciliation required")
        self._refresh_expired()
        handle = self.ingress._admit(event, observed_uid)
        admitted = self.ingress._events[handle]
        record = {"event_key": admitted.key, "handle": handle, "sender": admitted.sender,
                  "space": admitted.space, "message": admitted.message, "text": admitted.text,
                  "timestamp": admitted.timestamp.isoformat(), "reply_state": "ready",
                  "continuity": "synthetic_verified" if self.synthetic_verified else "unverified",
                  "lifecycle": "open"}
        try:
            self._persist(record)
        except BaseException:
            self.ingress._events.pop(handle, None)
            self.ingress._event_keys.discard(admitted.key)
            raise
        self.records[handle] = record
        self.by_event[admitted.key] = handle
        return handle, True

    def reserve_reply(self, handle: str) -> None:
        record = self.records.get(handle)
        if record is None or record["reply_state"] != "ready" or not self.is_reconciled(handle):
            raise JournalError("unknown, expired or used event handle")
        updated = {**record, "reply_state": "reserved"}
        self._persist(updated)
        self.records[handle] = updated

    def recoverable(self) -> list[str]:
        return [handle for handle, record in self.records.items() if self.is_reconciled(handle)
                and record["reply_state"] == "ready"]
