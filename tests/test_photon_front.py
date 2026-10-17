from __future__ import annotations

import datetime as dt
import errno
import http.client
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import socketserver
import tempfile
import threading

import pytest

from task_a.broker import AdmissionError, PhotonIngressPrototype
from task_a.photon_front import FrontError, HermesRestrictedServer, ProtectedSidecarClient, StagingPhotonFront, UnixHTTPConnection, _ThreadedUnixServer
from task_a.transport import LabInboxTransport


NOW = dt.datetime(2026, 10, 14, 9, 30, tzinfo=dt.timezone.utc)


def test_saturated_handler_limit_closes_stalled_client_without_spawning_thread():
    server = object.__new__(_ThreadedUnixServer)
    server._handler_slots = threading.BoundedSemaphore(1)
    server._handler_slots.acquire()
    codes = []
    server.front = type("Front", (), {"audit": codes.append})()
    closed = []
    request = type("Request", (), {"close": lambda self: closed.append(True)})()
    server.process_request(request, None)
    assert closed == [True]
    assert codes == ["restricted_capacity_denied"]


def synthetic_event(**changes):
    event = {"messageId": "lab-message", "platform": "iMessage",
             "space": {"id": "lab-space", "type": "dm"},
             "sender": {"id": "synthetic-authorized-id"},
             "content": {"type": "text", "text": "Prepare a lab-only note."},
             "timestamp": "2026-10-14T09:29:59Z"}
    event.update(changes)
    return event


class _SidecarServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class _SyntheticSDKHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path != "/inbound" or self.headers.get("X-Hermes-Sidecar-Token") != self.server.private_token:
            self.send_error(403)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(json.dumps(self.server.event).encode() + b"\n")

    def do_POST(self):
        if self.path != "/send" or self.headers.get("X-Hermes-Sidecar-Token") != self.server.private_token:
            self.send_error(403)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.sends.append(body)
        response = b'{"ok":true,"messageId":"synthetic-outbound"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


@pytest.fixture
def front():
    with tempfile.TemporaryDirectory(prefix="p", dir=tempfile.gettempdir()) as directory:
        lab_root = Path(directory)
        (lab_root / ".task-a-isolated-root").write_text("TASK_A_LAB_ONLY\n")
        yield from _front_in_root(lab_root)


def _front_in_root(lab_root):
    private_token = "a" * 64
    sidecar_path = lab_root / "private.sock"
    try:
        sidecar_server = _SidecarServer(str(sidecar_path), _SyntheticSDKHandler)
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            pytest.skip("sandbox denies Unix socket bind; OS IPC integration pending")
        raise
    sidecar_server.private_token = private_token
    sidecar_server.event = synthetic_event()
    sidecar_server.sends = []
    os.chmod(sidecar_path, 0o600)
    sidecar_thread = threading.Thread(target=sidecar_server.serve_forever, daemon=True)
    sidecar_thread.start()
    ingress = PhotonIngressPrototype(sidecar_uid=os.getuid(), hermes_uid=os.getuid(),
                                    allowed_sender="synthetic-authorized-id", transport=None,
                                    now=lambda: NOW)
    client = ProtectedSidecarClient(sidecar_path, sidecar_uid=os.getuid(), token=private_token)
    protected = StagingPhotonFront(ingress, client)
    restricted = HermesRestrictedServer(lab_root, "hermes.sock", protected)
    hermes_thread = threading.Thread(target=restricted.serve_forever, daemon=True)
    hermes_thread.start()
    try:
        yield protected, restricted.path, sidecar_server
    finally:
        restricted.shutdown()
        restricted.server_close()
        sidecar_server.shutdown()
        sidecar_server.server_close()
        sidecar_path.unlink(missing_ok=True)


def request(socket_path: Path, method: str, route: str, body: dict | None = None):
    conn = UnixHTTPConnection(socket_path)
    payload = json.dumps(body).encode() if body is not None else None
    conn.request(method, route, body=payload, headers={"Content-Type": "application/json"} if payload else {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, json.loads(data)


def test_single_private_feed_and_bounded_reply(front):
    protected, socket_path, sdk = front
    assert protected.read_private_feed(limit=1) == 1
    forwarded = protected.next_forwarded(timeout=0)
    assert set(forwarded) == {"handle", "messageId", "platform", "space", "sender", "content", "timestamp"}
    assert forwarded["space"]["id"] == "lab-space"
    assert "token" not in json.dumps(forwarded).lower()
    status, response = request(socket_path, "POST", "/reply", {"handle": forwarded["handle"], "text": "Lab reply."})
    assert status == 200 and response["messageId"] == "synthetic-outbound"
    assert sdk.sends == [{"spaceId": "lab-space", "text": "Lab reply.", "format": "text"}]
    status, _ = request(socket_path, "POST", "/reply", {"handle": forwarded["handle"], "text": "Replay"})
    assert status == 400 and len(sdk.sends) == 1


def test_restricted_socket_never_exposes_privileged_controls(front):
    protected, socket_path, sdk = front
    for route in ("/send-attachment", "/send", "/shutdown", "/probe", "/control", "/events"):
        status, _ = request(socket_path, "POST", route, {"path": "/etc/shadow", "spaceId": "attacker"})
        assert status == 404
    protected.read_private_feed(limit=1)
    handle = protected.next_forwarded(timeout=0)["handle"]
    for body in (
        {"handle": handle, "text": "x", "path": "/etc/shadow"},
        {"handle": handle, "text": "x", "spaceId": "other-company"},
        {"handle": handle, "text": "x", "token": sdk.private_token},
    ):
        status, _ = request(socket_path, "POST", "/reply", body)
        assert status == 400
    assert sdk.sends == []


def test_forged_sender_replay_and_cross_company_rejected(front):
    protected, _socket_path, sdk = front
    for bad in (
        synthetic_event(sender={"id": "forged"}),
        synthetic_event(sender={"id": None}),
        synthetic_event(space={"id": "other-company", "type": "group"}),
        synthetic_event(timestamp="2026-10-13T09:00:00Z"),
    ):
        with pytest.raises(AdmissionError):
            protected.ingest_protected_event(bad, observed_uid=os.getuid())
    with pytest.raises(AdmissionError):
        protected.ingest_protected_event(synthetic_event(), observed_uid=os.getuid() + 1)
    protected.read_private_feed(limit=1)
    with pytest.raises(AdmissionError, match="replayed"):
        protected.read_private_feed(limit=1)
    assert sdk.sends == []


def test_ipc_forgery_and_unapproved_destination_rejected(front):
    protected, socket_path, sdk = front
    status, _ = request(socket_path, "POST", "/reply", {"handle": "invented", "text": "Hi"})
    assert status == 400
    with pytest.raises(FrontError, match="unauthorized"):
        protected.reply("invented", "Hi", observed_uid=os.getuid() + 1)
    protected.read_private_feed(limit=1)
    handle = protected.next_forwarded(timeout=0)["handle"]
    with pytest.raises(FrontError, match="bounded"):
        protected.reply(handle, "x" * 4001, observed_uid=os.getuid())
    with pytest.raises(FrontError, match="expired"):
        protected.ingress.now = lambda: NOW + dt.timedelta(minutes=6)
        protected.reply(handle, "Hi", observed_uid=os.getuid())
    assert sdk.sends == []


class _FakePrivateSidecar:
    def __init__(self, event):
        self.sidecar_uid = os.getuid()
        self.event = event
        self.sends = []

    def events(self):
        yield self.event

    def send_text(self, space, text):
        self.sends.append((space, text))
        return "synthetic-outbound"


@pytest.fixture
def front_model():
    sdk = _FakePrivateSidecar(synthetic_event())
    ingress = PhotonIngressPrototype(sidecar_uid=os.getuid(), hermes_uid=os.getuid() + 1,
                                    allowed_sender="synthetic-authorized-id", transport=None, now=lambda: NOW)
    return StagingPhotonFront(ingress, sdk), sdk


def test_synthetic_sdk_feed_binds_reply_to_authenticated_space(front_model):
    protected, sdk = front_model
    assert protected.read_private_feed(limit=1) == 1
    event = protected.next_forwarded(timeout=0)
    assert event["sender"]["id"] == "synthetic-authorized-id"
    assert "token" not in json.dumps(event).lower()
    status, receipt = protected.restricted_call("POST", "/reply", {"handle": event["handle"], "text": "Done."},
                                               observed_uid=protected.ingress.hermes_uid)
    assert status == 200 and receipt["messageId"] == "synthetic-outbound"
    assert sdk.sends == [("lab-space", "Done.")]
    status, _ = protected.restricted_call("POST", "/reply", {"handle": event["handle"], "text": "Again"},
                                        observed_uid=protected.ingress.hermes_uid)
    assert status == 400 and len(sdk.sends) == 1


def test_forged_handle_and_restricted_route_denials_are_audited(front_model):
    protected, _sdk = front_model
    codes = []
    protected.audit = codes.append
    assert protected.restricted_call("POST", "/reply", {"handle": "invented", "text": "x"},
                                     observed_uid=protected.ingress.hermes_uid)[0] == 400
    assert protected.restricted_call("POST", "/shutdown", {},
                                     observed_uid=protected.ingress.hermes_uid)[0] == 404
    assert protected.restricted_call("POST", "/reply", {"handle": "invented", "text": "x"},
                                     observed_uid=protected.ingress.hermes_uid + 10)[0] == 403
    assert codes == ["forged_handle_denied", "restricted_request_denied", "restricted_peer_denied"]


@pytest.mark.parametrize("route", ["/send-attachment", "/send", "/shutdown", "/probe", "/control", "/events"])
def test_synthetic_restricted_surface_blocks_privileged_routes(front_model, route):
    protected, sdk = front_model
    status, _ = protected.restricted_call("POST", route, {"path": "/etc/shadow", "spaceId": "other-company"},
                                        observed_uid=protected.ingress.hermes_uid)
    assert status == 404 and sdk.sends == []


@pytest.mark.parametrize("extra", [{"path": "/etc/shadow"}, {"spaceId": "other-company"}, {"token": "forged"}])
def test_synthetic_reply_rejects_paths_destinations_and_tokens(front_model, extra):
    protected, sdk = front_model
    protected.read_private_feed(limit=1)
    handle = protected.next_forwarded(timeout=0)["handle"]
    status, _ = protected.restricted_call("POST", "/reply", {"handle": handle, "text": "Hi", **extra},
                                        observed_uid=protected.ingress.hermes_uid)
    assert status == 400 and sdk.sends == []


def test_synthetic_sender_replay_and_peer_forgery(front_model):
    protected, sdk = front_model
    for event in (
        synthetic_event(sender={"id": "forged"}),
        synthetic_event(sender={"id": None}),
        synthetic_event(space={"id": "lab-space", "type": "group"}),
        synthetic_event(timestamp="2026-10-13T09:00:00Z"),
    ):
        with pytest.raises(AdmissionError):
            protected.ingest_protected_event(event, observed_uid=protected.ingress.sidecar_uid)
    with pytest.raises(AdmissionError):
        protected.ingest_protected_event(synthetic_event(), observed_uid=protected.ingress.hermes_uid)
    protected.read_private_feed(limit=1)
    with pytest.raises(AdmissionError, match="replayed"):
        protected.read_private_feed(limit=1)
    assert sdk.sends == []


def test_synthetic_ipc_forgery_broker_privilege_and_expiry(front_model):
    protected, sdk = front_model
    assert protected.restricted_call("POST", "/reply", {"handle": "fake", "text": "x"},
                                    observed_uid=protected.ingress.hermes_uid)[0] == 400
    assert protected.restricted_call("POST", "/reply", {"handle": "fake", "text": "x"},
                                    observed_uid=protected.ingress.sidecar_uid)[0] == 403
    protected.read_private_feed(limit=1)
    handle = protected.next_forwarded(timeout=0)["handle"]
    assert protected.restricted_call("POST", "/reply", {"handle": handle, "text": "x" * 4001},
                                    observed_uid=protected.ingress.hermes_uid)[0] == 400
    protected.ingress.now = lambda: NOW + dt.timedelta(minutes=6)
    assert protected.restricted_call("POST", "/reply", {"handle": handle, "text": "x"},
                                    observed_uid=protected.ingress.hermes_uid)[0] == 400
    assert sdk.sends == []


def test_synthetic_bound_submit_preserves_gateway_envelope(front_model, lab_root, envelope_data):
    protected, _sdk = front_model
    inbox = lab_root / "home/Alfred/projects/hermes-requests/inbox"
    inbox.mkdir(parents=True)
    ledger = lab_root / "ledger"
    ledger.mkdir()
    protected.ingress.transport = LabInboxTransport(lab_root, inbox, ledger, secret=b"synthetic-staging-ledger-key")
    protected.read_private_feed(limit=1)
    handle = protected.next_forwarded(timeout=0)["handle"]
    envelope_data["origin"]["conversation_ref"] = "lab-space/lab-message"
    envelope_data["utterance"] = "Prepare a lab-only note."
    envelope = json.dumps(envelope_data, sort_keys=True, separators=(",", ":"))
    body = {"handle": handle, "envelope": envelope}
    status, result = protected.restricted_call("POST", "/submit", body, observed_uid=protected.ingress.hermes_uid)
    assert status == 200 and result["request_id"] == envelope_data["request_id"]
    assert (inbox / (result["request_id"] + ".json")).read_bytes() == envelope.encode()
    assert protected.restricted_call("POST", "/submit", body, observed_uid=protected.ingress.hermes_uid)[0] == 200
    assert len(list(inbox.glob("*.json"))) == 1
    for change in (
        {"project_hint": "other-company"},
        {"utterance": "Model-forged words"},
        {"origin": {"interface": "photon", "conversation_ref": "forged"}},
        {"approved_by": "model"},
    ):
        candidate = {**envelope_data, **change}
        assert protected.restricted_call("POST", "/submit", {"handle": handle, "envelope": json.dumps(candidate)},
                                         observed_uid=protected.ingress.hermes_uid)[0] == 400
    assert protected.restricted_call("POST", "/submit", {**body, "path": "/etc/shadow"},
                                     observed_uid=protected.ingress.hermes_uid)[0] == 400
