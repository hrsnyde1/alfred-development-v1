"""Protected development grants from Photon SDK observations.

The intake identity owns this store. Neither Hermes nor a developer worker may
write it. A fixture authority lives only in tests and is never accepted here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
import threading
import time
import uuid
from pathlib import Path

from .approval_transition import BOUND_FIELDS, stage_owner_transition
from .router import Denied

REF = re.compile(r"[0-9a-f]{32}\Z")
MAX_AGE = 300
PERMISSIONS = {"read_scoped", "write_scoped", "run_approved_check", "git_local_commit_if_granted"}


def _bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: dict | bytes) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else _bytes(value)).hexdigest()


def _phrase(request: dict) -> str:
    return f"Approve development {request['project']} {request['task_id']} {request['plan_sha256'][:12]}"


def _challenge_text(request: dict) -> str:
    return (f"Development execution approval\nProject/task: {request['project']} / {request['task_id']}\n"
            f"Plan SHA-256: {request['plan_sha256']}\nRepository: {request['repository']}\n"
            f"Scope: {', '.join(request['scope'])}\nSpecialists: {', '.join(request['specialists'])}\n"
            "This permits development edits in the specified worktree only; no merge or deployment.\n"
            f"Reply directly to this message within 5 minutes with: {_phrase(request)}")


def _event_time(value: object) -> float:
    if not isinstance(value, str):
        raise Denied("Photon event timestamp missing")
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Denied("Photon event timestamp invalid") from exc
    if stamp.tzinfo is None:
        raise Denied("Photon event timestamp lacks timezone")
    return stamp.timestamp()


def _protected(root: Path) -> None:
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise Denied("development grant store is not protected")


def _write_once(root: Path, name: str, value: dict) -> None:
    _protected(root)
    data = _bytes(value)
    fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read(root: Path, name: str) -> dict:
    _protected(root)
    fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 16384:
            raise Denied("untrusted development grant record")
        value = json.loads(stream.read())
    if type(value) is not dict:
        raise Denied("development evidence is not a JSON object")
    return value


def _verify_evidence(root: Path, reference: str, grant: dict, expected: dict) -> None:
    """A historical grant without these independent records is non-executable."""
    try:
        receipt = _read(root, f"challenge-{reference}.json")
        decision = _read(root, f"decision-{reference}.json")
        issuance = _read(root, f"issuance-{reference}.json")
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise Denied("development grant lacks trusted approval evidence") from exc
    request = {"schema": "alfred.development-approval-request/1",
               **{key: value for key, value in expected.items() if key != "schema"},
               "state": "pending_owner_decision"}
    if (receipt.get("schema") != "alfred.development-challenge/1"
            or receipt.get("reference") != reference or receipt.get("request") != request
            or not isinstance(receipt.get("owner_id"), str) or not receipt["owner_id"]
            or not isinstance(receipt.get("space_id"), str) or not receipt["space_id"]
            or not isinstance(receipt.get("message_id"), str) or not receipt["message_id"]
            or not isinstance(receipt.get("issued_at"), (int, float))
            or receipt.get("expires_at") != receipt["issued_at"] + MAX_AGE
            or receipt.get("challenge_text_sha256") != _digest(_challenge_text(request).encode())
            or receipt.get("phrase_sha256") != _digest(_phrase(request).encode())):
        raise Denied("challenge receipt does not bind canonical approval")
    checks = {"authenticated_sender": True, "same_dm": True, "fresh_event": True,
              "native_direct_reply": True, "not_forwarded": True,
              "within_challenge_lifetime": True, "exact_phrase": True,
              "single_use": True}
    if (decision.get("schema") != "alfred.development-owner-decision/1"
            or decision.get("reference") != reference
            or decision.get("challenge_sha256") != _digest(receipt)
            or decision.get("owner_event_id") != grant.get("owner_event_id")
            or decision.get("sender_id") != receipt["owner_id"]
            or decision.get("space_id") != receipt["space_id"]
            or decision.get("direction") != "inbound"
            or decision.get("native_reply_target") != receipt["message_id"]
            or decision.get("is_forward") is not False
            or decision.get("content_type") != "text"
            or decision.get("content_sha256") != receipt["phrase_sha256"]
            or decision.get("checks") != checks
            or grant.get("challenge_message_id") != receipt["message_id"]
            or not isinstance(decision.get("accepted_at"), (int, float))
            or not receipt["issued_at"] <= decision["accepted_at"] <= receipt["expires_at"]
            or not isinstance(decision.get("sdk_event_timestamp"), (int, float))
            or not receipt["issued_at"] - 5 <= decision["sdk_event_timestamp"] <= decision["accepted_at"] + 5):
        raise Denied("native owner-event evidence invalid")
    if (set(issuance) != {"schema", "reference", "grant_sha256", "challenge_sha256",
                         "decision_sha256", "bundle_sha256", "issued_at"}
            or issuance.get("schema") != "alfred.development-issuance/1"
            or issuance.get("reference") != reference
            or issuance.get("grant_sha256") != _digest(grant)
            or issuance.get("challenge_sha256") != _digest(receipt)
            or issuance.get("decision_sha256") != _digest(decision)
            or issuance.get("bundle_sha256") != _digest(_bytes(grant) + _bytes(receipt) + _bytes(decision))
            or issuance.get("issued_at") != decision["accepted_at"]):
        raise Denied("issuance digest does not match immutable evidence")


class ProtectedDevelopmentAuthority:
    def __init__(self, root: Path, *, clock=time.time, environment: str = "host"):
        if environment not in {"host", "staging"}:
            raise Denied("invalid grant environment")
        self.root = root
        self.clock = clock
        self.environment = environment
        self.activation_marker = Path("/opt/alfred-developer-v1/active")

    def verify(self, reference: str, expected: dict) -> dict:
        if self.environment == "host":
            try:
                marker = self.activation_marker.lstat()
            except OSError as exc:
                raise Denied("development execution is not host activated") from exc
            if (not stat.S_ISREG(marker.st_mode) or marker.st_uid != 0
                    or stat.S_IMODE(marker.st_mode) != 0o644):
                raise Denied("development activation marker invalid")
        if not isinstance(reference, str) or not REF.fullmatch(reference):
            raise Denied("invalid development grant reference")
        try:
            grant = _read(self.root, f"grant-{reference}.json")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise Denied("development grant unavailable") from exc
        if (grant.get("reference") != reference or grant.get("issuer") != "trusted_owner_authority"
                or grant.get("state") != "approved" or grant.get("source") != "photon_native_owner_reply"
                or grant.get("environment") != self.environment
                or set(grant.get("permissions", [])) != PERMISSIONS
                or any(grant.get(k) != v for k, v in expected.items())):
            raise Denied("development grant binding mismatch")
        if not isinstance(grant.get("expires_at"), (int, float)) or self.clock() >= grant["expires_at"]:
            raise Denied("development grant expired")
        if (self.root / f"revoke-{reference}").exists():
            raise Denied("development grant revoked")
        _verify_evidence(self.root, reference, grant, expected)
        return grant

    def claim(self, reference: str, expected: dict, *, run_sha256: str) -> dict:
        """Durably consume one grant before any worktree or model operation."""
        grant = self.verify(reference, expected)
        if not isinstance(run_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", run_sha256):
            raise Denied("invalid execution request digest")
        record = {"schema": "alfred.development-execution-claim/1",
                  "reference": reference, "project": grant["project"],
                  "task_id": grant["task_id"], "grant_sha256": _digest(grant),
                  "run_sha256": run_sha256, "claimed_at": self.clock(),
                  "status_if_no_result": "uncertain"}
        try:
            _write_once(self.root, f"execution-{reference}.json", record)
        except FileExistsError as exc:
            raise Denied("development grant already consumed") from exc
        return record

    def finish(self, reference: str, *, status: str) -> None:
        if (not isinstance(reference, str) or not REF.fullmatch(reference)
                or status not in {"completed", "failed", "uncertain"}):
            raise Denied("invalid execution terminal status")
        claim = _read(self.root, f"execution-{reference}.json")
        try:
            _write_once(self.root, f"execution-result-{reference}.json", {
                "schema": "alfred.development-execution-result/1",
                "reference": reference, "claim_sha256": _digest(claim),
                "status": status, "recorded_at": self.clock()})
        except FileExistsError as exc:
            raise Denied("development execution outcome already recorded") from exc


class _ObservedDecision:
    def __init__(self, event: dict, owner: str):
        self.event, self.owner = event, owner

    def verify(self, reference: str, expected: dict) -> dict:
        if reference != self.event["messageId"]:
            raise Denied("owner event mismatch")
        return {**expected, "owner": self.owner, "decision": "approve_development",
                "source": "independent_owner_channel", "reference": reference}


class DevelopmentGrantIssuer:
    """Runs inside the existing trusted intake process, never in a model process."""

    def __init__(self, root: Path, *, owner_sender_id: str, preview_sender,
                 sidecar_uid: int, clock=time.time, admin_uid: int = 0,
                 environment: str = "host"):
        _protected(root)
        self.root, self.owner, self.send = root, owner_sender_id, preview_sender
        if environment not in {"host", "staging"}:
            raise Denied("invalid grant environment")
        if sidecar_uid == admin_uid:
            raise Denied("Photon and administrator identities must differ")
        self.clock, self.admin_uid, self.sidecar_uid = clock, admin_uid, sidecar_uid
        self.environment = environment
        self._lock = threading.Lock()

    def stage(self, request: dict, *, space_id: str, peer_uid: int) -> dict:
        if peer_uid != self.admin_uid or not isinstance(space_id, str) or not space_id:
            raise Denied("development approval staging requires protected administrator")
        if (request.get("schema") != "alfred.development-approval-request/1"
                or request.get("state") != "pending_owner_decision"
                or not all(k in request for k in BOUND_FIELDS if k != "schema")):
            raise Denied("invalid development approval request")
        # This method is called only after the Gateway adapter and canonical
        # binding recompute the request; raw client-supplied requests are refused
        # by the intake extension.
        with self._lock:
            for path in self.root.glob("pending-*.json"):
                prior = _read(self.root, path.name)
                if self.clock() - prior["created_at"] > MAX_AGE:
                    old_reference = path.stem.removeprefix("pending-")
                    receipt = _read(self.root, f"challenge-{old_reference}.json")
                    try:
                        _write_once(self.root, f"expired-{old_reference}.json", {
                            "schema": "alfred.development-challenge-expiry/1",
                            "reference": old_reference,
                            "challenge_sha256": _digest(receipt),
                            "expired_at": self.clock()})
                    except FileExistsError:
                        pass
                    path.unlink()
            if any(self.root.glob("pending-*.json")):
                raise Denied("another development approval is pending")
            for path in self.root.glob("grant-*.json"):
                old = _read(self.root, path.name)
                old_reference = path.stem.removeprefix("grant-")
                if (old.get("project") == request["project"]
                        and old.get("task_id") == request["task_id"]
                        and not (self.root / f"revoke-{old_reference}").exists()):
                    raise Denied("existing task grant must be revoked before restaging")
            challenge = uuid.uuid4().hex
            phrase = _phrase(request)
            message = _challenge_text(request)
            if len(message) > 4000:
                raise Denied("development approval challenge too large")
            message_id = self.send(space_id, message)
            if not isinstance(message_id, str) or not message_id:
                raise Denied("approval challenge delivery unverified")
            issued_at = self.clock()
            _write_once(self.root, f"challenge-{challenge}.json", {
                "schema": "alfred.development-challenge/1", "reference": challenge,
                "request": request, "owner_id": self.owner, "space_id": space_id,
                "message_id": message_id, "issued_at": issued_at,
                "expires_at": issued_at + MAX_AGE,
                "challenge_text_sha256": _digest(message.encode()),
                "phrase_sha256": _digest(phrase.encode())})
            _write_once(self.root, f"pending-{challenge}.json", {
                "request": request, "space_id": space_id, "message_id": message_id,
                "phrase": phrase, "created_at": issued_at,
            })
            return {"state": "awaiting_native_owner_reply", "challenge": challenge,
                    "message_id": message_id}

    def observe(self, event: object, *, peer_uid: int) -> dict:
        if peer_uid != self.sidecar_uid or type(event) is not dict:
            raise Denied("untrusted Photon observation")
        target = event.get("nativeReplyTargetGuid")
        if not isinstance(target, str):
            return {"state": "not_development_approval"}
        with self._lock:
            matches = []
            for path in self.root.glob("pending-*.json"):
                pending = _read(self.root, path.name)
                if pending["message_id"] == target:
                    matches.append((path, pending))
            if not matches:
                for path in self.root.glob("challenge-*.json"):
                    receipt = _read(self.root, path.name)
                    reference = path.stem.removeprefix("challenge-")
                    if (receipt.get("message_id") == target
                            and (self.root / f"decision-{reference}.json").exists()):
                        raise Denied("development challenge already consumed")
                return {"state": "not_development_approval"}
            if len(matches) != 1:
                raise Denied("ambiguous development approval target")
            path, pending = matches[0]
            reference = path.stem.removeprefix("pending-")
            receipt = _read(self.root, f"challenge-{reference}.json")
            if (receipt.get("request") != pending["request"]
                    or receipt.get("message_id") != pending["message_id"]
                    or receipt.get("space_id") != pending["space_id"]
                    or receipt.get("phrase_sha256") != _digest(pending["phrase"].encode())
                    or receipt.get("issued_at") != pending["created_at"]):
                raise Denied("challenge receipt and pending state differ")
            content = event.get("content")
            now = self.clock()
            timestamp = _event_time(event.get("timestamp"))
            if (event.get("direction") != "inbound" or event.get("sender") != {"id": self.owner}
                    or event.get("space") != {"id": pending["space_id"], "type": "dm"}
                    or event.get("nativeIsForward") is not False
                    or not isinstance(event.get("messageId"), str)
                    or event["messageId"] == target
                    or not isinstance(content, dict) or content.get("type") != "text"
                    or content.get("text") != pending["phrase"]
                    or not receipt["issued_at"] <= now <= receipt["expires_at"]
                    or not receipt["issued_at"] - 5 <= timestamp <= now + 5):
                raise Denied("development owner reply unverified")
            if any(_read(self.root, record.name).get("owner_event_id") == event["messageId"]
                   for pattern in ("decision-*.json", "publication-decision-*.json")
                   for record in self.root.glob(pattern)):
                raise Denied("owner event already used")
            checks = {"authenticated_sender": True, "same_dm": True,
                      "fresh_event": True, "native_direct_reply": True,
                      "not_forwarded": True, "within_challenge_lifetime": True,
                      "exact_phrase": True, "single_use": True}
            decision = {"schema": "alfred.development-owner-decision/1",
                        "reference": reference, "challenge_sha256": _digest(receipt),
                        "owner_event_id": event["messageId"], "sender_id": self.owner,
                        "space_id": pending["space_id"], "direction": "inbound",
                        "native_reply_target": target, "is_forward": False,
                        "content_type": "text",
                        "content_sha256": _digest(content["text"].encode()),
                        "sdk_event_timestamp": timestamp, "accepted_at": now,
                        "peer_uid": peer_uid, "checks": checks}
            # The decision record consumes this challenge before grant creation.
            # A crash from here onward cannot authorize a second reply.
            try:
                _write_once(self.root, f"decision-{reference}.json", decision)
            except FileExistsError as exc:
                raise Denied("development challenge already consumed") from exc
            existing = self.root / f"grant-{reference}.json"
            if existing.exists():
                raise Denied("development approval replay conflict")
            grant = stage_owner_transition(
                pending["request"], decision_reference=event["messageId"],
                expected_owner=self.owner, verifier=_ObservedDecision(event, self.owner),
                grant_reference=reference,
            )
            grant.update({"source": "photon_native_owner_reply", "owner_event_id": event["messageId"],
                          "challenge_message_id": target, "expires_at": now + 86400,
                          "environment": self.environment,
                          "permissions": sorted(PERMISSIONS)})
            _write_once(self.root, f"issuance-{reference}.json", {
                "schema": "alfred.development-issuance/1", "reference": reference,
                "grant_sha256": _digest(grant),
                "challenge_sha256": _digest(receipt),
                "decision_sha256": _digest(decision),
                "bundle_sha256": _digest(_bytes(grant) + _bytes(receipt) + _bytes(decision)),
                "issued_at": now})
            _write_once(self.root, f"grant-{reference}.json", grant)
            path.unlink()
            return {"state": "development_approved", "reference": reference}

    def revoke(self, *, project: str, task_id: str, peer_uid: int) -> dict:
        """Root-staged revocation, including a legacy grant with no evidence."""
        if peer_uid != self.admin_uid or not project or not task_id:
            raise Denied("development revocation requires protected administrator")
        with self._lock:
            matches = []
            for path in self.root.glob("grant-*.json"):
                grant = _read(self.root, path.name)
                reference = path.stem.removeprefix("grant-")
                if (grant.get("project") == project and grant.get("task_id") == task_id
                        and not (self.root / f"revoke-{reference}").exists()):
                    matches.append(reference)
            if len(matches) != 1:
                raise Denied("expected one active task grant to revoke")
            _write_once(self.root, f"revoke-{matches[0]}", {
                "schema": "alfred.development-revocation/1", "project": project,
                "task_id": task_id, "revoked_at": self.clock()})
            return {"state": "development_grant_revoked", "project": project,
                    "task_id": task_id}

