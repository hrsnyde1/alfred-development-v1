"""Owner approvals in Alfred OS, signed with the owner's pinned passkey.

Root stages an OFFER exactly as it stages an iMessage challenge today, but with the
`alfred_os` channel nothing is sent. Alfred OS (its own Linux user, `alfred_os_uid`)
lists offers over a second Intake socket, opens one to get a 5-minute STATEMENT that V1
minted, and returns the owner's raw WebAuthn assertion. V1 verifies that assertion
against the root-pinned key (owner_passkey.py) and writes write-once evidence. Alfred OS
never decides anything; a compromised Alfred OS cannot produce a valid answer.

Both answers are signed: the statement's `action` is "approve" or "decline" and is inside
the signed digest, so one can never verify as the other. One offer takes exactly one
answer (`owner-passkey-decided-<offer>.json`, O_EXCL), so a later approve after a decline
is refused. An approval writes the same issuance and grant (development) or decision
(publication) shape as today with source `alfred_os_owner_passkey`; `verify()` and
`prepare()` re-verify the stored signature every time.

Files in the grant store, all written once unless noted:
    owner-offer-<O>.json                        the staged offer
    development-offer-slot-<task>.json          one Alfred OS offer per development task
    owner-passkey-challenge-<R>.json            one per open: the statement and its digest
    owner-passkey-expired-<R>.json              an open superseded by a newer one
    owner-passkey-decided-<O>.json              consumes the offer before any evidence
    owner-passkey-signature-<sha>.json          each signature is accepted once
    owner-passkey-sign-count.json               last sign count seen (replaced in place)
    development-passkey-decision-<O>.json       approve: then issuance-<O> and grant-<O>
    development-passkey-decline-<O>.json        decline: no grant
    publication-decision-<O>.json               approve: then publication-issuance-<O>
    publication-passkey-decline-<O>.json        decline: no authorization
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
import uuid
from pathlib import Path

from . import owner_passkey as passkey
from .owner_grants import (MAX_AGE, PERMISSIONS, _bytes, _digest, _protected, _read,
                           _write_once)
from .router import Denied

SOURCE = "alfred_os_owner_passkey"
OFFER_SCHEMA = "alfred.owner-approval-offer/1"
CHALLENGE_SCHEMA = "alfred.owner-passkey-challenge/1"
OFFER_MAX_AGE = 12 * 3600
MAX_OPENS_PER_OFFER = 10
MAX_OPENS_PER_HOUR = 30
LOCK_TIMEOUT = 1.0
KINDS = ("development", "publication")
ACTIONS = ("approve", "decline")
REF = re.compile(r"[0-9a-f]{32}\Z")
DECISION = {("development", "approve"): "alfred.development-owner-passkey-decision/1",
            ("development", "decline"): "alfred.development-owner-passkey-decline/1",
            ("publication", "approve"): "alfred.publication-owner-passkey-decision/1",
            ("publication", "decline"): "alfred.publication-owner-passkey-decline/1"}
DECISION_FILE = {("development", "approve"): "development-passkey-decision-{}.json",
                 ("development", "decline"): "development-passkey-decline-{}.json",
                 ("publication", "approve"): "publication-decision-{}.json",
                 ("publication", "decline"): "publication-passkey-decline-{}.json"}

# Which channel an offer uses. Only root writes it; absent means iMessage, as before.
CHANNEL_POLICY = Path("/etc/alfred-development/approval-channel.json")
CHANNEL_SCHEMA = "alfred.development-approval-channel/1"
CHANNELS = ("alfred_os", "imessage")


class ApprovalError(Exception):
    """One of the socket contract's refusal codes."""

    CODES = {"expired", "changed_since_review", "not_verified", "already_decided",
             "not_pinned", "unknown_offer", "busy", "invalid"}

    def __init__(self, code: str):
        if code not in self.CODES:
            raise ValueError(code)
        super().__init__(code)
        self.code = code


def load_channel_policy(path: Path | None, *, owner_uid: int) -> str:
    """The default channel: "imessage" when no policy is installed."""
    if path is None:
        return "imessage"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return "imessage"
    except OSError as exc:
        raise Denied("approval channel policy unreadable") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner_uid
                or info.st_mode & 0o022 or info.st_size > 1024):
            raise Denied("approval channel policy is not owner-protected")
        try:
            policy = json.loads(stream.read())
        except ValueError as exc:
            raise Denied("approval channel policy is not JSON") from exc
    if (type(policy) is not dict or set(policy) != {"schema", "default"}
            or policy["schema"] != CHANNEL_SCHEMA or policy["default"] not in CHANNELS):
        raise Denied("approval channel policy invalid")
    return policy["default"]


def resolve_channel(requested: object, path: Path | None, *, owner_uid: int) -> str:
    if requested is None:
        return load_channel_policy(path, owner_uid=owner_uid)
    if requested not in CHANNELS:
        raise Denied("unknown approval channel")
    return requested


def _offer_slot(project: str, task_id: str) -> str:
    return "development-offer-slot-" + _digest({"project": project, "task_id": task_id}) + ".json"


def _decided(root: Path, offer: str) -> bool:
    return (root / f"owner-passkey-decided-{offer}.json").exists()


def _title(value: object, fallback: str) -> str:
    text = " ".join(str(value or "").split())
    text = text or fallback
    return text if len(text) <= 200 else text[:199] + "…"


def write_offer(root: Path, *, kind: str, project: str, task_id: str, title: object,
                owner_id: str, space_id: str, now: float, body: dict) -> dict:
    """Record one offer. The caller holds its issuer's lock and has done its checks."""
    if kind == "development":
        try:
            _write_once(root, _offer_slot(project, task_id), {
                "schema": "alfred.development-offer-attempt/1",
                "project": project, "task_id": task_id})
        except FileExistsError as exc:
            raise Denied("development approval already offered for this task") from exc
    offer = uuid.uuid4().hex
    record = {"schema": OFFER_SCHEMA, "offer": offer, "kind": kind, "project": project,
              "task_id": task_id, "title": _title(title, f"{project} {task_id}"),
              "owner_id": owner_id, "space_id": space_id, "offered_at": now,
              "expires_at": now + OFFER_MAX_AGE, **body}
    if len(_bytes(record)) > 16000:
        raise Denied("approval offer too large")
    _write_once(root, f"owner-offer-{offer}.json", record)
    return {"state": "awaiting_alfred_os_owner_passkey", "challenge": offer,
            "message_id": None, "offer": offer}


def open_offers(root: Path, kind: str, now: float) -> list[dict]:
    """Offers of one kind that still await an answer."""
    result = []
    for path in root.glob("owner-offer-*.json"):
        offer = _read(root, path.name)
        if (offer.get("kind") == kind and not _decided(root, offer.get("offer", ""))
                and now <= offer.get("expires_at", 0)):
            result.append(offer)
    return result


def offer_plan_sha(root: Path, offer: str) -> str | None:
    """The sealed publication plan an Alfred OS offer names (for decided-plan scans)."""
    try:
        record = _read(root, f"owner-offer-{offer}.json")
    except (FileNotFoundError, OSError):
        return None
    return record.get("publication", {}).get("plan_sha256")


def declined(root: Path, kind: str, offer: str) -> bool:
    return (root / DECISION_FILE[(kind, "decline")].format(offer)).exists()


def _notice_text(offer: dict) -> str:
    plan = (offer["request"]["plan_sha256"] if offer["kind"] == "development"
            else offer["publication"]["plan_sha256"])
    return f"Approval opened in Alfred OS: {offer['project']} {offer['task_id']} {plan[:12]}"


class _PasskeyDecision:
    """stage_owner_transition's verifier: the passkey decision already verified."""

    def __init__(self, offer: str, owner: str):
        self.offer, self.owner = offer, owner

    def verify(self, reference: str, expected: dict) -> dict:
        if reference != self.offer:
            raise Denied("passkey decision reference mismatch")
        return {**expected, "owner": self.owner, "decision": "approve_development",
                "source": "independent_owner_channel", "reference": reference}


def _verify_chain(root: Path, offer_id: str, kind: str, pin: dict) -> tuple[dict, dict, dict, dict]:
    """Offer, decided slot, challenge and approve decision, re-verified from stored bytes."""
    offer = _read(root, f"owner-offer-{offer_id}.json")
    decided = _read(root, f"owner-passkey-decided-{offer_id}.json")
    decision = _read(root, DECISION_FILE[(kind, "approve")].format(offer_id))
    reference = decision.get("reference")
    if type(reference) is not str or not REF.fullmatch(reference):
        raise Denied("passkey decision reference invalid")
    challenge = _read(root, f"owner-passkey-challenge-{reference}.json")
    statement = challenge.get("statement")
    if (offer.get("schema") != OFFER_SCHEMA or offer.get("offer") != offer_id
            or offer.get("kind") != kind
            or challenge.get("schema") != CHALLENGE_SCHEMA
            or challenge.get("reference") != reference or challenge.get("offer") != offer_id
            or challenge.get("offer_sha256") != _digest(offer)
            or type(statement) is not dict
            or challenge.get("statement_sha256") != passkey.statement_digest(statement).hex()
            or statement.get("schema") != passkey.STATEMENT_SCHEMA
            or statement.get("kind") != kind or statement.get("action") != "approve"
            or statement.get("offer") != offer_id or statement.get("reference") != reference
            or statement.get("issued_at") != challenge.get("issued_at")
            or statement.get("expires_at") != challenge.get("expires_at")
            or statement.get("rp_id") != pin["rp_id"]
            or statement.get("credential_id") != pin["credential_id"]
            or (kind == "development" and statement.get("request") != offer.get("request"))
            or (kind == "publication" and statement.get("publication") != offer.get("publication"))
            or decided != {"schema": "alfred.owner-passkey-decided/1", "offer": offer_id,
                           "reference": reference, "action": "approve",
                           "decided_at": decision.get("accepted_at")}
            or decision.get("schema") != DECISION[(kind, "approve")]
            or decision.get("offer") != offer_id
            or decision.get("offer_sha256") != _digest(offer)
            or decision.get("challenge_sha256") != _digest(challenge)
            or decision.get("statement_sha256") != challenge["statement_sha256"]
            or decision.get("pin_sha256") != _digest(pin)
            or challenge.get("pin_sha256") != _digest(pin)
            or type(decision.get("assertion")) is not dict
            or decision.get("signature_sha256") != hashlib.sha256(passkey.b64url_decode(
                decision["assertion"].get("signature"))).hexdigest()
            or type(decision.get("accepted_at")) not in (int, float)
            or not challenge["issued_at"] <= decision["accepted_at"] <= challenge["expires_at"]
            or decision["accepted_at"] > offer["expires_at"]):
        raise Denied("passkey approval evidence does not bind this offer")
    result = passkey.verify_raw(pin, decision["assertion"],
                                passkey.statement_digest(statement), last_sign_count=None)
    if (decision.get("checks") != result["checks"]
            or decision.get("sign_count") != result["sign_count"]):
        raise Denied("passkey approval evidence checks differ")
    if declined(root, kind, offer_id):
        raise Denied("passkey offer was declined")
    return offer, challenge, decision, decided


def verify_development_evidence(root: Path, reference: str, grant: dict, expected: dict,
                                pin_path: Path | None, pin_owner: int) -> None:
    """The passkey branch of ProtectedDevelopmentAuthority.verify()."""
    try:
        pin = passkey.load_pin(pin_path, owner_uid=pin_owner)
        offer, challenge, decision, _ = _verify_chain(root, reference, "development", pin)
        issuance = _read(root, f"issuance-{reference}.json")
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise Denied("passkey development grant lacks trusted evidence") from exc
    request = {"schema": "alfred.development-approval-request/1",
               **{key: value for key, value in expected.items() if key != "schema"},
               "state": "pending_owner_decision"}
    if (offer["request"] != request or grant.get("offer_sha256") != _digest(offer)
            or grant.get("decision_sha256") != _digest(decision)):
        raise Denied("passkey development grant binding mismatch")
    if issuance != {"schema": "alfred.development-passkey-issuance/1", "reference": reference,
                    "grant_sha256": _digest(grant), "offer_sha256": _digest(offer),
                    "challenge_sha256": _digest(challenge),
                    "decision_sha256": _digest(decision),
                    "bundle_sha256": _digest(_bytes(grant) + _bytes(offer) + _bytes(challenge)
                                             + _bytes(decision)),
                    "issued_at": decision["accepted_at"]}:
        raise Denied("passkey issuance digest does not match immutable evidence")


def verify_publication_evidence(root: Path, reference: str, *, bound: dict, plan_sha: str,
                                pin_path: Path | None, pin_owner: int,
                                alfred_os_uid: int | None) -> dict:
    """The passkey branch of PublicationApprovalIssuer.prepare(); returns the decision."""
    try:
        pin = passkey.load_pin(pin_path, owner_uid=pin_owner)
        offer, challenge, decision, _ = _verify_chain(root, reference, "publication", pin)
        issuance = _read(root, f"publication-issuance-{reference}.json")
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise Denied("passkey publication approval lacks trusted evidence") from exc
    if (offer["publication"] != {"plan_sha256": plan_sha, **bound}
            or alfred_os_uid is None or decision.get("peer_uid") != alfred_os_uid
            or decision.get("owner_event_id") != "alfred-os-passkey-" + decision["signature_sha256"][:32]):
        raise Denied("passkey publication decision binding mismatch")
    if issuance != {"schema": "alfred.publication-passkey-issuance/1", "reference": reference,
                    "offer_sha256": _digest(offer), "challenge_sha256": _digest(challenge),
                    "decision_sha256": _digest(decision),
                    "bundle_sha256": _digest(_bytes(offer) + _bytes(challenge) + _bytes(decision)),
                    "issued_at": decision["accepted_at"]}:
        raise Denied("passkey publication issuance mismatch")
    return decision


class OwnerApprovals:
    """The three socket operations. Runs inside the trusted Intake process.

    development_request(offer) recomputes the development request from the Gateway now
    and returns (request, plan_raw or None). The publication issuer re-reads the sealed
    plan through its own plan verifier."""

    def __init__(self, root: Path, *, development_issuer, publication_issuer,
                 development_request, alfred_os_uid: int, notice_sender,
                 pin_path: Path | None = passkey.PIN_PATH, pin_owner: int = 0,
                 clock=time.time):
        _protected(root)
        if type(alfred_os_uid) is not int or alfred_os_uid < 1:
            raise Denied("invalid Alfred OS identity")
        self.root, self.clock = root, clock
        self.development, self.publication = development_issuer, publication_issuer
        self.development_request = development_request
        self.alfred_os_uid, self.notice = alfred_os_uid, notice_sender
        self.pin_path, self.pin_owner = pin_path, pin_owner
        self._lock = threading.Lock()

    # --- helpers ---------------------------------------------------------------------

    def _pin(self) -> dict:
        try:
            return passkey.load_pin(self.pin_path, owner_uid=self.pin_owner)
        except passkey.NotPinned as exc:
            raise ApprovalError("not_pinned") from exc

    def _offer(self, offer_id: object) -> dict:
        if type(offer_id) is not str or not REF.fullmatch(offer_id):
            raise ApprovalError("invalid")
        try:
            offer = _read(self.root, f"owner-offer-{offer_id}.json")
        except FileNotFoundError as exc:
            raise ApprovalError("unknown_offer") from exc
        if offer.get("schema") != OFFER_SCHEMA or offer.get("offer") != offer_id:
            raise ApprovalError("unknown_offer")
        return offer

    def _issuer_lock(self, kind: str):
        issuer = self.development if kind == "development" else self.publication
        if issuer is None:
            raise ApprovalError("unknown_offer")
        return issuer._lock

    def _current(self, offer: dict) -> tuple[dict, str]:
        """The bound fields recomputed now, and the human text; changed → refused."""
        try:
            if offer["kind"] == "development":
                from .owner_grants import _challenge_text
                request, plan_raw = self.development_request(offer)
                if request != offer["request"] or (
                        "plan_raw" in offer and (plan_raw is None
                                                 or plan_raw.decode() != offer["plan_raw"])):
                    raise ApprovalError("changed_since_review")
                text = _challenge_text(request, offer["plan_raw"].encode()
                                       if "plan_raw" in offer else None)
                return {"request": request}, text
            from .publication_approval import _challenge_text, _simple_text
            # The sealed plan, re-read through the issuer's protected plan verifier.
            bound, plan_sha, notes = self.publication._receipt_context(
                {"project": offer["project"], "task_id": offer["task_id"],
                 "plan_sha256": offer["publication"]["plan_sha256"]})
        except ApprovalError:
            raise
        except (Denied, OSError, ValueError, KeyError) as exc:
            raise ApprovalError("changed_since_review") from exc
        if {"plan_sha256": plan_sha, **bound} != offer["publication"]:
            raise ApprovalError("changed_since_review")
        text = (_simple_text(offer["summary"], notes) if offer.get("summary") is not None
                else _challenge_text(offer["offer"], bound, plan_sha, notes))
        return {"publication": offer["publication"]}, text

    # --- operations ------------------------------------------------------------------

    def list(self) -> dict:
        now = self.clock()
        approvals = []
        for kind in KINDS:
            for offer in open_offers(self.root, kind, now):
                approvals.append({"offer": offer["offer"], "kind": kind,
                                  "project": offer["project"], "task_id": offer["task_id"],
                                  "title": offer["title"], "expires_at": offer["expires_at"]})
        approvals.sort(key=lambda a: (a["expires_at"], a["offer"]))
        return {"approvals": approvals}

    def open(self, offer_id: object, action: object) -> dict:
        if action not in ACTIONS:
            raise ApprovalError("invalid")
        offer = self._offer(offer_id)
        pin = self._pin()
        lock = self._issuer_lock(offer["kind"])
        if not lock.acquire(timeout=LOCK_TIMEOUT):
            raise ApprovalError("busy")
        try:
            now = self.clock()
            if _decided(self.root, offer["offer"]):
                raise ApprovalError("already_decided")
            if now > offer["expires_at"]:
                raise ApprovalError("expired")
            bound, text = self._current(offer)
            mine, recent = [], 0
            for path in self.root.glob("owner-passkey-challenge-*.json"):
                record = _read(self.root, path.name)
                if record.get("offer") == offer["offer"]:
                    mine.append(record)
                if now - record.get("issued_at", 0) < 3600:
                    recent += 1
            if len(mine) >= MAX_OPENS_PER_OFFER or recent >= MAX_OPENS_PER_HOUR:
                raise ApprovalError("busy")
            # An independent display outside Alfred OS, before any statement exists.
            try:
                self.notice(offer["space_id"], _notice_text(offer))
            except (OSError, ValueError, Denied, TimeoutError) as exc:
                raise ApprovalError("busy") from exc
            for record in mine:
                name = f"owner-passkey-expired-{record['reference']}.json"
                if not (self.root / name).exists():
                    _write_once(self.root, name, {
                        "schema": "alfred.owner-passkey-expiry/1",
                        "reference": record["reference"], "offer": offer["offer"],
                        "challenge_sha256": _digest(record), "expired_at": now})
            reference = uuid.uuid4().hex
            statement = {"schema": passkey.STATEMENT_SCHEMA, "kind": offer["kind"],
                         "action": action, "offer": offer["offer"], "reference": reference,
                         **bound, "nonce": passkey.b64url(os.urandom(32)),
                         "issued_at": now, "expires_at": now + MAX_AGE,
                         "rp_id": pin["rp_id"], "credential_id": pin["credential_id"]}
            digest = passkey.statement_digest(statement)
            record = {"schema": CHALLENGE_SCHEMA, "reference": reference,
                      "offer": offer["offer"], "offer_sha256": _digest(offer),
                      "statement": statement, "statement_sha256": digest.hex(),
                      "challenge_text_sha256": _digest(text.encode()),
                      "pin_sha256": _digest(pin), "issued_at": now,
                      "expires_at": now + MAX_AGE}
            _write_once(self.root, f"owner-passkey-challenge-{reference}.json", record)
        finally:
            lock.release()
        return {"reference": reference, "kind": offer["kind"], "action": action,
                "statement": statement, "human_text": text,
                "challenge_text_sha256": record["challenge_text_sha256"],
                "expires_at": record["expires_at"],
                "webauthn": {"challenge": passkey.b64url(digest), "rpId": pin["rp_id"],
                             "allowCredentials": [{"id": pin["credential_id"],
                                                   "type": "public-key"}],
                             "userVerification": "required", "timeout": 120000}}

    def answer(self, reference: object, assertion: object, *, peer_uid: int) -> dict:
        if type(reference) is not str or not REF.fullmatch(reference):
            raise ApprovalError("invalid")
        try:
            passkey.check_assertion_shape(assertion)
        except passkey.NotVerified as exc:
            raise ApprovalError("invalid") from exc
        try:
            challenge = _read(self.root, f"owner-passkey-challenge-{reference}.json")
        except FileNotFoundError as exc:
            raise ApprovalError("unknown_offer") from exc
        offer = self._offer(challenge.get("offer"))
        pin = self._pin()
        kind, statement = offer["kind"], challenge["statement"]
        lock = self._issuer_lock(kind)
        if not lock.acquire(timeout=LOCK_TIMEOUT):
            raise ApprovalError("busy")
        try:
            with self._lock:
                return self._answer_locked(offer, challenge, statement, pin,
                                           assertion, peer_uid)
        finally:
            lock.release()

    def _answer_locked(self, offer, challenge, statement, pin, assertion, peer_uid) -> dict:
        now = self.clock()
        offer_id, reference, kind = offer["offer"], challenge["reference"], offer["kind"]
        if _decided(self.root, offer_id):
            raise ApprovalError("already_decided")
        if (challenge.get("schema") != CHALLENGE_SCHEMA
                or challenge.get("offer_sha256") != _digest(offer)
                or challenge.get("statement_sha256") != passkey.statement_digest(statement).hex()):
            raise ApprovalError("invalid")
        if ((self.root / f"owner-passkey-expired-{reference}.json").exists()
                or not challenge["issued_at"] <= now <= challenge["expires_at"]
                or now > offer["expires_at"]):
            raise ApprovalError("expired")
        if challenge.get("pin_sha256") != _digest(pin):
            raise ApprovalError("not_verified")
        bound, _ = self._current(offer)
        if any(statement.get(k) != v for k, v in bound.items()):
            raise ApprovalError("changed_since_review")
        raw = passkey.raw_assertion(assertion)
        signature_sha = hashlib.sha256(passkey.b64url_decode(raw["signature"])).hexdigest()
        if (self.root / f"owner-passkey-signature-{signature_sha}.json").exists():
            raise ApprovalError("not_verified")
        count_path = "owner-passkey-sign-count.json"
        last = 0
        if (self.root / count_path).exists():
            record = _read(self.root, count_path)
            if record.get("credential_id") == pin["credential_id"]:
                last = record["sign_count"]
        try:
            result = passkey.verify_raw(pin, raw, passkey.statement_digest(statement),
                                        last_sign_count=last)
        except passkey.NotVerified as exc:
            raise ApprovalError("not_verified") from exc
        action = statement["action"]
        # Consumes the offer first: a crash after this can never accept a second answer.
        try:
            _write_once(self.root, f"owner-passkey-decided-{offer_id}.json", {
                "schema": "alfred.owner-passkey-decided/1", "offer": offer_id,
                "reference": reference, "action": action, "decided_at": now})
        except FileExistsError as exc:
            raise ApprovalError("already_decided") from exc
        _write_once(self.root, f"owner-passkey-signature-{signature_sha}.json", {
            "schema": "alfred.owner-passkey-signature-use/1", "offer": offer_id,
            "reference": reference, "used_at": now})
        _replace(self.root, count_path, {"schema": "alfred.owner-passkey-sign-count/1",
                                         "credential_id": pin["credential_id"],
                                         "sign_count": result["sign_count"]})
        decision = {"schema": DECISION[(kind, action)], "offer": offer_id,
                    "reference": reference, "offer_sha256": _digest(offer),
                    "challenge_sha256": _digest(challenge),
                    "statement_sha256": challenge["statement_sha256"],
                    "assertion": raw, "signature_sha256": signature_sha,
                    "pin_sha256": _digest(pin), "sign_count": result["sign_count"],
                    "checks": result["checks"], "accepted_at": now, "peer_uid": peer_uid}
        if kind == "publication":
            decision["owner_event_id"] = "alfred-os-passkey-" + signature_sha[:32]
        _write_once(self.root, DECISION_FILE[(kind, action)].format(offer_id), decision)
        if action == "decline":
            return {"result": "declined"}
        if kind == "development":
            self._grant(offer, challenge, decision, now)
        else:
            _write_once(self.root, f"publication-issuance-{offer_id}.json", {
                "schema": "alfred.publication-passkey-issuance/1", "reference": offer_id,
                "offer_sha256": _digest(offer), "challenge_sha256": _digest(challenge),
                "decision_sha256": _digest(decision),
                "bundle_sha256": _digest(_bytes(offer) + _bytes(challenge) + _bytes(decision)),
                "issued_at": now})
        return {"result": "approved"}

    def _grant(self, offer, challenge, decision, now) -> None:
        from .approval_transition import stage_owner_transition
        issuer = self.development
        offer_id = offer["offer"]
        if (self.root / f"grant-{offer_id}.json").exists():
            raise Denied("development approval replay conflict")
        grant = stage_owner_transition(
            offer["request"], decision_reference=offer_id, expected_owner=issuer.owner,
            verifier=_PasskeyDecision(offer_id, issuer.owner), grant_reference=offer_id)
        grant.update({"source": SOURCE, "offer_sha256": _digest(offer),
                      "decision_sha256": _digest(decision), "expires_at": now + 86400,
                      "environment": issuer.environment, "permissions": sorted(PERMISSIONS)})
        _write_once(self.root, f"issuance-{offer_id}.json", {
            "schema": "alfred.development-passkey-issuance/1", "reference": offer_id,
            "grant_sha256": _digest(grant), "offer_sha256": _digest(offer),
            "challenge_sha256": _digest(challenge), "decision_sha256": _digest(decision),
            "bundle_sha256": _digest(_bytes(grant) + _bytes(offer) + _bytes(challenge)
                                     + _bytes(decision)),
            "issued_at": now})
        _write_once(self.root, f"grant-{offer_id}.json", grant)


def _replace(root: Path, name: str, value: dict) -> None:
    """The one record that is replaced in place (the last sign count), atomically."""
    _protected(root)
    temporary = root / f".{name}.{uuid.uuid4().hex}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, root / name)


# --- the socket contract -----------------------------------------------------------------

def handle(service: OwnerApprovals, request: object, peer_uid: int) -> dict:
    """One request on owner-approval.sock. Every refusal is {"error": code}."""
    try:
        if peer_uid != service.alfred_os_uid or type(request) is not dict:
            raise ApprovalError("invalid")
        op = request.get("op")
        if op == "list_owner_approvals" and set(request) == {"op"}:
            return service.list()
        if op == "open_owner_approval" and set(request) == {"op", "offer", "action"}:
            return service.open(request["offer"], request["action"])
        if op == "answer_owner_approval" and set(request) == {"op", "reference", "assertion"}:
            return service.answer(request["reference"], request["assertion"], peer_uid=peer_uid)
        raise ApprovalError("invalid")
    except ApprovalError as exc:
        return {"error": exc.code}
    except (Denied, OSError, ValueError, KeyError, TypeError):
        return {"error": "invalid"}
