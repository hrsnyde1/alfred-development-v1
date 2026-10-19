"""Staged, project-aware Photon observation and Gateway inbox writer.

The Unix socket must run under a protected identity. The existing Photon
sidecar and Hermes must have different UIDs; SO_PEERCRED then distinguishes
SDK observations from draft submissions. No Photon or Gateway connection is
opened by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import socket
import socketserver
import stat
import struct
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alfred.gateway.envelope import EnvelopeError, parse_envelope
from alfred.gateway.journal import Journal, JournalError
from alfred.gateway.requesters import require_bound_requester

from developer_v1.approval_transition import approval_request
from developer_v1.gateway_adapter import read_gateway_inputs
from developer_v1.owner_grants import (
    DELEGATION_POLICY,
    DevelopmentGrantIssuer,
    DevelopmentSendFailure,
    _rename_noreplace,
    load_delegation_policy,
    plan_approval_requested,
)
from developer_v1.publication_approval import PublicationApprovalIssuer
from developer_v1 import owner_approval
from developer_v1.owner_passkey import PIN_PATH
from developer_v1.undo_approval import UndoIssuer, notify_request, undo_text
from developer_v1.router import ID, TASK, Denied

MAX_PACKET = 64 * 1024
MAX_EVENT_AGE = 300
MAX_PREVIEW = 4000
DEVELOPMENT_SEND_TIMEOUT = 30
NAMESPACE = uuid.UUID("118579c1-6804-4eb9-b650-714c8386c892")
DRAFT_FIELDS = (
    "title", "task_type", "objective", "scope", "requirements",
    "constraints", "acceptance_criteria", "security_considerations",
    "testing_requirements",
)
# The owner says what they want in their own words ("I want…", "make…", "can you…").
_ACTION = re.compile(
    r"\b(?:build|fix|implement|develop|code|update|change|modify|refactor|test|debug|create|"
    r"add|remove|delete|investigate|improve|make|set|style|restyle|rename|move|replace|"
    r"adjust|tweak|redesign|design|polish|clean|convert|turn|swap|switch|show|hide|display|"
    r"put|place|include|insert|enable|disable|support|handle|connect|integrate|migrate|"
    r"optimi[sz]e|speed|upgrade|rewrite|redo|rework|align|center|resize|recolou?r|color|"
    r"colour|want|need|like|let'?s|should|could|would|can|please)\b"
    r"|\blook\s+into\b|\bset\s+up\b|\bget\s+rid\s+of\b", re.I)
_SOFTWARE = re.compile(r"\b(?:software|code|repo|repository|project|app|application|bug|feature|login|test|endpoint|api|website|site|page|service|server|bot|script|gateway|workflow|database|ui|button|footer|header|navbar|menu|form|layout|theme|color|colour|font|style|css|html|dashboard|screen|component|banner|homepage|home\s+page|landing\s+page|image|logo|icon|section|card|sidebar|modal|popup|dropdown|tab|table|chart|graph|animation|mobile|responsive)\b", re.I)
# Only a plain question about how things are, not "can you…" or "could you…".
_INFORMATION_ONLY = re.compile(r"^\s*(?:what(?:'s|\s+is|\s+are)|why|how\s+(?:is|are|does|do|did)|when|where|who)\b", re.I)


def _development_request_text(text: str, *, project: str | None = None) -> bool:
    """A request names a registered project, or asks for software work in any wording.
    Plain questions stay chat. The owner still approves (the preview, or the CTO plan text)
    before anything runs."""
    if _INFORMATION_ONLY.search(text):
        return False
    if project:
        return True
    return bool(_ACTION.search(text)) and bool(_SOFTWARE.search(text))
class IntakeRefused(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _development_failure(phase, request, exc, plan_sha256=None):
    """Redacted journal evidence; an issuer refusal never proves no send."""
    reasons = {
        "expected one canonical task": "canonical_task_not_unique",
        "canonical task lacks unique trusted Gateway filing": "canonical_filing_not_unique",
        "CTO plan failed schema validation": "plan_schema_invalid",
        "CTO plan does not bind canonical task": "plan_spec_binding_mismatch",
        "CTO plan request identity mismatch": "plan_request_mismatch",
        "plan is not ready for approval": "plan_not_ready",
        "repository binding mismatch": "repository_mismatch",
        "invalid authorized worktree root": "worktree_invalid",
        "invalid scope": "scope_type_invalid",
        "empty or duplicate scope": "scope_invalid",
        "another development approval is pending": "another_approval_pending",
        "existing task grant must be revoked before restaging": "existing_task_grant",
        "development approval challenge too large": "challenge_size_limit",
        "development approval evidence too large": "receipt_size_limit",
        "approval challenge delivery unverified": "send_receipt_unverified",
        "protected preview send failed": "photon_http_refused",
        "invalid protected preview response": "photon_response_size_invalid",
        "missing protected preview ID": "photon_receipt_missing",
    }
    if isinstance(exc, Denied):
        kind = "Denied"
    elif isinstance(exc, TimeoutError):
        kind = "TimeoutError"
    elif isinstance(exc, PermissionError):
        kind = "PermissionError"
    elif isinstance(exc, FileNotFoundError):
        kind = "FileNotFoundError"
    elif isinstance(exc, OSError):
        kind = "OSError"
    else:
        kind = "ValueError"
    project, task = request.get("project"), request.get("task_id")
    number = getattr(exc, "errno", None)
    return {
        "schema": "alfred.development-challenge-failure/1",
        "phase": phase,
        "project": project if isinstance(project, str) and ID.fullmatch(project) else None,
        "task_id": task if isinstance(task, str) and TASK.fullmatch(task) else None,
        "plan_sha256": plan_sha256,
        "exception_kind": kind,
        "reason_code": exc.reason_code if isinstance(exc, DevelopmentSendFailure) else reasons.get(str(exc), "unclassified"),
        "errno": number if type(number) is int and 0 <= number <= 4095 else None,
        "delivery_state": exc.delivery_state if isinstance(exc, DevelopmentSendFailure) else ("not_attempted" if phase != "issuer" else "uncertain"),
    }


@dataclass
class Observed:
    message_id: str
    text: str
    text_digest: str
    space_digest: str
    space_id: str
    timestamp: str
    request_id: str
    received_at: float
    project: str | None = None
    phase: str = "observed"
    draft_digest: str | None = None
    envelope_data: bytes | None = None
    preview_id: str | None = None
    preview_at: float | None = None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request_id(space_digest: str, message_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"photon:{space_digest}:{message_id}"))


class IntakeGate:
    def __init__(self, *, owner_sender_id: str, sidecar_uid: int, hermes_uid: int,
                 intake_dir: Path, gateway_dir: Path, clock=time.monotonic,
                 preview_sender=None, development_issuer=None, development_inputs=None,
                 publication_issuer=None, registry_path: Path | None = None,
                 request_route_root: Path | None = None, undo_issuer=None,
                 delegation_policy: Path | None = None, policy_owner: int = 0) -> None:
        if not owner_sender_id or sidecar_uid == hermes_uid:
            raise ValueError("owner and distinct sidecar/Hermes identities are required")
        self.owner_sender_id = owner_sender_id
        self.sidecar_uid = sidecar_uid
        self.hermes_uid = hermes_uid
        self.intake_dir = intake_dir
        if require_bound_requester(intake_dir, home=intake_dir.parents[2]) != "hermes":
            raise ValueError("intake directory is not the bound Hermes inbox")
        self.gateway_dir = gateway_dir
        self.clock = clock
        self.preview_sender = preview_sender
        self.development_issuer = development_issuer
        self.development_inputs = development_inputs
        self.publication_issuer = publication_issuer
        # handoff.31: the owner's "undo" reply to a merged change's completion text.
        self.undo_issuer = undo_issuer
        self.registry_path = registry_path
        self.request_route_root = request_route_root
        # handoff.33: the owner's root policy. A project in its "owner" mode is filed with
        # no preview; the owner's one text is the CTO plan. None: every request previews.
        self.delegation_policy, self.policy_owner = delegation_policy, policy_owner
        self._lock = threading.Lock()
        self._observed: dict[str, Observed] = {}
        self._retired: dict[str, str] = {}
        self._active: Observed | None = None
        self._completed: dict[str, tuple[str, str, str, str, str]] = {}
        self._terminal: dict[str, tuple[str, str, str]] = {}
        self._status_turn: tuple[str, str, str, float, str] | None = None
        self._last_filed: tuple[str, str, str, str] | None = None

    def dispatch(self, request: object, peer_uid: int) -> dict[str, Any]:
        if not isinstance(request, dict) or not isinstance(request.get("op"), str):
            raise IntakeRefused("invalid_request")
        op = request["op"]
        if op == "observe":
            if peer_uid != self.sidecar_uid:
                raise IntakeRefused("wrong_peer")
            if getattr(self, "undo_issuer", None) is not None:
                try:
                    result = self.undo_issuer.observe(request.get("event"), peer_uid=peer_uid)
                except Denied as exc:
                    raise IntakeRefused("undo_refused") from exc
                if result["state"] != "not_undo":
                    return result
            if getattr(self, "publication_issuer", None) is not None:
                try:
                    result = self.publication_issuer.observe(request.get("event"), peer_uid=peer_uid)
                except Denied as exc:
                    raise IntakeRefused("publication_approval_refused") from exc
                if result["state"] != "not_publication_approval":
                    return result
            if self.development_issuer is not None:
                try:
                    result = self.development_issuer.observe(request.get("event"), peer_uid=peer_uid)
                except Denied as exc:
                    raise IntakeRefused("development_approval_refused") from exc
                if result["state"] != "not_development_approval":
                    return result
            return self._observe(request.get("event"))
        if op == "stage_publication_approval":
            if peer_uid != 0 or self.publication_issuer is None:
                raise IntakeRefused("wrong_peer")
            try:
                raw = request.get("plan_raw")
                if type(raw) is not str or len(raw) > 16384:
                    raise Denied("invalid publication plan bytes")
                summary = request.get("summary")
                if type(summary) is str and self.registry_path is not None:
                    project = json.loads(raw).get("project")
                    summary = f"{summary.rstrip('.')} ({self._display_name(project)})"
                return self.publication_issuer.stage(raw.encode("utf-8"),
                    space_id=request.get("space_id"), peer_uid=peer_uid, summary=summary,
                    channel=_channel(request))
            except (Denied, OSError, ValueError) as exc:
                raise IntakeRefused("publication_request_unavailable") from exc
        if op == "prepare_publication_authorization":
            if peer_uid != 0 or self.publication_issuer is None:
                raise IntakeRefused("wrong_peer")
            try:
                return {"state": "publication_authorization_prepared",
                        "authorization": self.publication_issuer.prepare(
                            request.get("reference"), peer_uid=peer_uid)}
            except (Denied, OSError, ValueError) as exc:
                raise IntakeRefused("publication_authorization_unavailable") from exc
        if op == "stage_merge_authorization":
            # handoff.31: the owner's merge policy for one published draft PR, root only.
            if peer_uid != 0 or self.publication_issuer is None:
                raise IntakeRefused("wrong_peer")
            try:
                raw = request.get("plan_raw")
                if type(raw) is not str or len(raw) > 16384:
                    raise Denied("invalid publication plan bytes")
                return self.publication_issuer.merge_authorization(
                    raw.encode("utf-8"), draft_pr_url=request.get("draft_pr_url"),
                    peer_uid=peer_uid)
            except (Denied, OSError, ValueError) as exc:
                raise IntakeRefused("merge_authorization_unavailable") from exc
        if op in {"open_undo_window", "prepare_undo_authorization", "notify_owner_undo"}:
            if peer_uid != 0 or getattr(self, "undo_issuer", None) is None:
                raise IntakeRefused("wrong_peer")
            try:
                if op == "open_undo_window":
                    return self.undo_issuer.open(request, peer_uid=peer_uid)
                if op == "prepare_undo_authorization":
                    return {"state": "undo_authorization_prepared",
                            "authorization": self.undo_issuer.prepare(
                                request.get("reference"), peer_uid=peer_uid)}
                space_id, outcome, url = notify_request(request)
                project = request.get("project")
                if type(project) is not str or self.preview_sender is None:
                    raise Denied("invalid undo notice")
                text = undo_text(outcome, self._display_name(project)
                                 if self.registry_path else project, url)
                return {"state": "sent", "message_id": self.preview_sender(space_id, text)}
            except (Denied, OSError, ValueError, TimeoutError) as exc:
                raise IntakeRefused("undo_unavailable") from exc
        if op == "notify_owner_stuck":
            # After the last automatic fix round: one plain-language text, root only.
            if peer_uid != 0 or self.preview_sender is None:
                raise IntakeRefused("wrong_peer")
            project, space_id = request.get("project"), request.get("space_id")
            summary, findings = request.get("summary"), request.get("findings")
            if (type(project) is not str or type(space_id) is not str or not space_id
                    or type(summary) is not str or type(findings) is not list
                    or len(findings) > 3 or any(type(f) is not str for f in findings)):
                raise IntakeRefused("invalid_stuck_notice")
            text = _stuck_text(self._display_name(project) if self.registry_path else project,
                               summary, findings)
            try:
                message_id = self.preview_sender(space_id, text)
            except (OSError, ValueError, TimeoutError) as exc:
                raise IntakeRefused("stuck_notice_unavailable") from exc
            return {"state": "sent", "message_id": message_id}
        if op == "notify_owner_plan_refused":
            # handoff.38: the plan step refused a filed task. One fixed text per
            # reason, root only; no exception text or model output ever reaches it.
            if peer_uid != 0 or self.preview_sender is None:
                raise IntakeRefused("wrong_peer")
            project, space_id = request.get("project"), request.get("space_id")
            task_id, reason = request.get("task_id"), request.get("reason")
            if (type(project) is not str or type(space_id) is not str or not space_id
                    or type(task_id) is not str
                    or re.fullmatch(r"T-[0-9]{4}", task_id) is None
                    or type(reason) is not str or reason not in PLAN_REFUSAL_TEXT):
                raise IntakeRefused("invalid_plan_refusal_notice")
            text = _plan_refusal_text(
                self._display_name(project) if self.registry_path else project, task_id, reason)
            try:
                message_id = self.preview_sender(space_id, text)
            except (OSError, ValueError, TimeoutError) as exc:
                raise IntakeRefused("plan_refusal_notice_unavailable") from exc
            return {"state": "sent", "message_id": message_id}
        if op == "revoke_development_grant":
            if peer_uid != 0 or self.development_issuer is None:
                raise IntakeRefused("wrong_peer")
            if not isinstance(request.get("project"), str) or not isinstance(request.get("task_id"), str):
                raise IntakeRefused("invalid_development_request")
            try:
                return self.development_issuer.revoke(
                    project=request["project"], task_id=request["task_id"], peer_uid=peer_uid)
            except Denied as exc:
                raise IntakeRefused("development_revocation_unavailable") from exc
        if op == "stage_development_approval":
            if peer_uid != 0 or self.development_issuer is None or self.development_inputs is None:
                raise IntakeRefused("wrong_peer")
            if not isinstance(request.get("project"), str) or not isinstance(request.get("task_id"), str):
                raise IntakeRefused("invalid_development_request")
            phase, plan_sha256 = "gateway_inputs", None
            try:
                inputs = self.development_inputs(request["project"], request["task_id"])
                plan_sha256 = hashlib.sha256(inputs.plan_raw).hexdigest()
                phase = "approval_binding"
                scope = request.get("scope")
                if type(scope) is not list or any(type(s) is not str for s in scope):
                    raise Denied("invalid scope")
                root = request.get("worktree_root")
                if not isinstance(root, str):
                    raise Denied("invalid worktree root")
                prepared = approval_request(inputs.spec_raw, inputs.plan_raw,
                    project=request["project"], task_id=request["task_id"],
                    repository=inputs.repository, worktree_root=Path(root), scope=scope,
                    spec_decoder=inputs.spec_decoder)
                phase = "issuer"
                plan = json.loads(inputs.plan_raw)
                return self.development_issuer.stage(prepared,
                    space_id=request.get("space_id"), peer_uid=peer_uid,
                    channel=_channel(request),
                    title=str(plan.get("objective") or "").strip().split("\n")[0] or None,
                    project_name=(self._display_name(request["project"])
                                  if getattr(self, "registry_path", None) is not None else None),
                    **({"plan_raw": inputs.plan_raw} if plan.get("baseline_revision") else {}))
            except (Denied, OSError, ValueError) as exc:
                try:
                    print(json.dumps(_development_failure(phase, request, exc, plan_sha256),
                                     sort_keys=True), file=sys.stderr, flush=True)
                except OSError:
                    pass  # Logging failure never authorizes a retry or changes the refusal.
                raise IntakeRefused("development_request_unavailable") from exc
        if op in {"submit", "status"}:
            if peer_uid != self.hermes_uid:
                raise IntakeRefused("wrong_peer")
            event_id = request.get("event_id")
            digest = request.get("text_digest")
            if not isinstance(event_id, str) or not isinstance(digest, str):
                raise IntakeRefused("missing_turn_binding")
            if op == "submit":
                return self._submit(event_id, digest, request.get("draft"))
            return self._status(event_id, digest)
        raise IntakeRefused("unknown_operation")

    def _observe(self, event: object) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise IntakeRefused("invalid_event")
        sender = event.get("sender")
        space = event.get("space")
        content = event.get("content")
        # The original SDK sender is mandatory. No space.phone/space.id fallback.
        sender_id = sender.get("id") if isinstance(sender, dict) else None
        if sender_id != self.owner_sender_id:
            return {"state": "ignored"}
        if event.get("direction") != "inbound":
            return {"state": "ignored"}
        if not isinstance(space, dict) or space.get("type") != "dm":
            return {"state": "ignored"}
        message_id = event.get("messageId")
        space_id = space.get("id")
        text = content.get("text") if isinstance(content, dict) and content.get("type") == "text" else None
        timestamp = event.get("timestamp")
        if (not isinstance(message_id, str) or not 1 <= len(message_id) <= 200
                or not isinstance(space_id, str) or not 1 <= len(space_id) <= 200
                or not isinstance(text, str) or not 1 <= len(text) <= 8000
                or not isinstance(timestamp, str)):
            raise IntakeRefused("incomplete_event")
        space_digest = _digest(space_id)[:32]
        text_digest = _digest(text)
        request_id = _request_id(space_digest, message_id)
        try:
            # The envelope validator also checks the timestamp's exact grammar.
            parse_envelope(_envelope(message_id, space_digest, text, timestamp,
                                     _empty_draft(), request_id, project="unresolved"))
        except EnvelopeError:
            raise IntakeRefused("incomplete_event") from None
        record = Observed(message_id, text, text_digest, space_digest, space_id,
                          timestamp, request_id, self.clock())
        # Advance a filed request even when Hermes never requested status.
        # Otherwise a completed preview leaves every subsequent owner turn busy.
        previous_active = self._active
        if previous_active is not None and previous_active.phase == "submitted":
            self._status(previous_active.message_id, previous_active.text_digest)
        with self._lock:
            active = self._active
            if (active and active.phase == "awaiting_confirmation"
                    and self.clock() - active.preview_at > MAX_EVENT_AGE):
                active.phase = "expired"
                self._active = None
                self._retired[active.message_id] = active.text_digest
                if event.get("nativeReplyTargetGuid") == active.preview_id:
                    raise IntakeRefused("confirmation_expired")
                active = None
            if (active and active.phase == "awaiting_confirmation"
                    and active.preview_id and event.get("nativeReplyTargetGuid") == active.preview_id
                    and space_id == active.space_id):
                if message_id == active.message_id or message_id in self._retired:
                    raise IntakeRefused("confirmation_reused")
                if event.get("nativeIsForward") is not False:
                    raise IntakeRefused("confirmation_unverified")
                if " ".join(text.casefold().replace(",", " ").split()).rstrip(".!") not in {
                        "yes", "y", "go ahead", "yes go ahead", "start", "yes start"}:
                    raise IntakeRefused("confirmation_not_affirmative")
                if active.envelope_data is None:
                    raise IntakeRefused("confirmation_unavailable")
                if self.request_route_root is not None:
                    from developer_v1.owner_grants import _write_once
                    _write_once(self.request_route_root, f"request-route-{active.request_id}.json", {
                        "schema": "alfred.confirmed-request-route/1", "request_id": active.request_id,
                        "project": active.project, "owner_id": self.owner_sender_id,
                        "space_id": active.space_id, "request_event_id": active.message_id,
                        "confirmation_event_id": message_id, "native_reply_target": active.preview_id,
                        "envelope_sha256": hashlib.sha256(active.envelope_data).hexdigest(),
                        "confirmed_at": time.time(), "sidecar_uid": self.sidecar_uid})
                _publish(self.intake_dir / "inbox", f"{active.request_id}.json", active.envelope_data)
                active.phase = "submitted"
                self._retired[message_id] = text_digest
                self._status_turn = (message_id, text_digest, space_digest,
                                     self.clock(), active.request_id)
                return {"state": "submitted"}
            if message_id in self._retired:
                if self._retired[message_id] != text_digest:
                    raise IntakeRefused("event_conflict")
                return {"state": "expired"}
            if active:
                if active.message_id != message_id:
                    if active.space_digest == space_digest:
                        self._status_turn = (message_id, text_digest, space_digest,
                                             self.clock(), active.request_id)
                    # Freeze every observed SDK ID while a preview is pending.
                    # An unrelated delivery cannot later reappear with a
                    # substituted native target and become its confirmation.
                    if len(self._retired) >= 256:
                        active.phase = "uncertain"
                        self._active = None
                        raise IntakeRefused("confirmation_capacity")
                    self._retired[message_id] = text_digest
                    return {"state": "busy"}
                if active.text_digest != record.text_digest or active.space_digest != record.space_digest:
                    raise IntakeRefused("event_conflict")
                return {"state": active.phase}
            if message_id in self._completed:
                if self._completed[message_id][:2] != (record.text_digest, record.space_digest):
                    raise IntakeRefused("event_conflict")
                return {"state": "filed"}
            if message_id in self._terminal:
                if self._terminal[message_id][0] != record.text_digest:
                    raise IntakeRefused("event_conflict")
                return {"state": self._terminal[message_id][1]}
            previous = self._observed.get(message_id)
            if previous and (previous.text_digest, previous.space_digest) != (text_digest, space_digest):
                raise IntakeRefused("event_conflict")
            if previous:
                if self.clock() - previous.received_at > MAX_EVENT_AGE:
                    self._observed.pop(message_id)
                    self._retired[message_id] = previous.text_digest
                    return {"state": "expired"}
                record = previous
            else:
                # Hermes may submit a queued owner turn after a later message arrives.
                # Keep each exact SDK ID and text digest for its own bounded lifetime.
                for key, old in list(self._observed.items()):
                    if self.clock() - old.received_at > MAX_EVENT_AGE:
                        self._observed.pop(key)
                        self._retired[key] = old.text_digest
                if len(self._observed) >= 16:
                    key, old = next(iter(self._observed.items()))
                    self._observed.pop(key)
                    self._retired[key] = old.text_digest
                while len(self._retired) > 256:
                    self._retired.pop(next(iter(self._retired)))
                self._observed[message_id] = record
            if self._last_filed and self._last_filed[0] == space_digest:
                self._status_turn = (message_id, text_digest, space_digest,
                                     self.clock(), self._last_filed[1])
        return {"state": "observed"}

    def _project(self, text: str) -> str:
        if self.registry_path is None:
            raise IntakeRefused("project_registry_unavailable")
        from alfred.registry.loader import parse_registry, read_registry_data
        registry = parse_registry(read_registry_data(self.registry_path))
        # The exact project ID, or a registered alias or multi-word ID written
        # naturally: "demo-site" matches "the demo site" (any case, hyphens or
        # spaces). A one-word ID such as "alfred" never matches loosely, so
        # "Alfred, ..." does not name the alfred project.
        words = " " + " ".join(re.findall(r"[a-z0-9]+", text.casefold())) + " "

        def named(project) -> bool:
            loose = [*project.aliases, *([project.id] if "-" in project.id else [])]
            return any(" " + name.replace("-", " ") + " " in words for name in loose)

        matches = [p for p in registry.projects
                   if re.search(r"(?<![a-z0-9-])" + re.escape(p.id) + r"(?![a-z0-9-])", text)
                   or named(p)]
        if len(matches) != 1 or matches[0].status != "active" or not matches[0].permissions.hermes_requests:
            raise IntakeRefused("explicit_authorized_project_required")
        return matches[0].id

    def _plan_approval(self, project: str) -> bool:
        """Whether the owner's root policy has this project's plan approved by the owner's
        yes to the plan text. Unreadable or invalid: no, so the request previews as before."""
        try:
            policy = load_delegation_policy(getattr(self, "delegation_policy", None),
                                            owner_uid=getattr(self, "policy_owner", 0))
        except Denied:
            return False
        return plan_approval_requested(policy, project)

    def _display_name(self, project_id: str) -> str:
        """The registry's human name for a project (e.g. "SC Products Group website")."""
        from alfred.registry.loader import parse_registry, read_registry_data
        registry = parse_registry(read_registry_data(self.registry_path))
        names = [p.display_name for p in registry.projects if p.id == project_id]
        return names[0] if len(names) == 1 and names[0] else project_id

    def _linked_request(self, followup: Observed) -> Observed:
        """Hermes asks a clarifying question first, then submits the owner's short answer
        ("2", "yes"), which names no project. File the owner's own request from the same
        DM within the event lifetime instead, exactly as if Hermes had submitted it. The
        project still comes only from genuine owner text, and nothing runs before the
        owner's native yes (to the preview, or to the CTO plan text)."""
        now = self.clock()
        candidates = []
        for record in self._observed.values():
            if (record is followup or record.space_digest != followup.space_digest
                    or record.received_at > followup.received_at
                    or now - record.received_at > MAX_EVENT_AGE
                    or record.phase != "observed" or record.message_id in self._retired
                    or record.message_id in self._completed or record.message_id in self._terminal):
                continue
            try:
                project = self._project(record.text)
            except IntakeRefused:
                continue
            if _development_request_text(record.text, project=project):
                candidates.append((record.received_at, project, record))
        # Requests naming different projects are ambiguous; the owner must restate one.
        if not candidates or len({project for _, project, _ in candidates}) != 1:
            raise IntakeRefused("explicit_authorized_project_required")
        original = max(candidates, key=lambda candidate: candidate[0])[2]
        # The answer is consumed; Hermes's status calls on this turn follow the original.
        self._observed.pop(followup.message_id, None)
        self._retired[followup.message_id] = followup.text_digest
        self._status_turn = (followup.message_id, followup.text_digest,
                             followup.space_digest, now, original.request_id)
        return original

    def _require_active(self, event_id: str, digest: str) -> Observed:
        active = self._active
        if active is None or active.message_id != event_id or active.text_digest != digest:
            raise IntakeRefused("unverified_event")
        return active

    def _submit(self, event_id: str, digest: str, draft: object) -> dict[str, Any]:
        if not isinstance(draft, dict) or set(draft) != set(DRAFT_FIELDS):
            raise IntakeRefused("invalid_draft")
        with self._lock:
            if self._active is not None:
                active = self._require_active(event_id, digest)
            else:
                active = self._observed.get(event_id)
                if active is None or active.text_digest != digest or event_id in self._retired:
                    raise IntakeRefused("unverified_event")
                try:
                    self._project(active.text)
                except IntakeRefused as exc:
                    if exc.code != "explicit_authorized_project_required":
                        raise
                    active = self._linked_request(active)
                if not _development_request_text(active.text, project=self._project(active.text)):
                    raise IntakeRefused("not_development_request")
                if self.clock() - active.received_at > MAX_EVENT_AGE:
                    self._observed.pop(active.message_id, None)
                    self._retired[active.message_id] = active.text_digest
                    raise IntakeRefused("expired_event")
                try:
                    if Journal(self.gateway_dir / "journal.jsonl").outcomes_for(active.request_id):
                        raise IntakeRefused("previous_gateway_outcome")
                except JournalError:
                    raise IntakeRefused("gateway_unavailable") from None
            project = self._project(active.text)
            active.project = project
            envelope = _envelope(active.message_id, active.space_digest, active.text,
                                 active.timestamp, draft, active.request_id, project=project)
            try:
                parse_envelope(envelope)
            except EnvelopeError:
                raise IntakeRefused("invalid_draft") from None
            data = (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode()
            draft_digest = hashlib.sha256(data).hexdigest()
            if active.draft_digest and active.draft_digest != draft_digest:
                raise IntakeRefused("request_conflict")
            if active.phase == "observed" and self._plan_approval(project):
                # The owner approves the CTO's plan instead (handoff.33): file these exact
                # envelope bytes, bound to the owner's own message, and send nothing.
                active.draft_digest = draft_digest
                active.envelope_data = data
                if self.request_route_root is not None:
                    from developer_v1.owner_grants import _write_once
                    _write_once(self.request_route_root, f"request-route-{active.request_id}.json", {
                        "schema": "alfred.direct-request-route/1", "request_id": active.request_id,
                        "project": project, "owner_id": self.owner_sender_id,
                        "space_id": active.space_id, "request_event_id": active.message_id,
                        "envelope_sha256": draft_digest, "approval": "owner_plan_reply",
                        "filed_at": time.time(), "sidecar_uid": self.sidecar_uid})
                _publish(self.intake_dir / "inbox", f"{active.request_id}.json", data)
                active.phase = "submitted"
                self._active = active
                self._observed.pop(active.message_id, None)
                self._status_turn = (active.message_id, active.text_digest, active.space_digest,
                                     self.clock(), active.request_id)
            if active.phase == "observed":
                preview = _preview_text(active.text, draft, draft_digest,
                                        project=self._display_name(project))
                active.draft_digest = draft_digest
                active.envelope_data = data
                active.phase = "previewing"
                self._active = active
                try:
                    preview_id = self.preview_sender(active.space_id, preview) if self.preview_sender else None
                    if (not isinstance(preview_id, str) or not 1 <= len(preview_id) <= 200
                            or preview_id == active.message_id):
                        raise ValueError("missing preview message ID")
                except (OSError, ValueError, TimeoutError):
                    active.phase = "uncertain"
                    self._active = None
                    self._retired[active.message_id] = active.text_digest
                    raise IntakeRefused("preview_unavailable") from None
                active.preview_id = preview_id
                active.preview_at = self.clock()
                active.phase = "awaiting_confirmation"
            return {"state": active.phase, "request_id": active.request_id}

    def _status(self, event_id: str, digest: str) -> dict[str, Any]:
        with self._lock:
            completed = self._completed.get(event_id)
            if completed:
                if completed[0] != digest:
                    raise IntakeRefused("unverified_event")
                return {"state": "filed", "request_id": completed[2],
                        "task_id": completed[3], "project": completed[4]}
            terminal = self._terminal.get(event_id)
            if terminal:
                if terminal[0] != digest:
                    raise IntakeRefused("unverified_event")
                return {"state": terminal[1], "request_id": terminal[2]}
            status_turn = self._status_turn
            is_status_turn = bool(status_turn and status_turn[:2] == (event_id, digest)
                                  and self.clock() - status_turn[3] <= MAX_EVENT_AGE)
            if self._active is None:
                if (is_status_turn and self._last_filed
                        and status_turn[2] == self._last_filed[0]
                        and status_turn[4] == self._last_filed[1]):
                    return {"state": "filed", "request_id": self._last_filed[1],
                            "task_id": self._last_filed[2], "project": self._last_filed[3]}
                raise IntakeRefused("unverified_event")
            active = self._active if (is_status_turn and status_turn[2] == self._active.space_digest
                                      and status_turn[4] == self._active.request_id) \
                else self._require_active(event_id, digest)
            if active.phase != "submitted":
                return {"state": active.phase}
            try:
                outcomes = Journal(self.gateway_dir / "journal.jsonl").outcomes_for(active.request_id)
            except JournalError:
                raise IntakeRefused("gateway_unavailable") from None
            filed = [row for row in outcomes if row.get("outcome") == "filed"
                     and row.get("project") == active.project and isinstance(row.get("task_id"), str)]
            if len(filed) != 1:
                if outcomes:
                    outcome = outcomes[-1].get("outcome")
                    if outcome in {"rejected_invalid", "needs_clarification"}:
                        self._terminal[active.message_id] = (
                            active.text_digest, outcome, active.request_id)
                        if len(self._terminal) > 256:
                            self._terminal.pop(next(iter(self._terminal)))
                        self._active = None
                        return {"state": outcome, "request_id": active.request_id}
                return {"state": "submitted", "request_id": active.request_id}
            task_id = filed[0]["task_id"]
            self._completed[active.message_id] = (
                active.text_digest, active.space_digest, active.request_id, task_id, active.project)
            self._last_filed = (active.space_digest, active.request_id, task_id, active.project)
            if len(self._completed) > 256:
                self._completed.pop(next(iter(self._completed)))
            self._active = None
            return {"state": "filed", "request_id": active.request_id,
                    "task_id": task_id, "project": active.project}


def _channel(request: dict) -> str | None:
    """A stage op's optional channel; None means the root channel policy decides."""
    channel = request.get("channel")
    if channel is not None and channel not in owner_approval.CHANNELS:
        raise Denied("unknown approval channel")
    return channel


def _empty_draft() -> dict[str, str]:
    return {"title": "Pending draft", "task_type": "feature", "objective": "Pending.",
            "scope": "Pending.", "requirements": "Pending.", "constraints": "Pending.",
            "acceptance_criteria": "- [ ] Pending", "security_considerations": "Pending.",
            "testing_requirements": "Pending."}


def _stuck_text(project: str, summary: str, findings: list[str]) -> str:
    def line(value: str, limit: int) -> str:
        text = " ".join(value.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    problems = "\n".join(f"- {line(f, 200)}" for f in findings) or "- (no details recorded)"
    return (f"I couldn't finish this one: {line(summary, 200)} ({line(project, 80)}).\n"
            "The team tried 3 rounds of fixes, but it still isn't passing review:\n"
            f"{problems}\n"
            "Nothing was published. Tell me what to change, or send a new request.")


# handoff.38: why a filed task was not planned, in the owner's words. Fixed texts only.
PLAN_REFUSAL_TEXT = {
    "clarification_required": "needs a clearer request: which files or which part should "
                              "change? Send it again with that detail.",
    "project_outside_policy": "can't be planned: this project isn't set up for automatic "
                              "development.",
    "registered_main_unavailable": "is on hold: I couldn't read the project's main branch "
                                   "on GitHub. Send it again in a little while.",
    "main_moved": "is on hold: the main branch changed while I was planning. Send it again.",
    "planning_tree_unavailable": "can't be planned: the repository is too large or has "
                                 "files I can't plan from safely.",
}


def _plan_refusal_text(project: str, task_id: str, reason: str) -> str:
    name = " ".join(project.split())
    name = name if len(name) <= 80 else name[:79] + "…"
    return f"{task_id} ({name}) {PLAN_REFUSAL_TEXT[reason]} Nothing was started."


def _preview_text(utterance: str, draft: dict[str, Any], digest: str, *, project: str) -> str:
    # Plain language for the owner (the only person on this line). The gate still
    # stores and later publishes exactly the envelope bytes this preview was built
    # from; Hermes cannot revise them after confirmation.
    def line(value: object) -> str:
        return " ".join(str(value).split())

    preview = (f"Here's what I'll hand to the development team for {project}:\n"
               f"{line(draft.get('title', ''))}\n"
               f"Goal: {line(draft.get('objective', ''))}\n"
               f"What changes: {line(draft.get('scope', ''))}\n"
               f"Must do: {line(draft.get('requirements', ''))}\n"
               'Is that right? Reply "yes" to this message in the next 5 minutes to start.')
    if len(preview) > MAX_PREVIEW:
        raise IntakeRefused("preview_too_large")
    return preview


def _sidecar_preview_sender(port: int, token: str, *, timeout=2):
    if not isinstance(port, int) or not 1 <= port <= 65535 or not isinstance(token, str) or not token:
        raise ValueError("protected preview transport configuration is required")

    def send(space_id: str, preview: str) -> str:
        body = json.dumps({"spaceId": space_id, "text": preview, "format": "text"}).encode()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        development = timeout == DEVELOPMENT_SEND_TIMEOUT
        expired = threading.Event()

        def deadline():
            expired.set()
            if connection.sock is not None:
                try:
                    connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        timer = threading.Timer(timeout, deadline) if development else None
        try:
            if development:
                # No HTTP bytes have been submitted if explicit connect fails.
                timer.daemon = True
                timer.start()
                try:
                    connection.connect()
                except OSError as exc:
                    raise DevelopmentSendFailure("not_attempted", "connect_failed") from exc
                if expired.is_set():
                    raise DevelopmentSendFailure("not_attempted", "connect_failed")
            connection.request("POST", "/send", body,
                               {"Content-Type": "application/json", "x-hermes-sidecar-token": token})
            response = connection.getresponse()
            if response.status != 200:
                if development:
                    # These are explicit local rejections before resolveSpace/send
                    # in the pinned existing Photon handler. Generic 500s are not.
                    if response.status in {400, 401, 405}:
                        raise DevelopmentSendFailure("not_attempted", "http_preflight_refused")
                    payload = response.read(1025)
                    code = "http_failed"
                    if len(payload) <= 1024:
                        try:
                            result = json.loads(payload)
                            if type(result) is dict and result.get("error_class") == "target_not_allowed":
                                code = "provider_refused"
                        except ValueError:
                            pass
                    raise DevelopmentSendFailure("uncertain", code)
                raise OSError("protected preview send failed")
            payload = response.read(1025)
            if len(payload) > 1024:
                raise OSError("invalid protected preview response")
            result = json.loads(payload)
            if type(result) is not dict or result.get("ok") is not True or not isinstance(result.get("messageId"), str):
                raise OSError("missing protected preview ID")
            if development and (expired.is_set() or not 1 <= len(result["messageId"]) <= 200):
                raise DevelopmentSendFailure("uncertain", "ack_timeout" if expired.is_set() else "ack_invalid")
            return result["messageId"]
        except DevelopmentSendFailure:
            raise
        except (OSError, ValueError, http.client.HTTPException) as exc:
            if development:
                raise DevelopmentSendFailure("uncertain", "ack_timeout" if expired.is_set() or isinstance(exc, TimeoutError) else "ack_invalid") from exc
            raise
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()

    return send


def _envelope(message_id: str, conversation_ref: str, text: str, timestamp: str,
              draft: dict[str, Any], request_id: str, *, project: str) -> dict[str, Any]:
    return {"protocol": "alfred.devreq/1", "request_id": request_id, "revision": 1,
            "submitted_at": timestamp,
            "origin": {"interface": "photon", "conversation_ref": conversation_ref},
            "utterance": text, "project_hint": project, "intent_confidence": 0.9,
            "draft": draft, "answers": []}


def _publish(inbox: Path, name: str, data: bytes) -> None:
    if len(data) > MAX_PACKET:
        raise IntakeRefused("request_too_large")
    directory = os.open(inbox, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = f".{name}.{uuid.uuid4().hex}.tmp"
    try:
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o640, dir_fd=directory)
            with os.fdopen(fd, "wb") as handle:
                # The protected Gateway reader uses the inbox's setgid group.
                # fchmod avoids a restrictive service umask making it unreadable.
                os.fchmod(handle.fileno(), 0o640)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            _rename_noreplace(directory, temporary, name)
            os.fsync(directory)
        except FileExistsError:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or os.read(fd, MAX_PACKET + 1) != data):
                    raise IntakeRefused("request_conflict")
                os.fsync(directory)
            finally:
                os.close(fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(2)
        peer_uid = struct.unpack("3i", self.request.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))[1]
        packet = bytearray()
        while len(packet) <= MAX_PACKET:
            chunk = self.request.recv(min(4096, MAX_PACKET + 1 - len(packet)))
            if not chunk:
                break
            packet.extend(chunk)
            if b"\n" in chunk:
                break
        try:
            if len(packet) > MAX_PACKET or b"\n" not in packet:
                raise IntakeRefused("invalid_request")
            request = json.loads(bytes(packet).split(b"\n", 1)[0])
            result = self.server.gate.dispatch(request, peer_uid)  # type: ignore[attr-defined]
            reply = {"ok": True, **result}
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            reply = {"ok": False, "error": exc.code if isinstance(exc, IntakeRefused)
                     else "intake_unavailable"}
        self.request.sendall((json.dumps(reply, separators=(",", ":")) + "\n").encode())


class _OwnerHandler(socketserver.BaseRequestHandler):
    """owner-approval.sock: Alfred OS's three operations, same framing as intake.sock.
    Replies are the contract's bare JSON objects ({"error": code} on refusal)."""

    def handle(self) -> None:
        self.request.settimeout(2)
        peer_uid = struct.unpack("3i", self.request.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))[1]
        packet = bytearray()
        try:
            while len(packet) <= MAX_PACKET:
                chunk = self.request.recv(min(4096, MAX_PACKET + 1 - len(packet)))
                if not chunk:
                    break
                packet.extend(chunk)
                if b"\n" in chunk:
                    break
        except OSError:
            packet = bytearray()
        if len(packet) > MAX_PACKET or b"\n" not in packet:
            reply = {"error": "invalid"}
        else:
            try:
                request = json.loads(bytes(packet).split(b"\n", 1)[0])
            except ValueError:
                reply = {"error": "invalid"}
            else:
                reply = owner_approval.handle(self.server.service, request, peer_uid)  # type: ignore[attr-defined]
        try:
            self.request.sendall((json.dumps(reply, separators=(",", ":")) + "\n").encode())
        except OSError:
            pass


def _restrict_socket(path: Path, uid: int) -> None:
    """Exactly: owner rw, the Alfred OS user rw, nobody else (replaces inherited ACLs)."""
    read_write = 0o6
    entries = [(0x01, read_write, 0xFFFFFFFF), (0x02, read_write, uid),
               (0x04, 0, 0xFFFFFFFF), (0x10, read_write, 0xFFFFFFFF),
               (0x20, 0, 0xFFFFFFFF)]
    acl = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *e) for e in entries)
    os.setxattr(path, "system.posix_acl_access", acl, follow_symlinks=False)
    if os.getxattr(path, "system.posix_acl_access", follow_symlinks=False) != acl:
        raise ValueError("owner approval socket ACL not applied")


def serve_owner_approvals(socket_path: Path, service, alfred_os_uid: int) -> None:
    """The second listener. A failure here never stops intake.sock or iMessage."""
    try:
        if socket_path.exists() or socket_path.is_symlink():
            raise ValueError("owner approval socket path already exists")
        parent_info = socket_path.parent.lstat()
        if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.geteuid()
                or parent_info.st_mode & 0o022):
            raise ValueError("socket parent must be owned by the protected identity")
        server = socketserver.ThreadingUnixStreamServer(str(socket_path), _OwnerHandler)
        server.daemon_threads = True
        server.service = service  # type: ignore[attr-defined]
        os.chmod(socket_path, 0o600)
        _restrict_socket(socket_path, alfred_os_uid)
    except (OSError, ValueError) as exc:
        print(json.dumps({"event": "owner_approval_socket_unavailable",
                          "error": type(exc).__name__}), file=sys.stderr, flush=True)
        return
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                     name="owner-approvals", daemon=True).start()


def serve(socket_path: Path, gate: IntakeGate) -> None:
    """Run only under a protected service identity with a protected socket parent."""
    if socket_path.exists() or socket_path.is_symlink():
        raise ValueError("socket path already exists")
    parent_info = socket_path.parent.lstat()
    if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.geteuid()
            or parent_info.st_mode & 0o022):
        raise ValueError("socket parent must be owned by the protected identity")
    with socketserver.UnixStreamServer(str(socket_path), _Handler) as server:
        server.gate = gate  # type: ignore[attr-defined]
        os.chmod(socket_path, 0o660)
        server.serve_forever(poll_interval=0.2)


def main() -> None:
    if os.geteuid() == 0:
        raise ValueError("intake gate must run as an unprivileged protected identity")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    fd = os.open(args.config, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 4096):
            raise ValueError("untrusted protected intake configuration")
        with os.fdopen(fd) as handle:
            fd = -1
            config = json.load(handle)
    finally:
        if fd != -1:
            os.close(fd)
    publication_loader = None
    if config.get("fresh_handoff_root"):
        from fresh_v1.protected import publication_plan_loader
        publication_loader = publication_plan_loader(Path(config["fresh_handoff_root"]))
    development_issuer = None
    development_inputs = None
    if config.get("development_grant_root"):
        send = _sidecar_preview_sender(config["sidecar_port"], config["sidecar_token"])
        passkeys = _owner_approval_config()
        development_issuer = DevelopmentGrantIssuer(
            Path(config["development_grant_root"]), owner_sender_id=config["owner_sender_id"],
            sidecar_uid=config["sidecar_uid"],
            preview_sender=_sidecar_preview_sender(config["sidecar_port"], config["sidecar_token"],
                                                   timeout=DEVELOPMENT_SEND_TIMEOUT),
            **({"channel_policy": passkeys["policy"], "owner_passkey_pin": passkeys["pin"]}
               if passkeys else {}))
        publication_issuer = PublicationApprovalIssuer(
            Path(config["development_grant_root"]), owner_sender_id=config["owner_sender_id"],
            sidecar_uid=config["sidecar_uid"], preview_sender=send,
            plan_verifier=publication_loader, delegation_policy=DELEGATION_POLICY,
            **({"channel_policy": passkeys["policy"], "owner_passkey_pin": passkeys["pin"],
                "alfred_os_uid": passkeys["uid"]} if passkeys else {}))
        development_inputs = lambda project, task: read_gateway_inputs(
            gateway_root=Path(config["gateway_root"]), gateway_state=Path(config["gateway_dir"]),
            project_id=project, task_id=task, registry_path=Path(config["registry_path"]))
    gate = IntakeGate(owner_sender_id=config["owner_sender_id"],
                      sidecar_uid=config["sidecar_uid"], hermes_uid=config["hermes_uid"],
                      intake_dir=Path(config["intake_dir"]),
                      gateway_dir=Path(config["gateway_dir"]),
                      preview_sender=_sidecar_preview_sender(config["sidecar_port"],
                                                             config["sidecar_token"]),
                      development_issuer=development_issuer,
                      development_inputs=development_inputs,
                      publication_issuer=publication_issuer if development_issuer else None,
                      registry_path=Path(config["registry_path"]),
                      request_route_root=Path(config["development_grant_root"]),
                      undo_issuer=UndoIssuer(Path(config["development_grant_root"]),
                                             owner_sender_id=config["owner_sender_id"],
                                             sidecar_uid=config["sidecar_uid"])
                      if development_issuer else None,
                      delegation_policy=DELEGATION_POLICY if development_issuer else None)
    if os.geteuid() in (gate.sidecar_uid, gate.hermes_uid):
        raise ValueError("gate identity must be distinct from both clients")
    if development_issuer is not None and passkeys:
        if passkeys["uid"] in (0, os.geteuid(), gate.sidecar_uid, gate.hermes_uid):
            raise ValueError("Alfred OS identity must differ from root, Intake, sidecar and Hermes")

        def development_request(offer):
            request = offer["request"]
            inputs = development_inputs(offer["project"], offer["task_id"])
            current = approval_request(inputs.spec_raw, inputs.plan_raw,
                project=offer["project"], task_id=offer["task_id"],
                repository=inputs.repository, worktree_root=Path(request["worktree_root"]),
                scope=request["scope"], spec_decoder=inputs.spec_decoder)
            plan = json.loads(inputs.plan_raw)
            return current, (inputs.plan_raw if plan.get("baseline_revision") else None)

        service = owner_approval.OwnerApprovals(
            Path(config["development_grant_root"]), development_issuer=development_issuer,
            publication_issuer=publication_issuer, development_request=development_request,
            alfred_os_uid=passkeys["uid"], pin_path=passkeys["pin"],
            notice_sender=_sidecar_preview_sender(config["sidecar_port"], config["sidecar_token"]))
        serve_owner_approvals(passkeys["socket"], service, passkeys["uid"])
    serve(Path(config["socket_path"]), gate)


OWNER_APPROVAL_SETTINGS = Path("/etc/alfred-development/owner-approval.json")
OWNER_APPROVAL_SCHEMA = "alfred.owner-approval-intake/1"
OWNER_APPROVAL_KEYS = ("owner_approval_socket", "alfred_os_uid", "owner_passkey_pin",
                       "approval_channel_policy")


def _owner_approval_config(path: Path | None = OWNER_APPROVAL_SETTINGS, *,
                           owner_uid: int = 0) -> dict | None:
    """Root-owned settings that turn on the Alfred OS listener. Absent: the Intake behaves
    exactly as before. Kept out of the Intake's own config, which its user can edit."""
    if path is None:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner_uid
                or info.st_mode & 0o022 or info.st_size > 1024):
            raise ValueError("owner approval settings are not root-protected")
        config = json.loads(stream.read())
    if (type(config) is not dict or set(config) != {"schema", *OWNER_APPROVAL_KEYS}
            or config["schema"] != OWNER_APPROVAL_SCHEMA
            or config["owner_approval_socket"] != "/run/alfred-development-intake/owner-approval.sock"
            or type(config["alfred_os_uid"]) is not int or config["alfred_os_uid"] < 1
            or config["owner_passkey_pin"] != str(PIN_PATH)
            or config["approval_channel_policy"] != str(owner_approval.CHANNEL_POLICY)):
        raise ValueError("owner approval settings invalid")
    return {"socket": Path(config["owner_approval_socket"]), "uid": config["alfred_os_uid"],
            "pin": Path(config["owner_passkey_pin"]),
            "policy": Path(config["approval_channel_policy"])}


if __name__ == "__main__":
    main()
