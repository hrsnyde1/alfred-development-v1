"""Owner receipt and notifier acknowledgement can differ; never retry blindly."""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from completion_integration import delivery, runtime
from completion_integration.completion import CompletionNotification
from completion_integration.delivery import DeliveryTracker

pytest_plugins = ("test_completion_integration",)


@pytest.mark.parametrize(
    "failure", ["response_timeout", "missing_receipt", "success_write"]
)
def test_owner_receipt_then_blocked_has_no_durable_receipt_or_resend(
    world, failure, capsys
):
    received = []
    response = Mock(status=200)
    response.read.return_value = json.dumps(
        {
            "ok": True,
            "messageId": None if failure == "missing_receipt" else "mock-receipt",
        }
    ).encode()
    connection = Mock()
    connection.request.side_effect = lambda *args: received.append(
        json.loads(args[2])["text"]
    )
    if failure == "response_timeout":
        connection.getresponse.side_effect = TimeoutError(
            "mock acknowledgement timeout"
        )
    else:
        connection.getresponse.return_value = response
    sender = runtime.PhotonSender(
        port=8789,
        token="mock-token",
        space_id="mock-owner-dm",
        connection=Mock(return_value=connection),
    )
    original_run = runtime.run
    original_write = delivery._write

    def run_fixture(*args, **kwargs):
        return original_run(
            world["protected"] / "config.json",
            send=kwargs["send"],
            get_pr=world["get_pr"],
            sender_factory=lambda config: sender,
            paused_check=lambda: True,
            trusted_uid=os.geteuid(),
            trusted_root=world["protected"],
        )

    def write_fixture(directory, state):
        if failure == "success_write" and any(
            r.state == "sent" for r in state.records.values()
        ):
            raise PermissionError("mock confirmation persistence failure")
        return original_write(directory, state)

    with (
        patch.object(runtime, "run", side_effect=run_fixture),
        patch.object(delivery, "_write", side_effect=write_fixture),
    ):
        assert runtime.main(["notify"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "BLOCKED",
        "detail": "completion prerequisites or reconciliation failed",
    }
    assert len(received) == 1
    path = world["state"] / "delivery.json"
    original = path.read_bytes()
    record = next(iter(json.loads(original)["records"].values()))
    assert record["state"] == "uncertain"
    assert record.get("receipt_id") is None
    assert hashlib.sha256(received[0].encode()).hexdigest() == record["text_digest"]
    # A new runtime/tracker instance does not call the transport again.
    assert world["run"](send=True)["status"] == "uncertain"
    world["send"].assert_not_called()
    assert path.read_bytes() == original


def test_owner_confirmation_note_preserves_uncertainty_across_process_restarts(
    tmp_path,
):
    directory = tmp_path / "delivery"
    directory.mkdir(mode=0o700)
    notice = CompletionNotification(
        "fixture",
        "T-0002",
        "https://github.com/owner/repo/pull/1",
        "a" * 40,
        "fixture summary",
        "fixture completion text",
    )
    tracker = DeliveryTracker(directory)
    tracker.initialize()
    assert tracker.deliver(notice, lambda n: False) == "uncertain"
    state = directory / "delivery.json"
    original = state.read_bytes()
    key, record = next(iter(json.loads(original)["records"].items()))
    # This is an independent mock audit note, not a Photon receipt or state edit.
    note = {
        "resolution": "owner_confirmed_received",
        "transport_acknowledgement": "unresolved",
        "delivery_sha256": hashlib.sha256(original).hexdigest(),
        "record_key": key,
        "identity": record["identity"],
        "text_digest": record["text_digest"],
        "photon_receipt_id": None,
        "resend_permitted": False,
        "evidence": "mock owner statement for this test only",
    }
    (tmp_path / "owner-confirmation.json").write_text(json.dumps(note))
    script = """
import json, sys
from pathlib import Path
from completion_integration.completion import CompletionNotification
from completion_integration.delivery import DeliveryTracker
def forbidden_send(notification):
    raise AssertionError("duplicate send attempted")
notice = CompletionNotification(**json.loads(sys.argv[2]))
print(DeliveryTracker(Path(sys.argv[1])).deliver(notice, forbidden_send))
"""
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", script, str(directory), json.dumps(asdict(notice))],
            env=os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "uncertain"
        assert state.read_bytes() == original
