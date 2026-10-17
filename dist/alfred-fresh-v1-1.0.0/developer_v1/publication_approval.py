"""Exact-plan Draft PR approval through the existing trusted Intake observation."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from .owner_grants import MAX_AGE, _bytes, _digest, _event_time, _read, _write_once
from .router import Denied

PLAN_SHA = "511fa533fd9dc5bb41d51bff1baa21b28a54b8b0b670e5b3f0f602a78d38b903"
BOUND = {
    "project": "dev-v1-accept",
    "task_id": "T-0002",
    "destination": "hrsnyde1/alfred-dev-v1-acceptance",
    "base_branch": "main",
    "publication_branch": "alfred/dev-v1-accept/T-0002-89ba188f8a2f",
    "final_revision": "89ba188f8a2f801d433a30c9c21363efb3e1043d",
}
REF = re.compile(r"[0-9a-f]{32}\Z")


def _phrase(reference: str, bound: dict | None = None) -> str:
    bound = BOUND if bound is None else bound
    return f"Approve GitHub Draft PR {bound['project']} {bound['task_id']} {reference}"


def _challenge_text(reference: str, bound: dict | None = None, plan_sha: str | None = None) -> str:
    bound = BOUND if bound is None else bound
    plan_sha = PLAN_SHA if plan_sha is None else plan_sha
    return ("GitHub Draft PR publication approval\n"
            f"Project/task: {bound['project']} / {bound['task_id']}\n"
            f"Repository: {bound['destination']}\nBase: {bound['base_branch']}\n"
            f"Publication branch: {bound['publication_branch']}\n"
            f"Final revision: {bound['final_revision']}\nPublication plan SHA-256: {plan_sha}\n"
            "This permits one Draft PR only; it does not permit merge or deployment.\n"
            f"Reply directly to this message within 5 minutes with: {_phrase(reference, bound)}")


def _validate_plan(raw: bytes) -> None:
    if type(raw) is not bytes or len(raw) > 16384 or _digest(raw) != PLAN_SHA:
        raise Denied("publication plan digest mismatch")
    try:
        plan = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Denied("publication plan invalid") from exc
    if (type(plan) is not dict or plan.get("schema") != "alfred.draft-pr-plan/1"
            or plan.get("status") != "READY_FOR_OWNER_AUTHORIZATION"
            or any(plan.get(key) != value for key, value in BOUND.items())):
        raise Denied("publication plan binding mismatch")


def _check_receipt(receipt: dict, reference: str, bound: dict | None = None, plan_sha: str | None = None) -> None:
    bound = BOUND if bound is None else bound
    plan_sha = PLAN_SHA if plan_sha is None else plan_sha
    if (set(receipt) != {"schema", "reference", "plan_sha256", *BOUND,
                         "owner_id", "space_id", "message_id", "issued_at",
                         "expires_at", "challenge_text_sha256", "phrase_sha256"}
            or receipt.get("schema") != "alfred.publication-challenge/1"
            or receipt.get("reference") != reference
            or receipt.get("plan_sha256") != plan_sha
            or any(receipt.get(key) != value for key, value in bound.items())
            or not isinstance(receipt.get("owner_id"), str) or not receipt["owner_id"]
            or not isinstance(receipt.get("space_id"), str) or not receipt["space_id"]
            or not isinstance(receipt.get("message_id"), str) or not receipt["message_id"]
            or type(receipt.get("issued_at")) not in (int, float)
            or receipt.get("expires_at") != receipt["issued_at"] + MAX_AGE
            or receipt.get("challenge_text_sha256") != _digest(_challenge_text(reference, bound, plan_sha).encode())
            or receipt.get("phrase_sha256") != _digest(_phrase(reference, bound).encode())):
        raise Denied("publication challenge receipt invalid")


def _check_decision(receipt: dict, decision: dict, reference: str) -> None:
    checks = {"authenticated_sender": True, "same_dm": True, "fresh_event": True,
              "native_direct_reply": True, "not_forwarded": True,
              "within_challenge_lifetime": True, "exact_phrase": True,
              "single_use": True}
    if (set(decision) != {"schema", "reference", "challenge_sha256", "owner_event_id",
                          "sender_id", "space_id", "direction", "native_reply_target",
                          "is_forward", "content_type", "content_sha256",
                          "sdk_event_timestamp", "accepted_at", "peer_uid", "checks"}
            or decision.get("schema") != "alfred.publication-owner-decision/1"
            or decision.get("reference") != reference
            or decision.get("challenge_sha256") != _digest(receipt)
            or type(decision.get("owner_event_id")) is not str
            or not decision["owner_event_id"]
            or decision["owner_event_id"] == receipt["message_id"]
            or decision.get("sender_id") != receipt["owner_id"]
            or decision.get("space_id") != receipt["space_id"]
            or decision.get("direction") != "inbound"
            or decision.get("native_reply_target") != receipt["message_id"]
            or decision.get("is_forward") is not False
            or decision.get("content_type") != "text"
            or decision.get("content_sha256") != receipt["phrase_sha256"]
            or decision.get("checks") != checks
            or type(decision.get("accepted_at")) not in (int, float)
            or not receipt["issued_at"] <= decision["accepted_at"] <= receipt["expires_at"]
            or type(decision.get("sdk_event_timestamp")) not in (int, float)
            or not receipt["issued_at"] <= decision["sdk_event_timestamp"] <= decision["accepted_at"] + 5):
        raise Denied("publication owner decision invalid")


class PublicationApprovalIssuer:
    def __init__(self, root: Path, *, owner_sender_id: str, preview_sender,
                 sidecar_uid: int, clock=time.time, admin_uid: int = 0, plan_verifier=None):
        # The development issuer already validates this same private Intake store.
        from .owner_grants import _protected
        _protected(root)
        if not owner_sender_id or sidecar_uid == admin_uid:
            raise Denied("publication approval identities invalid")
        self.root, self.owner, self.send = root, owner_sender_id, preview_sender
        self.sidecar_uid, self.admin_uid, self.clock = sidecar_uid, admin_uid, clock
        self._lock = threading.Lock()
        self.plan_verifier = plan_verifier

    def _context(self, raw: bytes) -> tuple[dict, str]:
        if self.plan_verifier is None:
            _validate_plan(raw)
            return dict(BOUND), PLAN_SHA
        if type(raw) is not bytes or len(raw) > 16384:
            raise Denied("invalid publication plan bytes")
        plan = json.loads(raw)
        if type(plan) is not dict or raw != self.plan_verifier(plan.get("project"), plan.get("task_id")):
            raise Denied("publication plan differs from protected prepared evidence")
        from jsonschema import ValidationError, validate
        schema = Path(__file__).with_name("schemas") / "publication-plan.schema.json"
        try:
            validate(plan, json.loads(schema.read_bytes()))
        except ValidationError as exc:
            raise Denied("prepared publication schema invalid") from exc
        return {key: plan[key] for key in BOUND}, _digest(raw)

    def _receipt_context(self, receipt: dict) -> tuple[dict, str]:
        if self.plan_verifier is None or (receipt.get("plan_sha256") == PLAN_SHA and
                all(receipt.get(k) == v for k, v in BOUND.items())):
            return dict(BOUND), PLAN_SHA
        try:
            raw = self.plan_verifier(receipt.get("project"), receipt.get("task_id"))
        except (OSError, ValueError) as exc:
            raise Denied("protected publication evidence unavailable") from exc
        return self._context(raw)

    def stage(self, plan_raw: bytes, *, space_id: str, peer_uid: int) -> dict:
        if peer_uid != self.admin_uid or type(space_id) is not str or not space_id:
            raise Denied("publication staging requires administrator and DM")
        bound, plan_sha = self._context(plan_raw)
        with self._lock:
            for path in self.root.glob("publication-pending-*.json"):
                pending = _read(self.root, path.name)
                reference = path.stem.removeprefix("publication-pending-")
                if self.clock() <= pending["created_at"] + MAX_AGE:
                    raise Denied("publication challenge already pending")
                receipt = _read(self.root, f"publication-challenge-{reference}.json")
                _write_once(self.root, f"publication-expired-{reference}.json", {
                    "schema": "alfred.publication-challenge-expiry/1", "reference": reference,
                    "challenge_sha256": _digest(receipt), "expired_at": self.clock()})
                path.unlink()
            for decided in self.root.glob("publication-decision-*.json"):
                old_ref = decided.stem.removeprefix("publication-decision-")
                previous = _read(self.root, f"publication-challenge-{old_ref}.json")
                if previous.get("plan_sha256") == plan_sha:
                    raise Denied("publication decision already exists for this plan")
            reference = uuid.uuid4().hex
            message = _challenge_text(reference, bound, plan_sha)
            message_id = self.send(space_id, message)
            if type(message_id) is not str or not message_id:
                raise Denied("publication challenge delivery unverified")
            now = self.clock()
            receipt = {"schema": "alfred.publication-challenge/1", "reference": reference,
                       "plan_sha256": plan_sha, **bound, "owner_id": self.owner,
                       "space_id": space_id, "message_id": message_id,
                       "issued_at": now, "expires_at": now + MAX_AGE,
                       "challenge_text_sha256": _digest(message.encode()),
                       "phrase_sha256": _digest(_phrase(reference, bound).encode())}
            _write_once(self.root, f"publication-challenge-{reference}.json", receipt)
            _write_once(self.root, f"publication-pending-{reference}.json", {
                "message_id": message_id, "space_id": space_id,
                "created_at": now, "challenge_sha256": _digest(receipt)})
            return {"state": "awaiting_native_publication_reply", "challenge": reference,
                    "message_id": message_id}

    def observe(self, event: object, *, peer_uid: int) -> dict:
        if peer_uid != self.sidecar_uid or type(event) is not dict:
            raise Denied("untrusted Photon observation")
        target = event.get("nativeReplyTargetGuid")
        if type(target) is not str or not target:
            return {"state": "not_publication_approval"}
        with self._lock:
            matches = []
            for path in self.root.glob("publication-pending-*.json"):
                pending = _read(self.root, path.name)
                if pending["message_id"] == target:
                    matches.append((path, pending))
            if not matches:
                for path in self.root.glob("publication-challenge-*.json"):
                    receipt = _read(self.root, path.name)
                    if receipt.get("message_id") == target:
                        raise Denied("publication challenge already consumed or expired")
                return {"state": "not_publication_approval"}
            if len(matches) != 1:
                raise Denied("ambiguous publication challenge")
            path, pending = matches[0]
            reference = path.stem.removeprefix("publication-pending-")
            receipt = _read(self.root, f"publication-challenge-{reference}.json")
            bound, plan_sha = self._receipt_context(receipt)
            _check_receipt(receipt, reference, bound, plan_sha)
            if (pending != {"message_id": target, "space_id": receipt["space_id"],
                            "created_at": receipt["issued_at"],
                            "challenge_sha256": _digest(receipt)}):
                raise Denied("publication pending state mismatch")
            now = self.clock()
            timestamp = _event_time(event.get("timestamp"))
            content = event.get("content")
            event_id = event.get("messageId")
            if (event.get("direction") != "inbound"
                    or event.get("sender") != {"id": self.owner}
                    or event.get("space") != {"id": receipt["space_id"], "type": "dm"}
                    or event.get("nativeIsForward") is not False
                    or type(event_id) is not str or not 1 <= len(event_id) <= 200
                    or event_id == target
                    or type(content) is not dict or content.get("type") != "text"
                    or content.get("text") != _phrase(reference, bound)
                    or not receipt["issued_at"] <= now <= receipt["expires_at"]
                    or not receipt["issued_at"] <= timestamp <= now + 5):
                raise Denied("publication owner reply unverified")
            for pattern in ("decision-*.json", "publication-decision-*.json"):
                if any(_read(self.root, record.name).get("owner_event_id") == event_id
                       for record in self.root.glob(pattern)):
                    raise Denied("owner event already used")
            decision = {"schema": "alfred.publication-owner-decision/1",
                        "reference": reference, "challenge_sha256": _digest(receipt),
                        "owner_event_id": event_id, "sender_id": self.owner,
                        "space_id": receipt["space_id"], "direction": "inbound",
                        "native_reply_target": target, "is_forward": False,
                        "content_type": "text", "content_sha256": _digest(content["text"].encode()),
                        "sdk_event_timestamp": timestamp, "accepted_at": now,
                        "peer_uid": peer_uid,
                        "checks": {"authenticated_sender": True, "same_dm": True,
                                   "fresh_event": True, "native_direct_reply": True,
                                   "not_forwarded": True, "within_challenge_lifetime": True,
                                   "exact_phrase": True, "single_use": True}}
            _write_once(self.root, f"publication-decision-{reference}.json", decision)
            _write_once(self.root, f"publication-issuance-{reference}.json", {
                "schema": "alfred.publication-decision-issuance/1",
                "reference": reference, "challenge_sha256": _digest(receipt),
                "decision_sha256": _digest(decision),
                "bundle_sha256": _digest(_bytes(receipt) + _bytes(decision)),
                "issued_at": now})
            path.unlink()
            return {"state": "publication_approved", "reference": reference}

    def prepare(self, reference: str, *, peer_uid: int) -> dict:
        """Return a record for root installation only after evidence revalidation."""
        if peer_uid != self.admin_uid or type(reference) is not str or not REF.fullmatch(reference):
            raise Denied("publication preparation requires administrator and reference")
        receipt = _read(self.root, f"publication-challenge-{reference}.json")
        decision = _read(self.root, f"publication-decision-{reference}.json")
        issuance = _read(self.root, f"publication-issuance-{reference}.json")
        bound, plan_sha = self._receipt_context(receipt)
        _check_receipt(receipt, reference, bound, plan_sha)
        _check_decision(receipt, decision, reference)
        if receipt["owner_id"] != self.owner or decision["peer_uid"] != self.sidecar_uid:
            raise Denied("publication decision identity mismatch")
        if (issuance != {"schema": "alfred.publication-decision-issuance/1",
                         "reference": reference, "challenge_sha256": _digest(receipt),
                         "decision_sha256": _digest(decision),
                         "bundle_sha256": _digest(_bytes(receipt) + _bytes(decision)),
                         "issued_at": decision["accepted_at"]}):
            raise Denied("publication decision evidence digest mismatch")
        if (self.root / f"publication-pending-{reference}.json").exists():
            raise Denied("publication challenge still pending")
        if (self.root / f"publication-expired-{reference}.json").exists():
            raise Denied("publication challenge expired")
        for pattern in ("decision-*.json", "publication-decision-*.json"):
            if sum(_read(self.root, path.name).get("owner_event_id") == decision["owner_event_id"]
                   for path in self.root.glob(pattern)) != (1 if pattern.startswith("publication-") else 0):
                raise Denied("owner event reused")
        return {"schema": "alfred.github-draft-pr-authorization/1", "decision": "approved",
                **bound, "publication_plan_sha256": plan_sha,
                "owner_event_id": decision["owner_event_id"], "purpose": "one_github_draft_pr"}
