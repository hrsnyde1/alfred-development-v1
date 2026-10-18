"""The owner's "undo" reply to a merged change's completion text (handoff.31).

Owner-authorized 2026-10-18: after the pipeline squash-merges a change, the owner can
reply "undo" to the completion text within 24 hours and the pipeline reverts exactly that
squash commit. The reply is verified like a publication approval: the owner's number, the
same DM, a native in-thread reply to that exact completion text, not forwarded, fresh,
single use. The window is bound to the completion text's Photon receipt, read from the
completion delivery record, so no other message can open it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
from pathlib import Path

from .owner_grants import _bytes, _digest, _event_time, _protected, _read, _write_once
from .router import Denied

WINDOW = "alfred.undo-window/1"
DECISION = "alfred.undo-owner-decision/1"
AUTHORIZATION = "alfred.github-revert-authorization/1"
UNDO_MAX_AGE = 24 * 3600
REPLIES = ("undo", "undo it", "undo that", "undo please", "please undo", "undo this",
           "revert", "revert it", "take it back")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
REF = re.compile(r"[0-9a-f]{32}\Z")
PROJECT = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
TASK = re.compile(r"T-[0-9]{4}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
BOUND = ("project", "task_id", "destination", "base_branch", "draft_pr_url",
         "final_revision", "merge_commit", "merge_parent", "publication_plan_sha256")
CHECKS = {"authenticated_sender": True, "same_dm": True, "fresh_event": True,
          "native_direct_reply": True, "not_forwarded": True, "within_undo_window": True,
          "undo_reply": True, "single_use": True}
OUTCOMES = ("undone", "conflict", "already_undone", "not_on_main", "github_refused")


def _normalized(text: str) -> str:
    return " ".join(text.casefold().replace(",", " ").split()).rstrip(".!")


def undo_reply(text: object) -> bool:
    return type(text) is str and _normalized(text) in REPLIES


def _completion_receipt(state: Path, identity: list[str]) -> str | None:
    """The Photon receipt of the completion text, or None when its send is uncertain."""
    fd = os.open(state / "delivery.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > 1048576):
            raise Denied("completion delivery record is not protected")
        records = json.loads(stream.read()).get("records")
    key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    record = records.get(key) if type(records) is dict else None
    if (type(record) is not dict or record.get("identity") != identity
            or record.get("state") != "sent" or type(record.get("receipt_id")) is not str
            or not record["receipt_id"]):
        return None
    return record["receipt_id"]


def undo_text(outcome: str, project: str, commit_url: str | None) -> str:
    if outcome == "undone":
        return f"Undone. {project} is back to how it was before that change.\n{commit_url}"
    reason = {
        "conflict": "main has changed since, and taking it back would clash with the newer work",
        "already_undone": "main no longer has that change",
        "not_on_main": "that change is no longer on main",
        "github_refused": "GitHub refused it",
    }[outcome]
    return f"I couldn't undo that change to {project} on my own: {reason}. Nothing was changed."


class UndoIssuer:
    def __init__(self, root: Path, *, owner_sender_id: str, sidecar_uid: int,
                 clock=time.time, admin_uid: int = 0):
        _protected(root)
        if not owner_sender_id or sidecar_uid == admin_uid:
            raise Denied("undo identities invalid")
        self.root, self.owner = root, owner_sender_id
        self.sidecar_uid, self.admin_uid, self.clock = sidecar_uid, admin_uid, clock
        self._lock = threading.Lock()

    def _check_window(self, window: dict, reference: str) -> None:
        if (set(window) != {"schema", "reference", *BOUND, "owner_id", "space_id",
                            "message_id", "issued_at", "expires_at"}
                or window["schema"] != WINDOW or window["reference"] != reference
                or window["owner_id"] != self.owner
                or type(window["space_id"]) is not str or not window["space_id"]
                or type(window["message_id"]) is not str or not window["message_id"]
                or type(window["issued_at"]) not in (int, float)
                or window["expires_at"] != window["issued_at"] + UNDO_MAX_AGE):
            raise Denied("undo window invalid")

    def open(self, request: dict, *, peer_uid: int) -> dict:
        """After a merged change's completion text: its 24-hour undo window, once."""
        if peer_uid != self.admin_uid or type(request) is not dict:
            raise Denied("undo window requires administrator")
        bound = {k: request.get(k) for k in BOUND}
        space_id, state = request.get("space_id"), request.get("completion_state")
        if (not all(type(v) is str for v in bound.values())
                or not PROJECT.fullmatch(bound["project"]) or not TASK.fullmatch(bound["task_id"])
                or not REPO.fullmatch(bound["destination"])
                or not all(HEX40.fullmatch(bound[k]) for k in ("final_revision", "merge_commit",
                                                               "merge_parent"))
                or not HEX64.fullmatch(bound["publication_plan_sha256"])
                or re.fullmatch(r"https://github\.com/" + re.escape(bound["destination"])
                                + r"/pull/[1-9][0-9]{0,9}", bound["draft_pr_url"]) is None
                or type(space_id) is not str or not space_id
                or type(state) is not str or not Path(state).is_absolute()):
            raise Denied("undo window request invalid")
        reference = _digest(_bytes({k: bound[k] for k in ("project", "task_id", "merge_commit")}))[:32]
        name = f"undo-window-{reference}.json"
        with self._lock:
            if (self.root / name).exists():
                window = _read(self.root, name)
                self._check_window(window, reference)
                if any(window[k] != v for k, v in bound.items()):
                    raise Denied("undo window conflict")
            else:
                message_id = _completion_receipt(Path(state), [
                    bound["project"], bound["task_id"], bound["draft_pr_url"],
                    bound["final_revision"]])
                if message_id is None:
                    return {"state": "undo_unavailable",
                            "reason": "completion text receipt unavailable"}
                now = self.clock()
                window = {"schema": WINDOW, "reference": reference, **bound,
                          "owner_id": self.owner, "space_id": space_id,
                          "message_id": message_id, "issued_at": now,
                          "expires_at": now + UNDO_MAX_AGE}
                _write_once(self.root, name, window)
        return {"state": "undo_window_open", "reference": reference,
                "message_id": window["message_id"], "expires_at": window["expires_at"]}

    def observe(self, event: object, *, peer_uid: int) -> dict:
        if peer_uid != self.sidecar_uid or type(event) is not dict:
            raise Denied("untrusted Photon observation")
        target = event.get("nativeReplyTargetGuid")
        content = event.get("content")
        text = content.get("text") if type(content) is dict else None
        # Any other reply to the completion text ("thanks!") is ordinary conversation.
        if type(target) is not str or not target or not undo_reply(text):
            return {"state": "not_undo"}
        with self._lock:
            matches = []
            for path in self.root.glob("undo-window-*.json"):
                window = _read(self.root, path.name)
                if window.get("message_id") == target:
                    matches.append(window)
            if not matches:
                return {"state": "not_undo"}
            if len(matches) != 1:
                raise Denied("ambiguous undo window")
            window = matches[0]
            reference = window.get("reference")
            self._check_window(window, reference)
            if (self.root / f"undo-decision-{reference}.json").exists():
                return {"state": "undo_already_requested", "reference": reference}
            now = self.clock()
            timestamp = _event_time(event.get("timestamp"))
            event_id = event.get("messageId")
            if (event.get("direction") != "inbound"
                    or event.get("sender") != {"id": self.owner}
                    or event.get("space") != {"id": window["space_id"], "type": "dm"}
                    or event.get("nativeIsForward") is not False
                    or type(event_id) is not str or not 1 <= len(event_id) <= 200
                    or event_id == target
                    or content.get("type") != "text"
                    or not window["issued_at"] <= now <= window["expires_at"]
                    or not window["issued_at"] <= timestamp <= now + 5):
                raise Denied("undo owner reply unverified")
            for pattern in ("decision-*.json", "publication-decision-*.json", "undo-decision-*.json"):
                if any(_read(self.root, record.name).get("owner_event_id") == event_id
                       for record in self.root.glob(pattern)):
                    raise Denied("owner event already used")
            decision = {"schema": DECISION, "reference": reference,
                        "window_sha256": _digest(window), "owner_event_id": event_id,
                        "sender_id": self.owner, "space_id": window["space_id"],
                        "direction": "inbound", "native_reply_target": target,
                        "is_forward": False, "content_type": "text",
                        "content_sha256": _digest(_normalized(text).encode()),
                        "sdk_event_timestamp": timestamp, "accepted_at": now,
                        "peer_uid": peer_uid, "checks": dict(CHECKS)}
            _write_once(self.root, f"undo-decision-{reference}.json", decision)
            return {"state": "undo_requested", "reference": reference}

    def prepare(self, reference: object, *, peer_uid: int) -> dict:
        """The revert authorization for root to seal, after the evidence is rechecked."""
        if peer_uid != self.admin_uid or type(reference) is not str or not REF.fullmatch(reference):
            raise Denied("undo preparation requires administrator and reference")
        window = _read(self.root, f"undo-window-{reference}.json")
        decision = _read(self.root, f"undo-decision-{reference}.json")
        self._check_window(window, reference)
        if (set(decision) != {"schema", "reference", "window_sha256", "owner_event_id",
                              "sender_id", "space_id", "direction", "native_reply_target",
                              "is_forward", "content_type", "content_sha256",
                              "sdk_event_timestamp", "accepted_at", "peer_uid", "checks"}
                or decision["schema"] != DECISION or decision["reference"] != reference
                or decision["window_sha256"] != _digest(window)
                or decision["sender_id"] != self.owner
                or decision["space_id"] != window["space_id"]
                or decision["native_reply_target"] != window["message_id"]
                or decision["owner_event_id"] == window["message_id"]
                or decision["direction"] != "inbound" or decision["is_forward"] is not False
                or decision["content_type"] != "text"
                or decision["content_sha256"] not in {_digest(r.encode()) for r in REPLIES}
                or decision["checks"] != CHECKS or decision["peer_uid"] != self.sidecar_uid
                or type(decision["accepted_at"]) not in (int, float)
                or not window["issued_at"] <= decision["accepted_at"] <= window["expires_at"]):
            raise Denied("undo owner decision invalid")
        for pattern in ("decision-*.json", "publication-decision-*.json", "undo-decision-*.json"):
            if sum(_read(self.root, path.name).get("owner_event_id") == decision["owner_event_id"]
                   for path in self.root.glob(pattern)) != (1 if pattern.startswith("undo-") else 0):
                raise Denied("owner event reused")
        return {"schema": AUTHORIZATION, "decision": "approved",
                "purpose": "revert_one_squash_merge",
                **{k: window[k] for k in BOUND},
                "owner_event_id": decision["owner_event_id"],
                "accepted_at": decision["accepted_at"]}


def notify_request(request: dict) -> tuple[str, str, str]:
    """(space, outcome, commit link) from root's undo notice, validated."""
    space_id, outcome, url = request.get("space_id"), request.get("outcome"), request.get("commit_url")
    if (type(space_id) is not str or not space_id or outcome not in OUTCOMES
            or (outcome == "undone") != (type(url) is str)
            or (url is not None and re.fullmatch(
                r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/commit/[0-9a-f]{40}", url) is None)):
        raise Denied("invalid undo notice")
    return space_id, outcome, url

