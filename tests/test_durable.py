from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from task_a.audit import AuditLog
from task_a.broker import AdmissionError, PhotonIngressPrototype
from task_a.durable import DurableEventJournal, JournalError
from task_a.photon_front import FrontError, StagingPhotonFront


NOW = dt.datetime(2026, 10, 14, 9, 30, tzinfo=dt.timezone.utc)


def event(*, sender="synthetic-authorized-id", message="m1"):
    return {"deliveryId": "a" * 32, "messageId": message, "platform": "iMessage",
            "space": {"id": "space-one", "type": "dm"}, "sender": {"id": sender},
            "content": {"type": "text", "text": "Authorized lab request"},
            "timestamp": "2026-10-14T09:29:59Z"}


class FakeSidecar:
    sidecar_uid = 41011

    def __init__(self, events):
        self.input = list(events)
        self.acks = []
        self.sends = []
        self.on_ack = None
        self.on_send = None
        self.read_receipt_ok = True

    def events(self):
        yield from self.input

    def acknowledge(self, delivery_id, decision):
        if self.on_ack:
            self.on_ack()
        self.acks.append((delivery_id, decision))
        return self.read_receipt_ok

    def send_text(self, space, text):
        if self.on_send:
            self.on_send()
        self.sends.append((space, text))
        return "outbound-1"


def make_front(root: Path, *, events=None):
    directory = root / "journal"
    directory.mkdir(mode=0o700, exist_ok=True)
    ingress = PhotonIngressPrototype(sidecar_uid=41011, hermes_uid=41012,
                                    allowed_sender="synthetic-authorized-id", transport=None,
                                    now=lambda: NOW)
    journal = DurableEventJournal(directory, ingress, key=b"k" * 32,
                                  synthetic_verified=True)
    sidecar = FakeSidecar(events or [])
    audit = []
    front = StagingPhotonFront(ingress, sidecar, journal=journal, audit=audit.append)
    return front, sidecar, audit


def test_durable_acceptance_precedes_sidecar_ack_and_reuses_handle(tmp_path):
    front, sidecar, audit = make_front(tmp_path, events=[event()])
    def require_persisted():
        assert list((tmp_path / "journal").glob("*.json"))
    sidecar.on_ack = require_persisted
    assert front.read_private_feed(limit=1) == 1
    first = front.next_forwarded(timeout=0)
    assert sidecar.acks == [("a" * 32, "accepted")]
    restarted, replay_sidecar, _ = make_front(tmp_path, events=[event()])
    assert restarted.next_forwarded(timeout=0)["handle"] == first["handle"]
    assert restarted.read_private_feed(limit=1) == 1
    assert replay_sidecar.acks == [("a" * 32, "accepted")]
    assert len(list((tmp_path / "journal").glob("*.json"))) == 1
    assert "event_accepted" in audit


def test_rejection_is_explicit_and_does_not_create_record(tmp_path):
    front, sidecar, audit = make_front(tmp_path, events=[event(sender="forged")])
    assert front.read_private_feed() == 0
    assert sidecar.acks == [("a" * 32, "rejected")]
    assert not list((tmp_path / "journal").glob("*.json"))
    assert audit == ["event_rejected"]


def test_read_receipt_failure_is_audited_after_durable_acceptance(tmp_path):
    front, sidecar, audit = make_front(tmp_path, events=[event()])
    sidecar.read_receipt_ok = False
    assert front.read_private_feed(limit=1) == 1
    assert sidecar.acks == [("a" * 32, "accepted")]
    assert list((tmp_path / "journal").glob("*.json"))
    assert "read_receipt_failed" in audit


def test_conflicting_replay_metadata_is_rejected(tmp_path):
    front, _sidecar, _audit = make_front(tmp_path, events=[event()])
    assert front.read_private_feed(limit=1) == 1
    changed = event()
    changed["content"]["quoted"] = True
    with pytest.raises(AdmissionError, match="conflicting replay"):
        front.journal.accept(changed, observed_uid=41011)
    changed = event()
    changed["timestamp"] = "2026-10-14T09:29:58Z"
    with pytest.raises(AdmissionError, match="conflicting replay"):
        front.journal.accept(changed, observed_uid=41011)


def test_retry_limit_reports_delayed_state_without_losing_journal(tmp_path, monkeypatch):
    import queue
    front, _sidecar, audit = make_front(tmp_path, events=[event()])
    front.read_private_feed(limit=1)
    handle = front.next_forwarded(timeout=0)["handle"]
    front._forward_attempts[handle] = 3
    monkeypatch.setattr(front._forwarded, "get", lambda **_kwargs: (_ for _ in ()).throw(queue.Empty()))
    assert front.next_forwarded(timeout=0) is None
    assert "delivery_delayed" in audit
    restarted, _sidecar, _audit = make_front(tmp_path)
    assert restarted.next_forwarded(timeout=0)["handle"] == handle


def test_duplicate_sidecar_ack_retry_does_not_bypass_forward_limit(tmp_path):
    front, _sidecar, _audit = make_front(tmp_path, events=[event()])
    front.read_private_feed(limit=1)
    handle = front.next_forwarded(timeout=0)["handle"]
    front._forward_attempts[handle] = 3
    front.ingest_protected_event(event(), observed_uid=41011)
    assert front._forwarded.empty()


def test_persist_failure_is_unavailable_and_not_acknowledged(tmp_path, monkeypatch):
    front, sidecar, audit = make_front(tmp_path, events=[event()])
    def fail(_record):
        raise OSError("injected disk failure")
    monkeypatch.setattr(front.journal, "_persist", fail)
    with pytest.raises(OSError):
        front.read_private_feed()
    assert sidecar.acks == []
    assert front.ingress._events == {}
    assert "event_unavailable" in audit


def test_reply_reservation_survives_uncertain_send(tmp_path):
    front, sidecar, audit = make_front(tmp_path, events=[event()])
    front.read_private_feed(limit=1)
    handle = front.next_forwarded(timeout=0)["handle"]
    def fail_after_reserve():
        assert front.journal.records[handle]["reply_state"] == "reserved"
        raise OSError("injected uncertain send")
    sidecar.on_send = fail_after_reserve
    with pytest.raises(OSError):
        front.reply(handle, "response", observed_uid=41012)
    restarted, _, _ = make_front(tmp_path)
    with pytest.raises(FrontError):
        restarted.reply(handle, "duplicate", observed_uid=41012)
    assert "reply_delivery_failed" in audit


def test_capacity_refusal_leaves_sidecar_delivery_pending(tmp_path):
    front, sidecar, audit = make_front(tmp_path, events=[event()])
    for i in range(front._forwarded.maxsize):
        front._forwarded.put_nowait({"handle": str(i)})
    with pytest.raises(FrontError, match="queue full"):
        front.read_private_feed()
    assert sidecar.acks == []
    assert "event_unavailable" in audit


def test_audit_codes_never_include_principal_or_text(tmp_path):
    directory = tmp_path / "audit"
    directory.mkdir(mode=0o700)
    audit = AuditLog(directory / "events.jsonl")
    try:
        audit.emit("event_rejected")
        with pytest.raises(ValueError):
            audit.emit("sender=synthetic-authorized-id")
    finally:
        audit.close()
    data = (directory / "events.jsonl").read_text()
    assert "synthetic-authorized-id" not in data and "Authorized lab request" not in data
    assert json.loads(data)["code"] == "event_rejected"


def test_audit_storage_is_bounded_and_fails_closed(tmp_path, monkeypatch):
    import task_a.audit as audit_module
    directory = tmp_path / "audit"
    directory.mkdir(mode=0o700)
    audit = AuditLog(directory / "events.jsonl")
    try:
        monkeypatch.setattr(audit_module, "MAX_AUDIT_BYTES", 1)
        with pytest.raises(OSError, match="capacity"):
            audit.emit("event_accepted")
    finally:
        audit.close()


def test_every_repeated_authorization_denial_is_recorded(tmp_path):
    directory = tmp_path / "audit"
    directory.mkdir(mode=0o700)
    path = directory / "events.jsonl"
    audit = AuditLog(path)
    try:
        audit.emit("forged_handle_denied")
        audit.emit("forged_handle_denied")
    finally:
        audit.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 2
    assert all(set(record) == {"time_ns", "code"} and record["code"] == "forged_handle_denied"
               for record in records)


def test_provider_unverified_event_never_reaches_hermes_or_gateway(tmp_path):
    directory = tmp_path / "journal"
    directory.mkdir(mode=0o700)
    ingress = PhotonIngressPrototype(sidecar_uid=41011, hermes_uid=41012,
                                    allowed_sender="synthetic-authorized-id", transport=None,
                                    now=lambda: NOW)
    codes = []
    journal = DurableEventJournal(directory, ingress, key=b"k" * 32, audit=codes.append)
    sidecar = FakeSidecar([event()])
    front = StagingPhotonFront(ingress, sidecar, journal=journal, audit=codes.append)
    assert front.read_private_feed(limit=1) == 1
    handle = next(iter(journal.records))
    assert journal.records[handle]["continuity"] == "unverified"
    assert sidecar.acks == [("a" * 32, "held")]
    assert journal.recoverable() == []
    assert front.next_forwarded(timeout=0) is None
    with pytest.raises(FrontError, match="reconciliation"):
        front.reply(handle, "reply", observed_uid=41012)
    assert sidecar.sends == []
    assert "reconciliation_required" in codes


def test_unanswered_event_survives_ttl_and_restart_for_reconciliation(tmp_path):
    directory = tmp_path / "journal"
    directory.mkdir(mode=0o700)
    now = [NOW]
    def ingress():
        return PhotonIngressPrototype(sidecar_uid=41011, hermes_uid=41012,
                                      allowed_sender="synthetic-authorized-id", transport=None,
                                      now=lambda: now[0])
    first = DurableEventJournal(directory, ingress(), key=b"k" * 32)
    handle, created = first.accept(event(), observed_uid=41011)
    assert created and len(list(directory.glob("*.json"))) == 1
    now[0] += dt.timedelta(seconds=301)
    codes = []
    second = DurableEventJournal(directory, ingress(), key=b"k" * 32, audit=codes.append)
    assert handle in second.records
    assert second.records[handle]["lifecycle"] == "expired"
    assert second.unresolved_count() == 1
    assert len(list(directory.glob("*.json"))) == 1
    assert codes == ["event_expired_unresolved"]


def test_live_journal_expiry_is_persisted_before_recovery(tmp_path):
    directory = tmp_path / "journal"
    directory.mkdir(mode=0o700)
    now = [NOW]
    ingress = PhotonIngressPrototype(sidecar_uid=41011, hermes_uid=41012,
                                    allowed_sender="synthetic-authorized-id", transport=None,
                                    now=lambda: now[0])
    codes = []
    journal = DurableEventJournal(directory, ingress, key=b"k" * 32,
                                  synthetic_verified=True, audit=codes.append)
    handle, _ = journal.accept(event(), observed_uid=41011)
    now[0] += dt.timedelta(seconds=301)
    assert journal.recoverable() == []
    assert journal.records[handle]["lifecycle"] == "expired"
    assert codes == ["event_expired_unresolved"]


def test_unresolved_journal_capacity_fails_closed(tmp_path):
    front, _sidecar, _audit = make_front(tmp_path)
    front.journal.records = {str(index): {} for index in range(1024)}
    with pytest.raises(JournalError, match="capacity"):
        front.journal.accept(event(), observed_uid=41011)
    assert front.ingress._events == {}
