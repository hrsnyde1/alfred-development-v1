"""A slow sidecar acknowledgement is still a sent completion (demo-site T-0003).

The sidecar answers /send only after Photon's remote send returns. On 2026-10-18 the
owner received T-0003's "All done" text, but the acknowledgement took longer than the
old two-second socket timeout: the worker raised, the record stayed `uncertain` and the
task was held as `completion: python/python_failed`. These tests use a mock loopback
sidecar only; nothing reaches Photon.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import pytest

from completion_integration import runtime
from completion_integration.completion import CompletionNotification
from completion_integration.delivery import DeliveryTracker


@pytest.fixture
def sidecar():
    """A loopback stand-in for the sidecar that acknowledges after `delay` seconds."""
    state = {"delay": 0.0, "received": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["received"].append(json.loads(body))
            time.sleep(state["delay"])
            raw = json.dumps({"ok": True, "messageId": "spc-msg-mock"}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except OSError:
                pass  # the client already gave up

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["port"] = server.server_address[1]
    yield state
    server.shutdown()
    server.server_close()


def sender(port):
    return runtime.PhotonSender(port=port, token="mock-token", space_id="mock-owner-dm")


def notification():
    return CompletionNotification(
        project="demo-site",
        task_id="T-0003",
        pr_url="https://github.com/hrsnyde1/alfred-demo-site/pull/1",
        commit="c" * 40,
        summary="mock summary",
        text="All done with demo-site. It's on GitHub as a draft for your review.",
    )


def tracker(tmp_path):
    state = tmp_path / "delivery"
    state.mkdir(mode=0o700)
    result = DeliveryTracker(state)
    result.initialize()
    return result, state


def test_acknowledgement_slower_than_two_seconds_is_sent(sidecar, tmp_path):
    sidecar["delay"] = 2.5
    deliveries, state = tracker(tmp_path)
    assert deliveries.deliver(notification(), sender(sidecar["port"])) == "sent"
    [record] = json.loads((state / "delivery.json").read_text())["records"].values()
    assert record["state"] == "sent"
    assert record["receipt_id"] == "spc-msg-mock"
    assert len(sidecar["received"]) == 1


def test_acknowledgement_past_the_bound_stays_uncertain_and_is_not_resent(
    sidecar, tmp_path
):
    sidecar["delay"] = 1.0
    deliveries, state = tracker(tmp_path)
    with patch.object(runtime, "ACK_TIMEOUT", 0.3), pytest.raises(TimeoutError):
        deliveries.deliver(notification(), sender(sidecar["port"]))
    [record] = json.loads((state / "delivery.json").read_text())["records"].values()
    assert (record["state"], record["receipt_id"]) == ("uncertain", None)
    # Fail closed: a rerun never sends the same notification again.
    assert deliveries.deliver(notification(), sender(sidecar["port"])) == "uncertain"
    assert len(sidecar["received"]) == 1


def test_connect_is_short_and_acknowledgement_wait_is_long():
    response = Mock(status=200)
    response.read.return_value = b'{"ok": true, "messageId": "spc-msg-mock"}'
    connection = Mock()
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    photon = runtime.PhotonSender(
        port=8789, token="mock-token", space_id="mock-owner-dm", connection=factory
    )
    assert photon(Mock(text="mock completion text")) == "spc-msg-mock"
    assert factory.call_args.kwargs == {"timeout": runtime.CONNECT_TIMEOUT}
    assert runtime.CONNECT_TIMEOUT == 2
    # Connect, then lengthen the wait, all before the text is handed to the sidecar.
    names = [c[0] for c in connection.mock_calls]
    assert names[:3] == ["connect", "sock.settimeout", "request"]
    connection.sock.settimeout.assert_called_once_with(runtime.ACK_TIMEOUT)
    assert 20 <= runtime.ACK_TIMEOUT < 1200  # below the worker's own timeout


def test_refused_connection_sends_nothing():
    connection = Mock()
    connection.connect.side_effect = ConnectionRefusedError()
    photon = runtime.PhotonSender(
        port=8789,
        token="mock-token",
        space_id="mock-owner-dm",
        connection=Mock(return_value=connection),
    )
    with pytest.raises(ConnectionRefusedError):
        photon(Mock(text="mock completion text"))
    connection.request.assert_not_called()
    connection.close.assert_called_once()
