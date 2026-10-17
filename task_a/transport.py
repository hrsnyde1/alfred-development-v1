"""Staging-only, crash-safe writer for the Gateway's *lab* Hermes inbox.

This is a transport, not a Gateway or an approval authority. The protected
Gateway validates and files each envelope. All paths must be inside a marked
temporary root; production use requires a separately reviewed release.
"""

from __future__ import annotations

import base64
import ctypes
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid


MAX_BYTES = 64 * 1024
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
TOP_LEVEL = frozenset({"protocol", "request_id", "revision", "submitted_at", "origin", "utterance", "project_hint", "intent_confidence", "draft", "answers"})


class TransportError(ValueError):
    pass


def isolated_root(root: Path) -> Path:
    root = root.resolve(strict=True)
    temporary = Path(tempfile.gettempdir()).resolve()
    if root == temporary or not root.is_relative_to(temporary):
        raise TransportError("only a marked temporary test root is permitted")
    marker = root / ".task-a-isolated-root"
    if marker.is_symlink() or not marker.is_file() or marker.read_text() != "TASK_A_LAB_ONLY\n":
        raise TransportError("missing isolated-root marker")
    return root


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TransportError("duplicate JSON key")
        result[key] = value
    return result


def inspect_envelope(payload: bytes) -> dict:
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES or not payload:
        raise TransportError("invalid envelope size")
    try:
        doc = json.loads(payload.decode("utf-8"), object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportError("malformed envelope") from exc
    if not isinstance(doc, dict) or set(doc) != TOP_LEVEL or doc.get("protocol") != "alfred.devreq/1":
        raise TransportError("not the bounded canonical envelope shape")
    if not isinstance(doc.get("request_id"), str) or not UUID.fullmatch(doc["request_id"]):
        raise TransportError("invalid request ID")
    if type(doc.get("revision")) is not int or doc["revision"] != 1:
        raise TransportError("Task A fixture accepts revision 1 only")
    return doc


def _open_dir(path: Path, *, create_only: bool = False) -> int:
    if path.is_symlink():
        raise TransportError("symlink directory refused")
    flags = (os.O_PATH if create_only else os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path, flags)
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise TransportError("not a directory")
    return fd


def _read_file(directory_fd: int, name: str) -> bytes | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2 * MAX_BYTES:
            raise TransportError("unsafe existing file")
        return stream.read(2 * MAX_BYTES + 1)


def _sync_filesystem(fd: int) -> None:
    """Persist a create-only inbox rename without a readable directory fd.

    Linux syncfs accepts an ordinary file descriptor on the target filesystem.
    O_PATH directory descriptors cannot be fsync'ed, and granting directory
    read permission solely for fsync would expose unrelated inbox names.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.syncfs(fd) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def _rename_noreplace(directory_fd: int, old: str, new: str) -> None:
    """Publish atomically without clobbering a concurrent Gateway file.

    A hard-link-then-unlink sequence leaves two links after a crash between
    those calls. Linux renameat2 avoids that unrecoverable retry state while
    requiring only search/write access to the create-only inbox.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as exc:
        raise TransportError("atomic no-replace rename unavailable") from exc
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(directory_fd, os.fsencode(old), directory_fd, os.fsencode(new), 1) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def _sync_existing_publication(directory_fd: int, name: str, payload: bytes) -> None:
    """Close the rename-before-sync crash window before committing the ledger.

    A previous attempt can leave a visible final name after a crash or failed
    syncfs. Its visibility alone is not proof that the inbox directory entry is
    durable. Reopen the exact no-follow file, verify it, then sync both its
    inode and filesystem before changing the private ledger to ``sent``.
    """
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != len(payload):
            raise TransportError("unsafe existing inbox file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            if stream.read(len(payload) + 1) != payload:
                raise TransportError("inbox filename conflict")
        os.fsync(fd)
        _sync_filesystem(fd)
    finally:
        os.close(fd)


def _atomic(directory_fd: int, name: str, payload: bytes, mode: int = 0o600,
            *, create_only: bool = False, injection: str | None = None) -> None:
    def interrupt(stage: str) -> None:
        if injection == stage:
            raise RuntimeError(f"injected crash {stage}")

    temporary = f".task-a-{uuid.uuid4().hex}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=directory_fd)
    try:
        with os.fdopen(os.dup(fd), "wb") as stream:
            stream.write(payload)
            stream.flush()
            if create_only:
                interrupt("before_file_fsync")
            os.fsync(stream.fileno())
            if create_only:
                interrupt("after_file_fsync")
        if create_only:
            # Atomic no-clobber publication; a colliding request ID cannot
            # replace another envelope between the existence check and write.
            interrupt("before_publish_rename")
            _rename_noreplace(directory_fd, temporary, name)
            interrupt("after_publish_rename")
            interrupt("before_inbox_sync")
            _sync_filesystem(fd)
            interrupt("after_inbox_sync")
        else:
            os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
    finally:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


class LabInboxTransport:
    """One stable envelope per event key, with a write-ahead private ledger."""

    PROTECTED_ROOT = Path("/var/lib")
    PROTECTED_INBOX = Path("/var/lib/alfred-dev-gateway-lab/Alfred/projects/hermes-requests/inbox")
    PROTECTED_LEDGER = Path("/var/lib/alfred-photon-intake/ledger")

    @classmethod
    def protected_runtime(cls, *, secret: bytes, audit=None) -> "LabInboxTransport":
        return cls(cls.PROTECTED_ROOT, cls.PROTECTED_INBOX, cls.PROTECTED_LEDGER,
                   secret=secret, audit=audit, _protected=True)

    def __init__(self, root: Path, inbox: Path, ledger: Path, *, secret: bytes,
                 audit=None, _protected: bool = False):
        if _protected:
            if (root, inbox, ledger) != (self.PROTECTED_ROOT, self.PROTECTED_INBOX, self.PROTECTED_LEDGER):
                raise TransportError("protected transport paths are immutable")
            self.root = root
        else:
            self.root = isolated_root(root)
        self.inbox = inbox
        self.ledger = ledger
        if not secret or len(secret) < 16:
            raise TransportError("missing broker ledger key")
        self.secret = secret
        self.audit = audit or (lambda _code: None)
        for path in (inbox, ledger):
            if not path.resolve(strict=True).is_relative_to(self.root):
                raise TransportError("path outside isolated root")
            os.close(_open_dir(path, create_only=path == inbox))

    def _key(self, event_key: str) -> str:
        if not isinstance(event_key, str) or not event_key or len(event_key) > 512:
            raise TransportError("invalid event key")
        return hmac.new(self.secret, event_key.encode(), hashlib.sha256).hexdigest() + ".json"

    def submit(self, event_key: str, payload: bytes, *, fail_at: str | None = None) -> str:
        doc = inspect_envelope(payload)
        name = doc["request_id"] + ".json"
        ledger_name = self._key(event_key)
        ledger_fd = _open_dir(self.ledger)
        inbox_fd = _open_dir(self.inbox, create_only=True)
        try:
            lock_fd = os.open(".task-a-lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=ledger_fd)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                prior = _read_file(ledger_fd, ledger_name)
                digest = hashlib.sha256(payload).hexdigest()
                if prior is None:
                    if fail_at == "before_prepare":
                        raise RuntimeError("injected crash before_prepare")
                    record = {"request_id": doc["request_id"], "sha256": digest,
                              "bytes": base64.b64encode(payload).decode("ascii"), "state": "prepared"}
                    _atomic(ledger_fd, ledger_name, json.dumps(record, sort_keys=True).encode())
                    if fail_at == "after_prepare":
                        raise RuntimeError("injected crash after prepare")
                else:
                    try:
                        record = json.loads(prior)
                    except (ValueError, TypeError) as exc:
                        raise TransportError("corrupt ledger") from exc
                    if record.get("sha256") != digest or record.get("request_id") != doc["request_id"] or base64.b64decode(record.get("bytes", ""), validate=True) != payload:
                        raise TransportError("conflicting duplicate delivery")
                    if record.get("state") == "sent":
                        return doc["request_id"]
                    if record.get("state") != "prepared":
                        raise TransportError("unknown ledger state")
                retrying = prior is not None
                try:
                    existing = _read_file(inbox_fd, name)
                    if existing is None:
                        try:
                            _atomic(inbox_fd, name, payload, 0o640, create_only=True, injection=fail_at)
                        except FileExistsError:
                            _sync_existing_publication(inbox_fd, name, payload)
                    elif existing != payload:
                        raise TransportError("inbox filename conflict")
                    else:
                        _sync_existing_publication(inbox_fd, name, payload)
                    if fail_at == "after_publish":
                        raise RuntimeError("injected crash after publish")
                    if fail_at == "before_ledger_sent":
                        raise RuntimeError("injected crash before_ledger_sent")
                    record["state"] = "sent"
                    _atomic(ledger_fd, ledger_name, json.dumps(record, sort_keys=True).encode())
                    if fail_at == "after_ledger_sent":
                        raise RuntimeError("injected crash after_ledger_sent")
                except (OSError, TransportError, RuntimeError):
                    if retrying:
                        self.audit("inbox_retry_failed")
                    raise
                if retrying:
                    self.audit("inbox_recovered")
                return doc["request_id"]
            finally:
                os.close(lock_fd)
        finally:
            os.close(ledger_fd)
            os.close(inbox_fd)
