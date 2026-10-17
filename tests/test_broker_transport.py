from __future__ import annotations

import copy
import datetime as dt
import json
import os
from pathlib import Path
import socket
import subprocess

import pytest

from task_a.broker import AdmissionError, PhotonIngressPrototype
from task_a.transport import LabInboxTransport, TransportError
from alfred.gateway.envelope import parse_envelope
from alfred.gateway.requesters import require_bound_requester
from alfred.registry.loader import parse_registry


NOW = dt.datetime(2026, 10, 14, 9, 30, tzinfo=dt.timezone.utc)


@pytest.fixture
def transport(lab_root: Path) -> LabInboxTransport:
    home = lab_root / "home"
    intake = home / "Alfred/projects/hermes-requests"
    (intake / "inbox").mkdir(parents=True)
    assert require_bound_requester(intake, home) == "hermes"
    ledger = lab_root / "ledger"
    ledger.mkdir()
    return LabInboxTransport(lab_root, intake / "inbox", ledger, secret=b"staging-key-with-adequate-length")


@pytest.fixture
def broker(transport: LabInboxTransport) -> PhotonIngressPrototype:
    return PhotonIngressPrototype(sidecar_uid=os.getuid(), hermes_uid=os.getuid() + 1,
                                  allowed_sender="synthetic-authorized-id", transport=transport,
                                  now=lambda: NOW, synthetic_submission_enabled=True)


@pytest.fixture
def event() -> dict:
    return {"messageId": "lab-message", "platform": "iMessage", "space": {"id": "lab-space", "type": "dm"},
            "sender": {"id": "synthetic-authorized-id"}, "content": {"type": "text", "text": "Please create a laboratory documentation task."},
            "timestamp": "2026-10-14T09:29:59Z"}


def test_explicit_authenticated_sender_and_bound_synthetic_transport(broker, event, envelope_bytes):
    left, right = socket.socketpair()
    try:
        try:
            left.sendall(json.dumps(event).encode())
        except PermissionError:
            pytest.skip("sandbox denies Unix socket send; kernel peer integration pending")
        handle = broker.admit_socket(right)  # peer UID is kernel-provided, not JSON.
    finally:
        left.close(); right.close()
    assert broker.submit_synthetic_fixture(handle, envelope_bytes, observed_uid=broker.hermes_uid) == json.loads(envelope_bytes)["request_id"]
    assert parse_envelope(json.loads(envelope_bytes)).protocol == "alfred.devreq/1"
    assert list(broker.transport.inbox.glob("*.json")) == [broker.transport.inbox / (json.loads(envelope_bytes)["request_id"] + ".json")]
    assert broker.submit_synthetic_fixture(handle, envelope_bytes, observed_uid=broker.hermes_uid)
    assert len(list(broker.transport.inbox.glob("*.json"))) == 1


@pytest.mark.parametrize("mutation", [
    lambda e: e["sender"].update(id=None),
    lambda e: e["sender"].update(id="forged"),
    lambda e: e["space"].update(type="group"),
    lambda e: e["content"].update(type="reply"),
    lambda e: e["content"].update(forwarded=True),
    lambda e: e.update(timestamp="2026-10-13T09:00:00Z"),
    lambda e: e.update(messageId=None),
    lambda e: e.update(platform="cli"),
])
def test_untrusted_or_fallback_event_rejected(broker, event, mutation):
    mutation(event)
    with pytest.raises(AdmissionError):
        broker._admit(event, broker.sidecar_uid)


def test_company_mastermind_or_model_cannot_mint_ingress(broker, event, envelope_bytes):
    with pytest.raises(AdmissionError):
        broker._admit(event, broker.sidecar_uid + 20)
    with pytest.raises(AdmissionError):
        broker.submit_synthetic_fixture("model-invented-handle", envelope_bytes, observed_uid=broker.hermes_uid)
    handle = broker._admit(event, broker.sidecar_uid)
    with pytest.raises(AdmissionError):
        broker.submit_synthetic_fixture(handle, envelope_bytes, observed_uid=broker.hermes_uid + 1)
    forged = json.loads(envelope_bytes)
    forged["origin"]["conversation_ref"] = "model-claimed-conversation"
    with pytest.raises(AdmissionError):
        broker.submit_synthetic_fixture(handle, json.dumps(forged).encode(), observed_uid=broker.hermes_uid)
    assert not list(broker.transport.inbox.glob("*.json"))


def test_synthetic_submit_disabled_by_default(transport, event, envelope_bytes):
    broker = PhotonIngressPrototype(sidecar_uid=1, hermes_uid=2, allowed_sender="synthetic-authorized-id",
                                    transport=transport, now=lambda: NOW)
    handle = broker._admit(event, 1)
    with pytest.raises(AdmissionError, match="disabled"):
        broker.submit_synthetic_fixture(handle, envelope_bytes, observed_uid=2)


def test_model_cannot_choose_company_repo_or_workflow_fields(broker, event, envelope_bytes):
    handle = broker._admit(event, broker.sidecar_uid)
    bad = json.loads(envelope_bytes)
    bad["project_hint"] = "real-company-repo"
    with pytest.raises(AdmissionError):
        broker.submit_synthetic_fixture(handle, json.dumps(bad).encode(), observed_uid=broker.hermes_uid)
    bad = json.loads(envelope_bytes)
    bad["approved_by"] = "model"
    with pytest.raises(TransportError):
        broker.submit_synthetic_fixture(handle, json.dumps(bad).encode(), observed_uid=broker.hermes_uid)
    assert not list(broker.transport.inbox.glob("*.json"))


@pytest.mark.parametrize("stage", ["after_prepare", "after_publish"])
def test_crash_recovery_and_exact_bytes(transport, envelope_bytes, stage):
    with pytest.raises(RuntimeError):
        transport.submit("synthetic-event", envelope_bytes, fail_at=stage)
    request_id = transport.submit("synthetic-event", envelope_bytes)
    assert (transport.inbox / f"{request_id}.json").read_bytes() == envelope_bytes
    assert transport.submit("synthetic-event", envelope_bytes) == request_id
    assert len(list(transport.inbox.glob("*.json"))) == 1
    (transport.inbox / f"{request_id}.json").unlink()  # Models Gateway processing/move.
    assert transport.submit("synthetic-event", envelope_bytes) == request_id
    assert not list(transport.inbox.glob("*.json"))


def test_retry_resyncs_visible_file_before_marking_ledger_sent(transport, envelope_bytes, monkeypatch):
    """A renamed file can be visible after a crash before syncfs commits it."""
    import task_a.transport as module
    real_sync = module._sync_filesystem
    calls = []

    def interrupt_before_sync(_fd):
        raise OSError("injected crash before inbox syncfs")

    monkeypatch.setattr(module, "_sync_filesystem", interrupt_before_sync)
    with pytest.raises(OSError, match="before inbox syncfs"):
        transport.submit("crash-window-event", envelope_bytes)
    request_id = json.loads(envelope_bytes)["request_id"]
    assert (transport.inbox / f"{request_id}.json").read_bytes() == envelope_bytes
    ledger = next(transport.ledger.glob("*.json"))
    assert json.loads(ledger.read_text())["state"] == "prepared"

    def count_sync(fd):
        calls.append(fd)
        real_sync(fd)

    monkeypatch.setattr(module, "_sync_filesystem", count_sync)
    assert transport.submit("crash-window-event", envelope_bytes) == request_id
    assert len(calls) == 1
    assert json.loads(ledger.read_text())["state"] == "sent"


@pytest.mark.parametrize("stage", [
    "before_prepare", "after_prepare", "before_file_fsync", "after_file_fsync",
    "before_publish_rename", "after_publish_rename", "before_inbox_sync", "after_inbox_sync",
    "after_publish", "before_ledger_sent", "after_ledger_sent",
])
def test_each_commit_boundary_recovers_idempotently(transport, envelope_bytes, stage):
    with pytest.raises(RuntimeError, match="injected crash"):
        transport.submit("commit-boundary-event", envelope_bytes, fail_at=stage)
    request_id = json.loads(envelope_bytes)["request_id"]
    assert transport.submit("commit-boundary-event", envelope_bytes) == request_id
    assert transport.submit("commit-boundary-event", envelope_bytes) == request_id
    assert (transport.inbox / f"{request_id}.json").read_bytes() == envelope_bytes
    assert len(list(transport.inbox.glob("*.json"))) == 1
    assert json.loads(next(transport.ledger.glob("*.json")).read_text())["state"] == "sent"


@pytest.mark.parametrize("failure", ["after_prepare", "after_publish"])
def test_retry_decision_is_privacy_safe_and_durable(lab_root, envelope_bytes, failure):
    from task_a.transport import LabInboxTransport
    inbox, ledger = lab_root / "inbox", lab_root / "ledger"
    inbox.mkdir(); ledger.mkdir()
    codes = []
    writer = LabInboxTransport(lab_root, inbox, ledger, secret=b"k" * 32, audit=codes.append)
    with pytest.raises(RuntimeError):
        writer.submit("event", envelope_bytes, fail_at=failure)
    assert writer.submit("event", envelope_bytes) == json.loads(envelope_bytes)["request_id"]
    assert codes == ["inbox_recovered"]
    assert len(list(inbox.glob("*.json"))) == 1


def test_failed_retry_is_audited_without_event_identity(lab_root, envelope_bytes, monkeypatch):
    import task_a.transport as module
    inbox, ledger = lab_root / "inbox", lab_root / "ledger"
    inbox.mkdir(); ledger.mkdir()
    codes = []
    writer = LabInboxTransport(lab_root, inbox, ledger, secret=b"k" * 32, audit=codes.append)
    with pytest.raises(RuntimeError):
        writer.submit("private-event-key", envelope_bytes, fail_at="after_prepare")
    monkeypatch.setattr(module, "_sync_filesystem", lambda _fd: (_ for _ in ()).throw(OSError("sync unavailable")))
    with pytest.raises(OSError, match="sync unavailable"):
        writer.submit("private-event-key", envelope_bytes)
    assert codes == ["inbox_retry_failed"]
    assert "private-event-key" not in "".join(codes)


def test_conflicting_retry_and_symlink_refused(transport, envelope_bytes, lab_root):
    transport.submit("event-1", envelope_bytes)
    conflict = json.loads(envelope_bytes)
    conflict["utterance"] += " changed"
    with pytest.raises(TransportError, match="conflicting"):
        transport.submit("event-1", json.dumps(conflict).encode())
    outside = lab_root / "outside"
    outside.mkdir()
    (lab_root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(TransportError):
        LabInboxTransport(lab_root, lab_root / "linked", transport.ledger, secret=b"staging-key-with-adequate-length")


def test_create_only_inbox_needs_no_directory_read(transport, envelope_bytes):
    """Same-UID model of the proposed broker ACL; cross-UID DAC is separate."""
    inbox = transport.inbox
    prior_mode = inbox.stat().st_mode & 0o7777
    inbox.chmod(0o300)
    try:
        with pytest.raises(PermissionError):
            list(inbox.iterdir())
        fresh = LabInboxTransport(transport.root, inbox, transport.ledger, secret=transport.secret)
        request_id = fresh.submit("create-only-event", envelope_bytes)
        assert fresh.submit("create-only-event", envelope_bytes) == request_id
        assert (inbox / f"{request_id}.json").read_bytes() == envelope_bytes
    finally:
        inbox.chmod(prior_mode)


def test_inbox_publication_never_replaces_colliding_request_id(transport, envelope_bytes):
    request_id = json.loads(envelope_bytes)["request_id"]
    target = transport.inbox / f"{request_id}.json"
    target.write_bytes(b"preexisting gateway-owned sentinel")
    with pytest.raises(TransportError, match="inbox filename conflict"):
        transport.submit("different-event", envelope_bytes)
    assert target.read_bytes() == b"preexisting gateway-owned sentinel"


def test_setgid_inbox_envelope_metadata_for_gateway_read(transport, envelope_bytes):
    inbox = transport.inbox
    old_mode = inbox.stat().st_mode & 0o7777
    inbox.chmod(0o2300)
    try:
        request_id = transport.submit("gateway-readable-event", envelope_bytes)
        published = inbox / f"{request_id}.json"
        assert published.stat().st_gid == inbox.stat().st_gid
        assert published.stat().st_mode & 0o777 == 0o640
    finally:
        inbox.chmod(old_mode)


def test_lab_registry_is_only_alfred_dev001(lab_root):
    import yaml
    fixture = Path(__file__).resolve().parents[1] / "templates/registry/projects.yaml"
    data = yaml.safe_load(fixture.read_text())
    data["projects"][0]["local_path"] = str(lab_root / "dev-001")
    registry = parse_registry(data)
    assert [p.id for p in registry.projects] == ["dev-001"]
    assert registry.resolve("dev-001").project.company == "alfred"
    assert registry.resolve("other-company").project is None
    assert registry.resolve("real-repo").project is None


def test_disposable_gateway_files_one_unapproved_task_after_broker_write(transport, envelope_bytes, lab_root):
    """Real dispatcher/filer modules, temporary HOME/registry/repository only."""
    import intake
    import yaml
    from alfred.gateway.dispatcher import GatewayConfig, run_once
    home = lab_root / "home"
    repo = lab_root / "dev-001"
    (repo / ".dev/tasks").mkdir(parents=True)
    (repo / "README.md").write_text("Disposable lab only.\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    fixture = Path(__file__).resolve().parents[1] / "templates/registry/projects.yaml"
    registry_data = yaml.safe_load(fixture.read_text())
    registry_data["projects"][0]["local_path"] = str(repo)
    registry = parse_registry(registry_data)
    assert require_bound_requester(transport.inbox.parent, home) == "hermes"
    config = GatewayConfig(intake_dir=transport.inbox.parent, gateway_dir=home / "Alfred/gateway",
                           home=home, today="2026-10-14")
    transport.submit("synthetic-event-1", envelope_bytes)
    first = run_once(registry, intake.IntakeFiler(), config)
    assert len(first.filed) == 1
    specs = list((repo / ".dev/tasks").glob("*.md"))
    assert len(specs) == 1
    text = specs[0].read_text()
    assert "status: proposed" in text and "source: hermes" in text
    assert "approved_by: null" in text
    assert not list(repo.glob(".git/config.lock"))
    # The transport returns the old receipt even after Gateway moved the file.
    assert transport.submit("synthetic-event-1", envelope_bytes) == json.loads(envelope_bytes)["request_id"]
    second = run_once(registry, intake.IntakeFiler(), config)
    assert second.filed == []
    assert len(list((repo / ".dev/tasks").glob("*.md"))) == 1
