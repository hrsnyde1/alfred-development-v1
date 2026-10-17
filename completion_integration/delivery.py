"""Local durable delivery guard, not a Photon API or a publication verifier.

Only a trusted, verified CompletionNotification may enter here. A receipt string denotes
Photon SDK send acceptance; literal True remains supported for the original mock seam.
Neither means that the owner received or read the message. Owner routing is fixed by
the trusted runtime adapter.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .completion import CompletionNotification

MAX_STATE_BYTES = 1024 * 1024


class DeliveryTrackingError(RuntimeError):
    """Tracking unavailable, unsafe or inconsistent: do not deliver."""


@contextmanager
def _tracking_io() -> Iterator[None]:
    try:
        yield
    except (OSError, ValueError) as exc:
        raise DeliveryTrackingError("delivery tracking unavailable") from exc


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    identity: tuple[str, str, str, str]
    text_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["uncertain", "sent"]
    receipt_id: str | None = Field(default=None, min_length=1, max_length=200)


class _State(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    records: dict[str, _Record]


def _digest(identity: tuple[str, str, str, str]) -> str:
    return hashlib.sha256(
        json.dumps(identity, separators=(",", ":")).encode()
    ).hexdigest()


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    """Pin every directory component; never follow an intermediate symlink."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.absolute().parts[1:]:
            if component in {".", ".."}:
                raise DeliveryTrackingError("unsafe tracking path")
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise DeliveryTrackingError("tracking directory must be private and owned")
        yield fd
    finally:
        os.close(fd)


def _regular(fd: int) -> None:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise DeliveryTrackingError("unsafe tracking file")


def _write(directory: int, state: _State) -> None:
    data = state.model_dump_json().encode()
    if len(data) > MAX_STATE_BYTES:
        raise DeliveryTrackingError("tracking capacity exceeded")
    name = f".delivery-{uuid.uuid4().hex}.tmp"
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, "delivery.json", src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(name, dir_fd=directory)


class DeliveryTracker:
    """Persist an uncertain attempt BEFORE delivery; never automatically resend it.

    Use a pre-provisioned private directory outside protected Gateway evidence.
    Missing state is an error, not a fresh start. Initialization is explicit and only
    for a genuinely new installation. Preserve this directory across reinstalls.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @contextmanager
    def _locked(self) -> Iterator[int]:
        with ExitStack() as stack:
            with _tracking_io():
                directory = stack.enter_context(_directory(self.directory))
                fd = os.open(
                    "delivery.lock",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                    0o600,
                    dir_fd=directory,
                )
                stack.callback(os.close, fd)
                _regular(fd)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield directory

    def initialize(self) -> None:
        """Explicit first-install step; refuses any existing state, even corrupt state."""
        with self._locked() as directory, _tracking_io():
            try:
                os.stat("delivery.json", dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                _write(directory, _State(records={}))
            else:
                raise DeliveryTrackingError("tracking already exists")

    def _read(self, directory: int) -> _State:
        fd = os.open(
            "delivery.json",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        with os.fdopen(fd, "rb") as stream:
            _regular(stream.fileno())
            data = stream.read(MAX_STATE_BYTES + 1)
        if len(data) > MAX_STATE_BYTES:
            raise DeliveryTrackingError("tracking capacity exceeded")

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise DeliveryTrackingError("duplicate tracking key")
                result[key] = value
            return result

        raw = json.loads(data, object_pairs_hook=unique)
        # JSON arrays become tuples only at this explicitly checked boundary.
        if isinstance(raw, dict) and isinstance(raw.get("records"), dict):
            for record in raw["records"].values():
                if isinstance(record, dict) and isinstance(
                    record.get("identity"), list
                ):
                    record["identity"] = tuple(record["identity"])
        state = _State.model_validate(raw)
        if any(
            key != _digest(record.identity) for key, record in state.records.items()
        ):
            raise DeliveryTrackingError("tracking identity mismatch")
        return state

    def deliver(
        self,
        notification: CompletionNotification,
        send: Callable[[CompletionNotification], bool | str],
    ) -> Literal["sent", "already_sent", "uncertain"]:
        """No callback on duplicate, uncertain, corrupt or unavailable tracking.

        Callback errors propagate, leaving uncertain state. A crash even before the
        callback can lose a notification; resolving uncertainty needs host receipts
        or owner reconciliation, never a blind retry. This is not exactly-once delivery.
        """
        identity = (
            notification.project,
            notification.task_id,
            notification.pr_url,
            notification.commit,
        )
        key = _digest(identity)
        text_digest = hashlib.sha256(notification.text.encode()).hexdigest()
        with self._locked() as directory:
            with _tracking_io():
                state = self._read(directory)
            existing = state.records.get(key)
            if existing is not None:
                if existing.text_digest != text_digest:
                    raise DeliveryTrackingError("notification content changed")
                return "already_sent" if existing.state == "sent" else "uncertain"
            state.records[key] = _Record(
                identity=identity, text_digest=text_digest, state="uncertain"
            )
            with _tracking_io():
                _write(directory, state)
            receipt = send(notification)
            if receipt is not True and not (
                type(receipt) is str
                and 1 <= len(receipt) <= 200
                and not any(ord(c) < 33 for c in receipt)
            ):
                return "uncertain"
            if type(receipt) is str:
                state.records[key].receipt_id = receipt
            state.records[key].state = "sent"
            with _tracking_io():
                _write(directory, state)
            return "sent"
