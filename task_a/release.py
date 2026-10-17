"""Transactional Task A installer simulator; refuses any non-temporary root.

This tests release mechanics before a protected installer receives human review.
It does not create accounts, set ACLs, install units or touch production.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import uuid

from .transport import isolated_root


class ReleaseError(ValueError):
    pass


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _safe_relative(name: str) -> Path:
    value = PurePosixPath(name)
    if value.is_absolute() or not value.parts or any(p in (".", "..") for p in value.parts):
        raise ReleaseError("unsafe relative target")
    return Path(*value.parts)


def _read_regular(path: Path) -> bytes | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ReleaseError("non-regular or linked target")
    return path.read_bytes()


def _atomic(path: Path, data: bytes, mode: int = 0o600) -> None:
    temporary = path.parent / (".task-a-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


class StagingTransaction:
    def __init__(self, root: Path, payload: Path, manifest: dict):
        self.root = isolated_root(root)
        self.payload = isolated_root(payload)
        self.manifest = manifest
        self.transactions = self.root / ".task-a-transactions"

    def _target(self, name: str) -> Path:
        destination = self.root / _safe_relative(name)
        for component in (destination, *destination.parents):
            if component == self.root:
                break
            if component.is_symlink():
                raise ReleaseError("target path symlink")
        if not destination.parent.is_dir() or not destination.parent.resolve().is_relative_to(self.root):
            raise ReleaseError("missing protected target parent")
        return destination

    def _files(self) -> dict[str, dict]:
        files = self.manifest.get("files")
        if self.manifest.get("schema") != "task-a-staging-release/1" or not isinstance(files, dict) or not files:
            raise ReleaseError("invalid release manifest")
        for name, spec in files.items():
            _safe_relative(name)
            if not isinstance(spec, dict) or set(spec) != {"payload_sha256", "baseline_sha256", "mode", "baseline_mode"}:
                raise ReleaseError("invalid file specification")
            if spec["mode"] not in (0o600, 0o640, 0o644, 0o750):
                raise ReleaseError("unsafe file mode")
            if spec["baseline_mode"] is not None and spec["baseline_mode"] not in (0o600, 0o640, 0o644, 0o750):
                raise ReleaseError("unsafe baseline mode")
        return files

    def verify(self) -> None:
        if self.transactions.exists():
            for transaction in self.transactions.iterdir():
                if not transaction.is_dir():
                    raise ReleaseError("unexpected transaction entry")
                state_path = transaction / "state.json"
                if not state_path.is_file() or json.loads(state_path.read_text()).get("status") not in ("committed", "rolled_back"):
                    raise ReleaseError("interrupted transaction requires recovery")
        for name, spec in self._files().items():
            relative = _safe_relative(name)
            destination = self._target(name)
            source = self.payload / relative
            if not source.resolve(strict=True).is_relative_to(self.payload):
                raise ReleaseError("payload path escape")
            if sha256(_read_regular(source) or b"") != spec["payload_sha256"]:
                raise ReleaseError("payload checksum mismatch")
            existing = _read_regular(destination)
            digest = sha256(existing) if existing is not None else None
            if digest != spec["baseline_sha256"]:
                raise ReleaseError("unexpected baseline modification")
            mode = stat.S_IMODE(destination.stat().st_mode) if existing is not None else None
            if mode != spec["baseline_mode"]:
                raise ReleaseError("unexpected baseline permissions")

    def install(self, *, fail_at: str | None = None) -> Path:
        self.verify()
        self.transactions.mkdir(mode=0o700, exist_ok=True)
        transaction = self.transactions / uuid.uuid4().hex
        transaction.mkdir(mode=0o700)
        backup = transaction / "backup"
        backup.mkdir(mode=0o700)
        state = {"schema": "task-a-staging-transaction/1", "status": "preparing", "files": self._files()}
        _atomic(transaction / "state.json", json.dumps(state, sort_keys=True).encode())
        if fail_at == "after_transaction":
            raise RuntimeError("injected interruption before backup")
        for index, (name, spec) in enumerate(state["files"].items()):
            old = _read_regular(self._target(name))
            if old is not None:
                target = backup / f"{index}.bak"
                _atomic(target, old)
                if sha256(target.read_bytes()) != spec["baseline_sha256"]:
                    raise ReleaseError("backup verification failed")
            if fail_at == f"after_backup_file_{index}":
                raise RuntimeError("injected interruption during backup")
        state["status"] = "backed_up"
        _atomic(transaction / "state.json", json.dumps(state, sort_keys=True).encode())
        if fail_at == "after_backup":
            raise RuntimeError("injected interruption after backup")
        state["status"] = "installing"
        _atomic(transaction / "state.json", json.dumps(state, sort_keys=True).encode())
        for index, (name, spec) in enumerate(state["files"].items()):
            content = (self.payload / _safe_relative(name)).read_bytes()
            _atomic(self._target(name), content, spec["mode"])
            if fail_at == f"after_file_{index}":
                raise RuntimeError("injected interruption after replacement")
        state["status"] = "committed"
        _atomic(transaction / "state.json", json.dumps(state, sort_keys=True).encode())
        return transaction

    def _restore(self, transaction: Path, *, require_payload: bool) -> None:
        if not transaction.resolve(strict=True).is_relative_to(self.transactions):
            raise ReleaseError("transaction path escape")
        if (transaction / "backup").is_symlink() or not (transaction / "backup").is_dir():
            raise ReleaseError("unsafe backup directory")
        state = json.loads((transaction / "state.json").read_text())
        if state.get("schema") != "task-a-staging-transaction/1" or state.get("files") != self._files():
            raise ReleaseError("transaction manifest mismatch")
        if require_payload and state["status"] != "committed":
            raise ReleaseError("only committed transactions can roll back")
        if not require_payload and state["status"] not in ("preparing", "backed_up", "installing"):
            raise ReleaseError("not an interrupted transaction")
        if state["status"] == "preparing":
            # No target replacement starts until all backups are verified.
            for name, spec in state["files"].items():
                current = _read_regular(self._target(name))
                if (sha256(current) if current is not None else None) != spec["baseline_sha256"]:
                    raise ReleaseError("target changed during backup preparation")
            state["status"] = "rolled_back"
            _atomic(transaction / "state.json", json.dumps(state, sort_keys=True).encode())
            return
        # Verify every backup and all observed target bytes before changing any target.
        for index, (name, spec) in enumerate(state["files"].items()):
            backup = _read_regular(transaction / "backup" / f"{index}.bak")
            if (sha256(backup) if backup is not None else None) != spec["baseline_sha256"]:
                raise ReleaseError("backup checksum mismatch")
            current = _read_regular(self._target(name))
            digest = sha256(current) if current is not None else None
            expected = {spec["payload_sha256"]} if require_payload else {spec["payload_sha256"], spec["baseline_sha256"]}
            if spec["baseline_sha256"] is None and not require_payload:
                expected.add(None)
            if digest not in expected:
                raise ReleaseError("target changed since transaction")
        for index, (name, spec) in enumerate(state["files"].items()):
            destination = self._target(name)
            backup = transaction / "backup" / f"{index}.bak"
            if spec["baseline_sha256"] is None:
                destination.unlink(missing_ok=True)
            else:
                _atomic(destination, backup.read_bytes(), spec["baseline_mode"])
        state["status"] = "rolled_back"
        _atomic(transaction / "state.json", json.dumps(state, sort_keys=True).encode())

    def recover(self, transaction: Path) -> None:
        if not transaction.resolve(strict=True).is_relative_to(self.transactions):
            raise ReleaseError("transaction path escape")
        if not (transaction / "state.json").exists():
            # Transaction directory was created but the first state write was
            # interrupted. No backup or replacement can have started.
            for name, spec in self._files().items():
                current = _read_regular(self._target(name))
                if (sha256(current) if current is not None else None) != spec["baseline_sha256"]:
                    raise ReleaseError("target changed before transaction record")
            state = {"schema": "task-a-staging-transaction/1", "status": "rolled_back", "files": self._files()}
            _atomic(transaction / "state.json", json.dumps(state, sort_keys=True).encode())
            return
        self._restore(transaction, require_payload=False)

    def rollback(self, transaction: Path) -> None:
        self._restore(transaction, require_payload=True)
