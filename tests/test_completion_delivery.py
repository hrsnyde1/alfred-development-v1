"""Durable delivery regression tests: temporary state and mock transport only."""

import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from completion_integration import delivery
from completion_integration.completion import CompletionNotification
from completion_integration.delivery import DeliveryTracker, DeliveryTrackingError

NOTICE = CompletionNotification(
    "alfred",
    "T-0017",
    "https://github.com/owner/alfred/pull/12",
    "a" * 40,
    "Development complete; draft PR awaits owner review.",
    "fixture message",
)


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    result = tmp_path / "notifications"
    result.mkdir(mode=0o700)
    DeliveryTracker(result).initialize()
    return result


def test_repeated_events_and_restart_do_not_deliver_twice(directory: Path) -> None:
    send = Mock(return_value=True)
    tracker = DeliveryTracker(directory)
    assert tracker.deliver(NOTICE, send) == "sent"
    assert tracker.deliver(NOTICE, send) == "already_sent"
    assert DeliveryTracker(directory).deliver(NOTICE, send) == "already_sent"
    send.assert_called_once_with(NOTICE)


@pytest.mark.parametrize("field", ["project", "task_id", "pr_url", "commit"])
def test_identity_binds_every_publication_field(directory: Path, field: str) -> None:
    send = Mock(return_value=True)
    assert DeliveryTracker(directory).deliver(NOTICE, send) == "sent"
    changed = replace(NOTICE, **{field: getattr(NOTICE, field) + "different"})
    assert DeliveryTracker(directory).deliver(changed, send) == "sent"
    assert send.call_count == 2


@pytest.mark.parametrize("result", [False, None])
def test_unconfirmed_delivery_remains_uncertain_after_restart(
    directory: Path, result: bool | None
) -> None:
    send = Mock(return_value=result)
    assert DeliveryTracker(directory).deliver(NOTICE, send) == "uncertain"
    assert DeliveryTracker(directory).deliver(NOTICE, send) == "uncertain"
    send.assert_called_once()


def test_success_followed_by_crash_before_success_record(directory: Path) -> None:
    send = Mock(return_value=True)
    real_write = delivery._write

    def crash_on_success(fd: int, state: delivery._State) -> None:
        if any(record.state == "sent" for record in state.records.values()):
            raise SystemExit("simulated crash after delivery")
        real_write(fd, state)

    with (
        patch.object(delivery, "_write", side_effect=crash_on_success),
        pytest.raises(SystemExit),
    ):
        DeliveryTracker(directory).deliver(NOTICE, send)
    assert DeliveryTracker(directory).deliver(NOTICE, send) == "uncertain"
    send.assert_called_once()


def test_timeout_after_possible_delivery_never_blindly_retries(directory: Path) -> None:
    send = Mock(side_effect=TimeoutError("possible delivery"))
    with pytest.raises(TimeoutError):
        DeliveryTracker(directory).deliver(NOTICE, send)
    assert DeliveryTracker(directory).deliver(NOTICE, send) == "uncertain"
    send.assert_called_once()


def test_attempt_is_durable_before_callback(directory: Path) -> None:
    def send(_: CompletionNotification) -> bool:
        assert '"state":"uncertain"' in (directory / "delivery.json").read_text()
        raise SystemExit("crash before delivery confirmation")

    with pytest.raises(SystemExit):
        DeliveryTracker(directory).deliver(NOTICE, send)
    other_send = Mock(return_value=True)
    assert DeliveryTracker(directory).deliver(NOTICE, other_send) == "uncertain"
    other_send.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        b"{",
        b"",
        b"{}",
        b'{"version":2,"records":{}}',
        b'{"version":1,"records":{},"records":{}}',
        b'{"version":1,"records":{"bad":{"identity":["a","b","c","d"],'
        b'"text_digest":"' + b"a" * 64 + b'","state":"sent"}}}',
        b'{"version":1,"records":{"bad":{}}}',
    ],
)
def test_corruption_fails_closed(directory: Path, data: bytes) -> None:
    state = directory / "delivery.json"
    state.write_bytes(data)
    send = Mock(return_value=True)
    with pytest.raises(DeliveryTrackingError):
        DeliveryTracker(directory).deliver(NOTICE, send)
    assert state.read_bytes() == data
    send.assert_not_called()


def test_missing_state_is_not_implicitly_reinitialized(directory: Path) -> None:
    (directory / "delivery.json").unlink()
    send = Mock(return_value=True)
    with pytest.raises(DeliveryTrackingError):
        DeliveryTracker(directory).deliver(NOTICE, send)
    send.assert_not_called()


def test_initialization_never_overwrites_existing_state(directory: Path) -> None:
    path = directory / "delivery.json"
    path.write_bytes(b"corrupt")
    with pytest.raises(DeliveryTrackingError):
        DeliveryTracker(directory).initialize()
    assert path.read_bytes() == b"corrupt"


def test_write_failure_before_delivery_blocks_callback(directory: Path) -> None:
    before = (directory / "delivery.json").read_bytes()
    send = Mock(return_value=True)
    with (
        patch(
            "completion_integration.delivery.os.replace", side_effect=PermissionError
        ),
        pytest.raises(DeliveryTrackingError),
    ):
        DeliveryTracker(directory).deliver(NOTICE, send)
    assert (directory / "delivery.json").read_bytes() == before
    assert list(directory.glob("*.tmp")) == []
    send.assert_not_called()


def test_inaccessible_tracking_blocks_callback(directory: Path) -> None:
    send = Mock(return_value=True)
    with (
        patch("completion_integration.delivery.os.open", side_effect=PermissionError),
        pytest.raises(DeliveryTrackingError),
    ):
        DeliveryTracker(directory).deliver(NOTICE, send)
    send.assert_not_called()


def test_symlink_state_is_not_read(directory: Path, tmp_path: Path) -> None:
    state = directory / "delivery.json"
    outside = tmp_path / "outside"
    state.rename(outside)
    state.symlink_to(outside)
    send = Mock(return_value=True)
    with pytest.raises(DeliveryTrackingError):
        DeliveryTracker(directory).deliver(NOTICE, send)
    send.assert_not_called()


def test_unsafe_directory_is_refused(directory: Path) -> None:
    directory.chmod(0o755)
    send = Mock(return_value=True)
    with pytest.raises(DeliveryTrackingError):
        DeliveryTracker(directory).deliver(NOTICE, send)
    send.assert_not_called()


def test_competing_instances_cannot_deliver_same_event(directory: Path) -> None:
    competitor = Mock(return_value=True)

    def send(_: CompletionNotification) -> bool:
        with pytest.raises(DeliveryTrackingError):
            DeliveryTracker(directory).deliver(NOTICE, competitor)
        return True

    assert DeliveryTracker(directory).deliver(NOTICE, send) == "sent"
    competitor.assert_not_called()


def test_changed_message_cannot_reset_publication_identity(directory: Path) -> None:
    send = Mock(return_value=True)
    assert DeliveryTracker(directory).deliver(NOTICE, send) == "sent"
    with pytest.raises(DeliveryTrackingError):
        DeliveryTracker(directory).deliver(replace(NOTICE, text="changed"), send)
    send.assert_called_once()


def test_real_process_exit_after_mock_send_leaves_durable_uncertainty(
    directory: Path,
) -> None:
    script = """
import json
import os
import sys
from pathlib import Path
from completion_integration.completion import CompletionNotification
from completion_integration.delivery import DeliveryTracker

root = Path(sys.argv[1])
notice = CompletionNotification(**json.loads(sys.argv[2]))
def mock_send(notification):
    (root / 'mock-delivered').write_text(notification.text)
    os._exit(7)
DeliveryTracker(root).deliver(notice, mock_send)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(directory), json.dumps(asdict(NOTICE))],
        env=os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 7, result.stderr.decode()
    assert (directory / "mock-delivered").read_text() == NOTICE.text
    send = Mock(return_value=True)
    assert DeliveryTracker(directory).deliver(NOTICE, send) == "uncertain"
    send.assert_not_called()
