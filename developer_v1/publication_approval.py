"""Exact-plan Draft PR approval through the existing trusted Intake observation."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from .owner_grants import (MAX_AGE, _bytes, _digest, _event_time, _read, _write_once,
                           load_delegation_policy, merge_delegation_permits,
                           publication_delegation_permits)
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
DELEGATED = "alfred.publication-delegation/1"
DELEGATED_DECISION = "alfred.publication-delegated-decision/1"
MERGE_DELEGATED = "alfred.merge-delegated-decision/1"


def _decided_plan(root: Path, decision_path: Path) -> str | None:
    """The plan a publication decision approved: an iMessage or delegated receipt, or an
    Alfred OS passkey offer (owner_approval.py)."""
    reference = decision_path.stem.removeprefix("publication-decision-")
    if (root / f"owner-offer-{reference}.json").exists():
        from .owner_approval import offer_plan_sha
        return offer_plan_sha(root, reference)
    return _read(root, f"publication-challenge-{reference}.json").get("plan_sha256")


def _phrase(reference: str, bound: dict | None = None) -> str:
    bound = BOUND if bound is None else bound
    return f"Approve GitHub Draft PR {bound['project']} {bound['task_id']} {reference}"


NOTE_LINE = 200
NOTES_TOTAL = 1500


def _notes(plan: dict) -> tuple[tuple[str, str], ...]:
    """The sealed plan's informational Reviewer findings, as (requirement, detail)."""
    return tuple((f["requirement"], f["detail"]) for f in plan.get("review_findings", []))


def _notes_text(notes: tuple[tuple[str, str], ...]) -> str:
    if not notes:
        return ""
    lines, used = [], 0
    for i, (requirement, detail) in enumerate(notes):
        line = " ".join(f"- {requirement}: {detail}".split())
        line = line if len(line) <= NOTE_LINE else line[:NOTE_LINE - 1] + "…"
        if used + len(line) > NOTES_TOTAL:
            lines.append(f"- … {len(notes) - i} more in the sealed publication plan")
            break
        lines.append(line)
        used += len(line)
    return "Reviewer notes (informational, non-blocking):\n" + "\n".join(lines) + "\n"


# From handoff.11 the owner (the only person on this Photon line) approves in plain
# language: reply "yes" in the approval message's own thread within 12 hours. The
# native in-thread reply target, the owner's number, the same DM, no forwarding and
# single use bind the exact sealed plan; the technical binding stays in the receipt.
# Receipts issued earlier keep their 5-minute exact-phrase wording and still verify.
SIMPLE_MAX_AGE = 12 * 3600
SIMPLE_REPLIES = ("yes", "y", "approve", "approved", "publish", "yes publish", "go ahead",
                  "yes go ahead")
SUMMARY_MAX = 300


def _normalized(text: str) -> str:
    return " ".join(text.casefold().replace(",", " ").split()).rstrip(".!")


def _reply_digest(text: str, reference: str, bound: dict, simple: bool) -> str | None:
    """The digest recorded for an accepted reply, or None when it is not an approval."""
    if text == _phrase(reference, bound):
        return _digest(text.encode())
    normalized = _normalized(text)
    return _digest(normalized.encode()) if simple and normalized in SIMPLE_REPLIES else None


def _lifetime(receipt: dict) -> int | None:
    issued, expires = receipt.get("issued_at"), receipt.get("expires_at")
    if type(issued) not in (int, float) or type(expires) not in (int, float):
        return None
    for lifetime in (MAX_AGE, SIMPLE_MAX_AGE):
        if expires == issued + lifetime:
            return lifetime
    return None


def _summary(value: object) -> str:
    """One plain-language line describing the work, e.g. "Add dark mode (SC Products)"."""
    if type(value) is not str:
        raise Denied("publication summary invalid")
    text = " ".join(value.split())
    if not text:
        raise Denied("publication summary invalid")
    return text if len(text) <= SUMMARY_MAX else text[:SUMMARY_MAX - 1] + "…"


def _simple_text(summary: str, notes: tuple[tuple[str, str], ...]) -> str:
    return (f"Ready to publish: {summary}\n"
            "It passed testing and an independent review.\n"
            + _notes_text(notes) +
            'Reply "yes" to this message to put it on GitHub as a draft for your review. '
            "Nothing goes live without you.")


def _challenge_text(reference: str, bound: dict | None = None, plan_sha: str | None = None,
                    notes: tuple[tuple[str, str], ...] = ()) -> str:
    bound = BOUND if bound is None else bound
    plan_sha = PLAN_SHA if plan_sha is None else plan_sha
    return ("GitHub Draft PR publication approval\n"
            f"Project/task: {bound['project']} / {bound['task_id']}\n"
            f"Repository: {bound['destination']}\nBase: {bound['base_branch']}\n"
            f"Publication branch: {bound['publication_branch']}\n"
            f"Final revision: {bound['final_revision']}\nPublication plan SHA-256: {plan_sha}\n"
            + _notes_text(notes) +
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


def _check_receipt(receipt: dict, reference: str, bound: dict | None = None, plan_sha: str | None = None,
                   notes: tuple[tuple[str, str], ...] = ()) -> None:
    bound = BOUND if bound is None else bound
    plan_sha = PLAN_SHA if plan_sha is None else plan_sha
    simple = _lifetime(receipt) == SIMPLE_MAX_AGE
    fields = {"schema", "reference", "plan_sha256", *BOUND, "owner_id", "space_id",
              "message_id", "issued_at", "expires_at", "challenge_text_sha256", "phrase_sha256"}
    if (set(receipt) != (fields | {"summary"} if simple else fields)
            or receipt.get("schema") != "alfred.publication-challenge/1"
            or receipt.get("reference") != reference
            or receipt.get("plan_sha256") != plan_sha
            or any(receipt.get(key) != value for key, value in bound.items())
            or not isinstance(receipt.get("owner_id"), str) or not receipt["owner_id"]
            or not isinstance(receipt.get("space_id"), str) or not receipt["space_id"]
            or not isinstance(receipt.get("message_id"), str) or not receipt["message_id"]
            or _lifetime(receipt) is None
            or (simple and receipt.get("summary") != _summary(receipt.get("summary")))
            or receipt.get("challenge_text_sha256") != _digest((
                _simple_text(receipt["summary"], notes) if simple
                else _challenge_text(reference, bound, plan_sha, notes)).encode())
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
            or decision.get("content_sha256") not in (
                {receipt["phrase_sha256"]} | (
                    {_digest(reply.encode()) for reply in SIMPLE_REPLIES}
                    if _lifetime(receipt) == SIMPLE_MAX_AGE else set()))
            or decision.get("checks") != checks
            or type(decision.get("accepted_at")) not in (int, float)
            or not receipt["issued_at"] <= decision["accepted_at"] <= receipt["expires_at"]
            or type(decision.get("sdk_event_timestamp")) not in (int, float)
            or not receipt["issued_at"] <= decision["sdk_event_timestamp"] <= decision["accepted_at"] + 5):
        raise Denied("publication owner decision invalid")


class PublicationApprovalIssuer:
    def __init__(self, root: Path, *, owner_sender_id: str, preview_sender,
                 sidecar_uid: int, clock=time.time, admin_uid: int = 0, plan_verifier=None,
                 delegation_policy: Path | None = None, policy_owner: int = 0,
                 channel_policy: Path | None = None, owner_passkey_pin: Path | None = None,
                 alfred_os_uid: int | None = None):
        # The development issuer already validates this same private Intake store.
        from .owner_grants import _protected
        _protected(root)
        if not owner_sender_id or sidecar_uid == admin_uid:
            raise Denied("publication approval identities invalid")
        self.root, self.owner, self.send = root, owner_sender_id, preview_sender
        self.sidecar_uid, self.admin_uid, self.clock = sidecar_uid, admin_uid, clock
        self._lock = threading.Lock()
        self.plan_verifier = plan_verifier
        # The owner's delegation policy (root-owned), read on every use, so turning it
        # off applies to the next draft PR. None: the owner answers each one.
        self.delegation_policy, self.policy_owner = delegation_policy, policy_owner
        # Alfred OS passkey approvals (owner_approval.py). None: iMessage only, as before.
        self.channel_policy, self.owner_passkey_pin = channel_policy, owner_passkey_pin
        self.alfred_os_uid = alfred_os_uid

    def _policy(self) -> dict | None:
        return load_delegation_policy(self.delegation_policy, owner_uid=self.policy_owner)

    def _delegate(self, bound: dict, plan_sha: str, policy: dict) -> dict:
        """The owner's policy approves this exact draft PR, so no text is sent. The record
        says so plainly and never claims an owner reply."""
        for decided in self.root.glob("publication-decision-*.json"):
            if _decided_plan(self.root, decided) == plan_sha:
                raise Denied("publication decision already exists for this plan")
        reference = uuid.uuid4().hex
        now = self.clock()
        receipt = {"schema": DELEGATED, "reference": reference, "plan_sha256": plan_sha,
                   **bound, "owner_id": self.owner, "policy_sha256": _digest(policy),
                   "issued_at": now, "expires_at": now}
        decision = {"schema": DELEGATED_DECISION, "reference": reference,
                    "challenge_sha256": _digest(receipt),
                    "owner_event_id": f"delegated-publication-{reference}",
                    "accepted_at": now, "peer_uid": self.admin_uid}
        _write_once(self.root, f"publication-challenge-{reference}.json", receipt)
        _write_once(self.root, f"publication-decision-{reference}.json", decision)
        _write_once(self.root, f"publication-issuance-{reference}.json", {
            "schema": "alfred.publication-decision-issuance/1",
            "reference": reference, "challenge_sha256": _digest(receipt),
            "decision_sha256": _digest(decision),
            "bundle_sha256": _digest(_bytes(receipt) + _bytes(decision)),
            "issued_at": now})
        return {"state": "publication_delegated", "challenge": reference, "message_id": None}

    def _context(self, raw: bytes) -> tuple[dict, str, tuple[tuple[str, str], ...]]:
        if self.plan_verifier is None:
            _validate_plan(raw)
            return dict(BOUND), PLAN_SHA, ()
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
        return {key: plan[key] for key in BOUND}, _digest(raw), _notes(plan)

    def _receipt_context(self, receipt: dict) -> tuple[dict, str, tuple[tuple[str, str], ...]]:
        if self.plan_verifier is None or (receipt.get("plan_sha256") == PLAN_SHA and
                all(receipt.get(k) == v for k, v in BOUND.items())):
            return dict(BOUND), PLAN_SHA, ()
        try:
            raw = self.plan_verifier(receipt.get("project"), receipt.get("task_id"))
        except (OSError, ValueError) as exc:
            raise Denied("protected publication evidence unavailable") from exc
        return self._context(raw)

    def stage(self, plan_raw: bytes, *, space_id: str, peer_uid: int,
              summary: object = None, channel: str | None = None) -> dict:
        """With a summary, the owner gets the plain-language 12-hour "yes" approval.
        channel "alfred_os" records an offer for the owner's passkey instead of a text."""
        from . import owner_approval
        if peer_uid != self.admin_uid or type(space_id) is not str or not space_id:
            raise Denied("publication staging requires administrator and DM")
        bound, plan_sha, notes = self._context(plan_raw)
        summary = None if summary is None else _summary(summary)
        policy = self._policy() if summary is not None else None
        if publication_delegation_permits(policy, bound["project"]):
            with self._lock:
                return self._delegate(bound, plan_sha, policy)
        alfred_os = owner_approval.resolve_channel(
            channel, self.channel_policy, owner_uid=self.policy_owner) == "alfred_os"
        with self._lock:
            if owner_approval.open_offers(self.root, "publication", self.clock()):
                raise Denied("publication challenge already pending")
            for declined in self.root.glob("publication-passkey-decline-*.json"):
                if owner_approval.offer_plan_sha(self.root, declined.stem.removeprefix(
                        "publication-passkey-decline-")) == plan_sha:
                    raise Denied("the owner declined this publication plan")
            for path in self.root.glob("publication-pending-*.json"):
                reference = path.stem.removeprefix("publication-pending-")
                receipt = _read(self.root, f"publication-challenge-{reference}.json")
                if self.clock() <= receipt["expires_at"]:
                    raise Denied("publication challenge already pending")
                _write_once(self.root, f"publication-expired-{reference}.json", {
                    "schema": "alfred.publication-challenge-expiry/1", "reference": reference,
                    "challenge_sha256": _digest(receipt), "expired_at": self.clock()})
                path.unlink()
            for decided in self.root.glob("publication-decision-*.json"):
                if _decided_plan(self.root, decided) == plan_sha:
                    raise Denied("publication decision already exists for this plan")
            if alfred_os:
                from .owner_passkey import NotPinned, load_pin
                try:
                    load_pin(self.owner_passkey_pin, owner_uid=self.policy_owner)
                except NotPinned as exc:
                    raise Denied("Alfred OS approvals need the root-pinned owner passkey") from exc
                if self.alfred_os_uid is None:
                    raise Denied("Alfred OS approvals are not configured")
                return owner_approval.write_offer(
                    self.root, kind="publication", project=bound["project"],
                    task_id=bound["task_id"],
                    title=summary or f"Draft PR {bound['project']} {bound['task_id']}",
                    owner_id=self.owner, space_id=space_id, now=self.clock(),
                    body={"publication": {"plan_sha256": plan_sha, **bound},
                          "summary": summary})
            reference = uuid.uuid4().hex
            message = (_challenge_text(reference, bound, plan_sha, notes) if summary is None
                       else _simple_text(summary, notes))
            message_id = self.send(space_id, message)
            if type(message_id) is not str or not message_id:
                raise Denied("publication challenge delivery unverified")
            now = self.clock()
            receipt = {"schema": "alfred.publication-challenge/1", "reference": reference,
                       "plan_sha256": plan_sha, **bound, "owner_id": self.owner,
                       "space_id": space_id, "message_id": message_id,
                       "issued_at": now,
                       "expires_at": now + (MAX_AGE if summary is None else SIMPLE_MAX_AGE),
                       "challenge_text_sha256": _digest(message.encode()),
                       "phrase_sha256": _digest(_phrase(reference, bound).encode()),
                       **({} if summary is None else {"summary": summary})}
            _write_once(self.root, f"publication-challenge-{reference}.json", receipt)
            _write_once(self.root, f"publication-pending-{reference}.json", {
                "message_id": message_id, "space_id": space_id,
                "created_at": now, "challenge_sha256": _digest(receipt)})
            return {"state": "awaiting_native_publication_reply", "challenge": reference,
                    "message_id": message_id}

    def merge_authorization(self, plan_raw: bytes, *, draft_pr_url: object,
                            peer_uid: int) -> dict:
        """The owner's merge policy for this exact published draft PR (handoff.31).

        Delegated: one record, written once per plan, naming the policy in force; the
        root-sealed authorization the Publisher needs to squash-merge it. Otherwise the
        owner merges, exactly as before.
        """
        if peer_uid != self.admin_uid:
            raise Denied("merge authorization requires administrator")
        bound, plan_sha, _ = self._context(plan_raw)
        plan = json.loads(plan_raw)
        if (type(draft_pr_url) is not str or re.fullmatch(
                r"https://github\.com/" + re.escape(bound["destination"]) + r"/pull/[1-9][0-9]{0,9}",
                draft_pr_url) is None):
            raise Denied("merge authorization needs the published draft PR")
        name = f"merge-delegation-{plan_sha[:32]}.json"
        with self._lock:
            if (self.root / name).exists():
                record = _read(self.root, name)
            else:
                # The draft PR itself must have been approved, by the owner or by delegation.
                if not any(_decided_plan(self.root, p) == plan_sha
                           for p in self.root.glob("publication-decision-*.json")):
                    raise Denied("no publication decision for this plan")
                policy = self._policy()
                if not merge_delegation_permits(policy, bound["project"]):
                    return {"state": "merge_not_delegated"}
                record = {"schema": MERGE_DELEGATED, "reference": uuid.uuid4().hex,
                          "plan_sha256": plan_sha, **bound, "draft_pr_url": draft_pr_url,
                          "owner_id": self.owner, "policy": policy,
                          "policy_sha256": _digest(policy),
                          "decided_by": "owner_delegation_policy", "decided_at": self.clock()}
                _write_once(self.root, name, record)
            if (record.get("schema") != MERGE_DELEGATED or record.get("plan_sha256") != plan_sha
                    or record.get("draft_pr_url") != draft_pr_url
                    or any(record.get(k) != v for k, v in bound.items())
                    or record.get("policy_sha256") != _digest(record.get("policy") or {})
                    or not REF.fullmatch(record.get("reference") or "")):
                raise Denied("merge delegation record mismatch")
            return {"state": "merge_authorization_prepared", "authorization": {
                "schema": "alfred.github-merge-authorization/1", "decision": "approved",
                "purpose": "one_squash_merge", **bound,
                "baseline_revision": plan["baseline_revision"],
                "publication_plan_sha256": plan_sha, "draft_pr_url": draft_pr_url,
                "merge_method": "squash",
                "owner_event_id": f"delegated-merge-{record['reference']}",
                "policy_sha256": record["policy_sha256"]}}

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
            bound, plan_sha, notes = self._receipt_context(receipt)
            _check_receipt(receipt, reference, bound, plan_sha, notes)
            if (pending != {"message_id": target, "space_id": receipt["space_id"],
                            "created_at": receipt["issued_at"],
                            "challenge_sha256": _digest(receipt)}):
                raise Denied("publication pending state mismatch")
            now = self.clock()
            timestamp = _event_time(event.get("timestamp"))
            content = event.get("content")
            event_id = event.get("messageId")
            reply = (_reply_digest(content["text"], reference, bound,
                                   _lifetime(receipt) == SIMPLE_MAX_AGE)
                     if type(content) is dict and type(content.get("text")) is str else None)
            if (event.get("direction") != "inbound"
                    or event.get("sender") != {"id": self.owner}
                    or event.get("space") != {"id": receipt["space_id"], "type": "dm"}
                    or event.get("nativeIsForward") is not False
                    or type(event_id) is not str or not 1 <= len(event_id) <= 200
                    or event_id == target
                    or type(content) is not dict or content.get("type") != "text"
                    or reply is None
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
                        "content_type": "text", "content_sha256": reply,
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
        if (self.root / f"owner-offer-{reference}.json").exists():
            return self._prepare_passkey(reference)
        receipt = _read(self.root, f"publication-challenge-{reference}.json")
        decision = _read(self.root, f"publication-decision-{reference}.json")
        issuance = _read(self.root, f"publication-issuance-{reference}.json")
        bound, plan_sha, notes = self._receipt_context(receipt)
        if receipt.get("schema") == DELEGATED:
            # Rechecked against the policy as it is now: delegation turned off (or the
            # project removed) since staging means no draft PR from this record.
            if (set(receipt) != {"schema", "reference", "plan_sha256", *BOUND, "owner_id",
                                 "policy_sha256", "issued_at", "expires_at"}
                    or receipt["reference"] != reference or receipt["plan_sha256"] != plan_sha
                    or any(receipt.get(k) != v for k, v in bound.items())
                    or receipt["owner_id"] != self.owner
                    or not publication_delegation_permits(self._policy(), bound["project"])
                    or decision != {"schema": DELEGATED_DECISION, "reference": reference,
                                    "challenge_sha256": _digest(receipt),
                                    "owner_event_id": f"delegated-publication-{reference}",
                                    "accepted_at": receipt["issued_at"],
                                    "peer_uid": self.admin_uid}):
                raise Denied("delegated publication evidence invalid")
        else:
            _check_receipt(receipt, reference, bound, plan_sha, notes)
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

    def _prepare_passkey(self, reference: str) -> dict:
        """An Alfred OS approval: the stored signature is re-verified against the root pin,
        the sealed plan is re-read, and the decision must come from the Alfred OS peer."""
        from .owner_approval import verify_publication_evidence
        offer = _read(self.root, f"owner-offer-{reference}.json")
        if type(offer.get("publication")) is not dict:
            raise Denied("passkey publication offer invalid")
        bound, plan_sha, _ = self._receipt_context(
            {"project": offer.get("project"), "task_id": offer.get("task_id"),
             "plan_sha256": offer["publication"].get("plan_sha256")})
        decision = verify_publication_evidence(
            self.root, reference, bound=bound, plan_sha=plan_sha,
            pin_path=self.owner_passkey_pin, pin_owner=self.policy_owner,
            alfred_os_uid=self.alfred_os_uid)
        for pattern in ("decision-*.json", "publication-decision-*.json"):
            if sum(_read(self.root, path.name).get("owner_event_id") == decision["owner_event_id"]
                   for path in self.root.glob(pattern)) != (1 if pattern.startswith("publication-") else 0):
                raise Denied("owner event reused")
        return {"schema": "alfred.github-draft-pr-authorization/1", "decision": "approved",
                **bound, "publication_plan_sha256": plan_sha,
                "owner_event_id": decision["owner_event_id"], "purpose": "one_github_draft_pr"}
