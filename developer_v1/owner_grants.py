"""Protected development grants from Photon SDK observations.

The intake identity owns this store. Neither Hermes nor a developer worker may
write it. A fixture authority lives only in tests and is never accepted here.
"""

from __future__ import annotations

import ctypes
import datetime as dt
import errno
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

# The owner's standing delegation. Only root (the owner, via sudo) writes it, so no
# model, Hermes or worker identity can widen it. Absent means every development
# approval goes to the owner's phone exactly as before.
DELEGATION_POLICY = Path("/etc/alfred-development/delegation.json")
DELEGATION_SCHEMA = "alfred.development-delegation-policy/1"
PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
# Automatic fix rounds after QA or the Reviewer found problems (owner's choice).
MAX_FIX_ROUNDS = 3


def _round_name(reference: str, fix_round: int) -> str:
    """Round 0 keeps the original record names; fix rounds add -r<n>."""
    return f"{reference}.json" if fix_round == 0 else f"{reference}-r{fix_round}.json"


OWNER_SOURCE = "photon_native_owner_reply"
DELEGATED_SOURCE = "delegated_owner_policy"
# The owner's passkey, verified by V1 itself (owner_approval.py); see that module.
PASSKEY_SOURCE = "alfred_os_owner_passkey"


def load_delegation_policy(path: Path | None, *, owner_uid: int) -> dict | None:
    """The validated policy, or None when absent. Anything malformed is refused."""
    if path is None:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Denied("development delegation policy unreadable") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner_uid
                or info.st_mode & 0o022 or info.st_size > 4096):
            raise Denied("development delegation policy is not owner-protected")
        try:
            policy = json.loads(stream.read())
        except ValueError as exc:
            raise Denied("development delegation policy is not JSON") from exc
    development = policy.get("development_approval") if type(policy) is dict else None
    projects = development.get("projects") if type(development) is dict else None
    if (type(policy) is not dict
            or set(policy) - {"merge_approval"} != {"schema", "development_approval",
                                                     "publication_approval"}
            or policy["schema"] != DELEGATION_SCHEMA
            # "owner": the owner answers a second text before every draft PR. "delegated"
            # (owner-authorized 2026-10-18): the owner's "yes" to the request preview also
            # approves its draft PR for the same listed projects only.
            or policy["publication_approval"] not in ("owner", "delegated")
            # Absent or "owner": the owner merges. "delegated" (owner-authorized
            # 2026-10-18, handoff.31): after QA and the Reviewer pass, the pipeline
            # squash-merges the draft PR itself; the owner can reply "undo" for 24 hours.
            or policy.get("merge_approval", "owner") not in ("owner", "delegated")
            or set(development) != {"enabled", "projects"}
            or type(development["enabled"]) is not bool
            or type(projects) is not list or len(projects) != len(set(projects))
            or any(type(p) is not str or not PROJECT_ID.fullmatch(p) for p in projects)):
        raise Denied("development delegation policy invalid")
    return policy


def _policy_path(path: Path | None, environment: str) -> Path | None:
    # Staging never reads the host policy implicitly; a fixture names its own.
    return path if path is not None else (DELEGATION_POLICY if environment == "host" else None)


def _policy_owner(environment: str) -> int:
    # On the host only root may own the policy; staging fixtures are the test user's.
    return 0 if environment == "host" else os.geteuid()


def delegation_permits(policy: dict | None, project: str) -> bool:
    """Only explicitly listed registered projects; never a wildcard."""
    return (policy is not None and policy["development_approval"]["enabled"]
            and project in policy["development_approval"]["projects"])


def publication_delegation_permits(policy: dict | None, project: str) -> bool:
    """A draft PR without a second owner text: only where development is delegated too."""
    return (delegation_permits(policy, project)
            and policy["publication_approval"] == "delegated")


def merge_delegation_permits(policy: dict | None, project: str) -> bool:
    """A squash merge without the owner: only where the draft PR is delegated too."""
    return (publication_delegation_permits(policy, project)
            and policy.get("merge_approval", "owner") == "delegated")


class DevelopmentSendFailure(OSError):
    """Only the protected transport may classify a send; no raw provider text."""

    def __init__(self, delivery_state: str, reason_code: str):
        if delivery_state not in {"not_attempted", "uncertain"} or reason_code not in {
            "connect_failed", "http_preflight_refused", "provider_refused",
            "http_failed", "ack_timeout", "ack_invalid", "intent_unavailable",
        }:
            raise ValueError("invalid development send outcome")
        self.delivery_state, self.reason_code = delivery_state, reason_code
        super().__init__("development challenge send " + reason_code)


def _send_slot(request: dict) -> str:
    # An exact task may be attempted once. Changing its plan/DM cannot bypass it.
    return "development-send-" + _digest({
        "project": request["project"], "task_id": request["task_id"],
    }) + ".json"


def _delegation_slot(request: dict) -> str:
    return "development-delegation-" + _digest({
        "project": request["project"], "task_id": request["task_id"],
    }) + ".json"


def _bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: dict | bytes) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else _bytes(value)).hexdigest()


def _phrase(request: dict) -> str:
    return f"Approve development {request['project']} {request['task_id']} {request['plan_sha256'][:12]}"


def _challenge_text(request: dict, plan_raw: bytes | None = None) -> str:
    summary = ""
    if plan_raw is not None:
        if type(plan_raw) is not bytes or len(plan_raw) > 32768 or _digest(plan_raw) != request["plan_sha256"]:
            raise Denied("development challenge plan differs from canonical binding")
        plan = json.loads(plan_raw)
        if (type(plan) is not dict or any(plan.get(k) != request[k] for k in
                ("project", "task_id", "repository", "spec_sha256"))):
            raise Denied("development challenge plan identity mismatch")
        def excerpt(name, limit):
            value = str(plan.get(name, ""))
            return value if len(value) <= limit else value[:limit] + "… (full plan bound by SHA-256)"
        summary = (f"CTO goal: {excerpt('objective', 700)}\n"
                   f"Approach: {excerpt('implementation_approach', 500)}\n"
                   f"Baseline: {plan.get('baseline_revision', 'not specified')}\n"
                   f"Acceptance criteria:\n{excerpt('acceptance_criteria', 1000)}\n")
    return (f"Development execution approval\nProject/task: {request['project']} / {request['task_id']}\n"
            f"Plan SHA-256: {request['plan_sha256']}\nRepository: {request['repository']}\n"
            f"Scope: {', '.join(request['scope'])}\nSpecialists: {', '.join(request['specialists'])}\n"
            + summary +
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


def _rename_noreplace(directory: int, source: str, destination: str) -> None:
    """Publish exactly once without exposing a hard link to the Gateway reader."""
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable") from None
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                       ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(directory, os.fsencode(source), directory, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), destination)



def _write_delivery_record(root: Path, name: str, value: dict) -> None:
    """A private ACK/index is visible only after its complete bytes are fsynced."""
    _protected(root)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = f".{name}.{uuid.uuid4().hex}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        _rename_noreplace(directory, temporary, name)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
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
    if "plan_raw" in receipt and type(receipt["plan_raw"]) is not str:
        raise Denied("development challenge plan bytes invalid")
    if (receipt.get("schema") != "alfred.development-challenge/1"
            or receipt.get("reference") != reference or receipt.get("request") != request
            or not isinstance(receipt.get("owner_id"), str) or not receipt["owner_id"]
            or not isinstance(receipt.get("space_id"), str) or not receipt["space_id"]
            or not isinstance(receipt.get("message_id"), str) or not receipt["message_id"]
            or not isinstance(receipt.get("issued_at"), (int, float))
            or receipt.get("expires_at") != receipt["issued_at"] + MAX_AGE
            or receipt.get("challenge_text_sha256") != _digest(_challenge_text(request,
                receipt["plan_raw"].encode() if "plan_raw" in receipt else None).encode())
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


def _verify_delegation(root: Path, reference: str, grant: dict, expected: dict,
                       policy: dict | None) -> None:
    """A delegated grant executes only while the owner's policy still permits it."""
    try:
        record = _read(root, f"delegation-{reference}.json")
        issuance = _read(root, f"issuance-{reference}.json")
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise Denied("delegated grant lacks trusted delegation evidence") from exc
    request = {"schema": "alfred.development-approval-request/1",
               **{key: value for key, value in expected.items() if key != "schema"},
               "state": "pending_owner_decision"}
    if (record.get("schema") != "alfred.development-delegated-decision/1"
            or record.get("reference") != reference or record.get("request") != request
            or record.get("decision") != "approve_development"
            or record.get("decided_by") != "owner_delegation_policy"
            or type(record.get("policy")) is not dict
            or record.get("policy_sha256") != _digest(record["policy"])
            or not delegation_permits(record["policy"], request["project"])
            or not isinstance(record.get("owner_id"), str) or not record["owner_id"]
            or not isinstance(record.get("space_id"), str) or not record["space_id"]
            or not isinstance(record.get("decided_at"), (int, float))
            or grant.get("delegation_sha256") != _digest(record)):
        raise Denied("delegation record does not bind canonical approval")
    if not delegation_permits(policy, request["project"]):
        raise Denied("owner delegation policy no longer permits this project")
    if (set(issuance) != {"schema", "reference", "grant_sha256", "delegation_sha256",
                         "policy_sha256", "bundle_sha256", "issued_at"}
            or issuance.get("schema") != "alfred.development-delegated-issuance/1"
            or issuance.get("reference") != reference
            or issuance.get("grant_sha256") != _digest(grant)
            or issuance.get("delegation_sha256") != _digest(record)
            or issuance.get("policy_sha256") != record["policy_sha256"]
            or issuance.get("bundle_sha256") != _digest(_bytes(grant) + _bytes(record))
            or issuance.get("issued_at") != record["decided_at"]):
        raise Denied("delegated issuance digest does not match immutable evidence")


class _DelegatedDecision:
    """The owner's standing policy, not a reply; recorded as exactly that."""

    def __init__(self, reference: str, owner: str):
        self.reference, self.owner = reference, owner

    def verify(self, reference: str, expected: dict) -> dict:
        if reference != self.reference:
            raise Denied("delegation reference mismatch")
        return {**expected, "owner": self.owner, "decision": "approve_development",
                "source": "independent_owner_channel", "reference": reference}


def _pin_path(path: Path | None, environment: str) -> Path | None:
    # Like the delegation policy: staging never reads the host pin implicitly.
    from .owner_passkey import PIN_PATH
    return path if path is not None else (PIN_PATH if environment == "host" else None)


class ProtectedDevelopmentAuthority:
    def __init__(self, root: Path, *, clock=time.time, environment: str = "host",
                 delegation_policy: Path | None = None, owner_passkey_pin: Path | None = None):
        if environment not in {"host", "staging"}:
            raise Denied("invalid grant environment")
        self.root = root
        self.clock = clock
        self.environment = environment
        self.delegation_policy = _policy_path(delegation_policy, environment)
        self.owner_passkey_pin = _pin_path(owner_passkey_pin, environment)
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
                or grant.get("state") != "approved"
                or grant.get("source") not in {OWNER_SOURCE, DELEGATED_SOURCE, PASSKEY_SOURCE}
                or grant.get("environment") != self.environment
                or set(grant.get("permissions", [])) != PERMISSIONS
                or any(grant.get(k) != v for k, v in expected.items())):
            raise Denied("development grant binding mismatch")
        if not isinstance(grant.get("expires_at"), (int, float)) or self.clock() >= grant["expires_at"]:
            raise Denied("development grant expired")
        if (self.root / f"revoke-{reference}").exists():
            raise Denied("development grant revoked")
        if grant["source"] == DELEGATED_SOURCE:
            _verify_delegation(self.root, reference, grant, expected, load_delegation_policy(
                self.delegation_policy, owner_uid=_policy_owner(self.environment)))
        elif grant["source"] == PASSKEY_SOURCE:
            # Re-verifies the stored signature against the root pin on every verify().
            from .owner_approval import verify_development_evidence
            verify_development_evidence(self.root, reference, grant, expected,
                                        self.owner_passkey_pin, _policy_owner(self.environment))
        else:
            _verify_evidence(self.root, reference, grant, expected)
        return grant

    def claim(self, reference: str, expected: dict, *, run_sha256: str,
              fix_round: int = 0) -> dict:
        """Durably consume one grant before any worktree or model operation.

        Round 0 is the approved development. Fix rounds 1 to MAX_FIX_ROUNDS redo the
        same approved work after QA or the Reviewer found problems: same plan, scope
        and specialists, each round claimed once and only after the previous round
        completed."""
        grant = self.verify(reference, expected)
        if not isinstance(run_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", run_sha256):
            raise Denied("invalid execution request digest")
        if type(fix_round) is not int or not 0 <= fix_round <= MAX_FIX_ROUNDS:
            raise Denied("invalid fix round")
        if fix_round:
            try:
                previous = _read(self.root, "execution-result-" + _round_name(reference, fix_round - 1))
            except (FileNotFoundError, OSError, ValueError) as exc:
                raise Denied("previous round has no recorded outcome") from exc
            if previous.get("status") != "completed":
                raise Denied("previous round did not complete")
        record = {"schema": "alfred.development-execution-claim/1",
                  "reference": reference, "project": grant["project"],
                  "task_id": grant["task_id"], "grant_sha256": _digest(grant),
                  "run_sha256": run_sha256, "claimed_at": self.clock(),
                  "status_if_no_result": "uncertain"}
        try:
            _write_once(self.root, "execution-" + _round_name(reference, fix_round), record)
        except FileExistsError as exc:
            raise Denied("development grant already consumed") from exc
        return record

    def finish(self, reference: str, *, status: str, fix_round: int = 0) -> None:
        if (not isinstance(reference, str) or not REF.fullmatch(reference)
                or status not in {"completed", "failed", "uncertain"}
                or type(fix_round) is not int or not 0 <= fix_round <= MAX_FIX_ROUNDS):
            raise Denied("invalid execution terminal status")
        name = _round_name(reference, fix_round)
        claim = _read(self.root, f"execution-{name}")
        try:
            _write_once(self.root, f"execution-result-{name}", {
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
                 environment: str = "host", delegation_policy: Path | None = None,
                 channel_policy: Path | None = None, owner_passkey_pin: Path | None = None):
        _protected(root)
        self.root, self.owner, self.send = root, owner_sender_id, preview_sender
        if environment not in {"host", "staging"}:
            raise Denied("invalid grant environment")
        if sidecar_uid == admin_uid:
            raise Denied("Photon and administrator identities must differ")
        self.clock, self.admin_uid, self.sidecar_uid = clock, admin_uid, sidecar_uid
        self.environment = environment
        self.delegation_policy = _policy_path(delegation_policy, environment)
        from .owner_approval import CHANNEL_POLICY
        self.channel_policy = (channel_policy if channel_policy is not None
                               else (CHANNEL_POLICY if environment == "host" else None))
        self.owner_passkey_pin = _pin_path(owner_passkey_pin, environment)
        self._lock = threading.Lock()

    def _delegate(self, request: dict, space_id: str, policy: dict) -> dict:
        """Issue a grant under the owner's standing policy. Nothing is sent and no
        owner reply is fabricated: the evidence says the policy decided."""
        # One decision per task, whether by the owner or by delegation.
        try:
            _write_once(self.root, _delegation_slot(request), {
                "schema": "alfred.development-delegation-attempt/1",
                "project": request["project"], "task_id": request["task_id"]})
        except FileExistsError as exc:
            raise Denied("development delegation already attempted for this task") from exc
        reference = uuid.uuid4().hex
        now = self.clock()
        record = {"schema": "alfred.development-delegated-decision/1",
                  "reference": reference, "request": request,
                  "decision": "approve_development", "decided_by": "owner_delegation_policy",
                  "policy": policy, "policy_sha256": _digest(policy),
                  "owner_id": self.owner, "space_id": space_id, "decided_at": now}
        _write_once(self.root, f"delegation-{reference}.json", record)
        grant = stage_owner_transition(
            request, decision_reference=reference, expected_owner=self.owner,
            verifier=_DelegatedDecision(reference, self.owner), grant_reference=reference)
        grant.update({"source": DELEGATED_SOURCE, "delegation_sha256": _digest(record),
                      "expires_at": now + 86400, "environment": self.environment,
                      "permissions": sorted(PERMISSIONS)})
        _write_once(self.root, f"issuance-{reference}.json", {
            "schema": "alfred.development-delegated-issuance/1", "reference": reference,
            "grant_sha256": _digest(grant), "delegation_sha256": _digest(record),
            "policy_sha256": record["policy_sha256"],
            "bundle_sha256": _digest(_bytes(grant) + _bytes(record)), "issued_at": now})
        _write_once(self.root, f"grant-{reference}.json", grant)
        # `challenge` keeps the host's existing stage contract: it names the grant.
        return {"state": "development_approved_by_delegation", "challenge": reference,
                "reference": reference}

    def _ack_pending(self):
        """Index durable acknowledgements if interrupted before pending indexing.

        Legacy receipts without a send intent are never adopted this way. This
        reads a genuine native ID; it does not send or create approval evidence.
        """
        result = []
        for path in self.root.glob("challenge-*.json"):
            receipt = _read(self.root, path.name)
            reference = path.stem.removeprefix("challenge-")
            if ("send_attempt_sha256" not in receipt
                    or (self.root / f"pending-{reference}.json").exists()
                    or (self.root / f"decision-{reference}.json").exists()
                    or (self.root / f"expired-{reference}.json").exists()):
                continue
            attempt = _read(self.root, _send_slot(receipt["request"]))
            expected = {k: v for k, v in receipt.items()
                        if k not in {"schema", "message_id", "send_attempt_sha256"}}
            if (attempt != {**expected, "schema": "alfred.development-send-attempt/1",
                            "delivery_state": "uncertain_until_ack"}
                    or receipt.get("schema") != "alfred.development-challenge/1"
                    or _digest(attempt) != receipt["send_attempt_sha256"]
                    or receipt.get("reference") != reference
                    or receipt.get("owner_id") != self.owner
                    or type(receipt.get("message_id")) is not str
                    or not 1 <= len(receipt["message_id"]) <= 200
                    or receipt.get("expires_at") != receipt["issued_at"] + MAX_AGE
                    or receipt.get("challenge_text_sha256") != _digest(_challenge_text(
                        receipt["request"], receipt["plan_raw"].encode() if "plan_raw" in receipt else None).encode())
                    or receipt.get("phrase_sha256") != _digest(_phrase(receipt["request"]).encode())):
                raise Denied("development send acknowledgement binding mismatch")
            result.append((None, {
                "request": receipt["request"], "space_id": receipt["space_id"],
                "message_id": receipt["message_id"],
                "phrase": _phrase(receipt["request"]), "created_at": receipt["issued_at"],
                "reference": reference,
            }))
        return result

    def stage(self, request: dict, *, space_id: str, peer_uid: int, plan_raw: bytes | None = None,
              channel: str | None = None, title: str | None = None) -> dict:
        """channel: "imessage" sends today's challenge text; "alfred_os" records an offer
        for the owner's passkey in Alfred OS and sends nothing. None: the root policy."""
        if peer_uid != self.admin_uid or not isinstance(space_id, str) or not space_id:
            raise Denied("development approval staging requires protected administrator")
        if (request.get("schema") != "alfred.development-approval-request/1"
                or request.get("state") != "pending_owner_decision"
                or not all(k in request for k in BOUND_FIELDS if k != "schema")):
            raise Denied("invalid development approval request")
        # This method is called only after the Gateway adapter and canonical
        # binding recompute the request; raw client-supplied requests are refused
        # by the intake extension.
        from . import owner_approval
        with self._lock:
            if ((self.root / _send_slot(request)).exists()
                    or (self.root / _delegation_slot(request)).exists()
                    or (self.root / owner_approval._offer_slot(request["project"],
                                                              request["task_id"])).exists()):
                raise Denied("development challenge already attempted; reconciliation required")
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
            if (any(self.root.glob("pending-*.json"))
                    or any(self.clock() <= p["created_at"] + MAX_AGE
                           for _, p in self._ack_pending())
                    or owner_approval.open_offers(self.root, "development", self.clock())):
                raise Denied("another development approval is pending")
            for path in self.root.glob("grant-*.json"):
                old = _read(self.root, path.name)
                old_reference = path.stem.removeprefix("grant-")
                if (old.get("project") == request["project"]
                        and old.get("task_id") == request["task_id"]
                        and not (self.root / f"revoke-{old_reference}").exists()):
                    raise Denied("existing task grant must be revoked before restaging")
            policy = load_delegation_policy(self.delegation_policy,
                                            owner_uid=_policy_owner(self.environment))
            if delegation_permits(policy, request["project"]):
                return self._delegate(request, space_id, policy)
            if owner_approval.resolve_channel(channel, self.channel_policy,
                                              owner_uid=_policy_owner(self.environment)) == "alfred_os":
                return self._offer(request, space_id, plan_raw, title)
            challenge = uuid.uuid4().hex
            phrase = _phrase(request)
            message = _challenge_text(request, plan_raw)
            if len(message) > 4000:
                raise Denied("development approval challenge too large")
            issued_at = self.clock()
            receipt = {
                "schema": "alfred.development-challenge/1", "reference": challenge,
                "request": request, "owner_id": self.owner, "space_id": space_id,
                "message_id": "M" * 200, "issued_at": issued_at,
                "expires_at": issued_at + MAX_AGE,
                "challenge_text_sha256": _digest(message.encode()),
                "phrase_sha256": _digest(phrase.encode()),
                **({"plan_raw": plan_raw.decode()} if plan_raw is not None else {})}
            attempt = {k: v for k, v in receipt.items() if k != "message_id"}
            attempt.update(schema="alfred.development-send-attempt/1",
                           delivery_state="uncertain_until_ack")
            receipt["send_attempt_sha256"] = _digest(attempt)
            # The existing evidence reader is bounded to 16 KiB. Validate the
            # complete receipt before a send, reserving timestamp encoding room.
            if len(_bytes(receipt)) > 16300:
                raise Denied("development approval evidence too large")
            try:
                _write_once(self.root, _send_slot(request), attempt)
            except FileExistsError as exc:
                raise Denied("development challenge already attempted; reconciliation required") from exc
            except (OSError, Denied) as exc:
                raise DevelopmentSendFailure("not_attempted", "intent_unavailable") from exc
            try:
                message_id = self.send(space_id, message)
                if not isinstance(message_id, str) or not 1 <= len(message_id) <= 200:
                    raise DevelopmentSendFailure("uncertain", "ack_invalid")
            except (OSError, ValueError, Denied) as exc:
                _write_once(self.root, f"development-send-outcome-{challenge}.json", {
                    "schema": "alfred.development-send-outcome/1", "reference": challenge,
                    "send_attempt_sha256": _digest(attempt), "recorded_at": self.clock(),
                    "delivery_state": exc.delivery_state if isinstance(exc, DevelopmentSendFailure) else "uncertain",
                    "reason_code": exc.reason_code if isinstance(exc, DevelopmentSendFailure) else "unclassified",
                })
                raise
            # Native replies may arrive while Photon is returning its ACK. Pin
            # lifetime to dispatch, never to the later ACK or restart time.
            receipt.update(message_id=message_id)
            _write_delivery_record(self.root, f"challenge-{challenge}.json", receipt)
            _write_delivery_record(self.root, f"pending-{challenge}.json", {
                "request": request, "space_id": space_id, "message_id": message_id,
                "phrase": phrase, "created_at": issued_at,
            })
            return {"state": "awaiting_native_owner_reply", "challenge": challenge,
                    "message_id": message_id}

    def _offer(self, request: dict, space_id: str, plan_raw: bytes | None,
               title: str | None) -> dict:
        """An Alfred OS offer: nothing is sent and no reply is awaited."""
        from . import owner_approval
        from .owner_passkey import NotPinned, load_pin
        try:
            load_pin(self.owner_passkey_pin, owner_uid=_policy_owner(self.environment))
        except NotPinned as exc:
            raise Denied("Alfred OS approvals need the root-pinned owner passkey") from exc
        if plan_raw is not None:
            _challenge_text(request, plan_raw)  # the same plan checks as the iMessage text
        return owner_approval.write_offer(
            self.root, kind="development", project=request["project"],
            task_id=request["task_id"], title=title, owner_id=self.owner,
            space_id=space_id, now=self.clock(),
            body={"request": request, **({"plan_raw": plan_raw.decode()}
                                         if plan_raw is not None else {})})

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
            matches.extend((path, pending) for path, pending in self._ack_pending()
                           if pending["message_id"] == target)
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
            reference = path.stem.removeprefix("pending-") if path is not None else pending["reference"]
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
            if path is not None:
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

