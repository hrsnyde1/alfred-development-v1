"""One append-only QA recovery for the confirmed T-0005 host setfacl EROFS failure.

The original QA attempt failed in root's preparation, before any QA worker was
dispatched (no qa-output exists): the Evidence sandbox kept the lab checkout
read-only. inspect is read-only; authorize writes only an operator decision.
Only the existing automatic handoff can run the single new QA attempt, reusing
the complete original root-built qa-input whose bytes this decision pins.
"""

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import time
from pathlib import Path

from .handoffs import Held, write_once
from .protected import protected_json

TARGET = ("dev-v1-accept", "T-0005")
DECISION = "qa.recovery.json"
ATTEMPT = "qa-recovery-1.attempt.json"
SCHEMA = "alfred.fresh-v1-qa-recovery/1"
INSPECTION = "alfred.fresh-v1-qa-recovery-inspection/1"
LIBRARY = Path("/usr/local/lib/alfred-fresh-v1/fresh_v1")
RUNTIME = (
    "host.py",
    "role.py",
    "handoffs.py",
    "protected.py",
    "diagnostics.py",
    "qa_recovery.py",
)
# The exact evidence left by the held original attempt, and nothing else.
BEFORE = {
    "context.json",
    "developer.attempt.json",
    "developer.result.json",
    "development-challenge.attempt.json",
    "development-challenge.result.json",
    "execution.json",
    "job.json",
    "plan.attempt.json",
    "plan.result.json",
    "qa.attempt.json",
    "qa-input",
    "worker-policy.json",
}
REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


def canonical(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Evidence:
    def __init__(
        self,
        policy_path,
        directory,
        *,
        uid=0,
        trusted_root=Path("/"),
        alfred_uid=None,
        library=LIBRARY,
    ):
        self.policy_path, self.directory = policy_path, directory
        self.uid, self.trusted_root, self.library = uid, trusted_root, library
        self.alfred_uid = (
            pwd.getpwnam("alfred").pw_uid if alfred_uid is None else alfred_uid
        )

    def protected(self, path):
        return protected_json(
            path, trusted_uid=self.uid, trusted_root=self.trusted_root
        )

    def owned(self, path, uid):
        from .host import read_owned

        return read_owned(path, uid)

    def tree(self, root):
        """Pinned bytes of the root-built QA input; links and other owners refused."""
        if root.is_symlink() or not root.is_dir() or root.lstat().st_uid != self.uid:
            raise Held("qa recovery: original QA input directory is not root's")
        found = {}
        for directory, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                path = Path(directory) / name
                if path.is_symlink():
                    raise Held("qa recovery: link inside original QA input")
            for name in files:
                path = Path(directory) / name
                found[str(path.relative_to(root))] = digest(self.owned(path, self.uid))
        if not found:
            raise Held("qa recovery: original QA input is empty")
        return found

    def core(self):
        p, policy_sha = self.protected(self.policy_path)
        job, job_sha = self.protected(self.directory / "job.json")
        original, attempt_sha = self.protected(self.directory / "qa.attempt.json")
        developed, developer_sha = self.protected(
            self.directory / "developer.result.json"
        )
        challenge, _ = self.protected(
            self.directory / "development-challenge.result.json"
        )
        if (
            (job.get("project"), job.get("task_id")) != TARGET
            or p.get("project") != TARGET[0]
            or p.get("schema") != "alfred.fresh-v1-policy/1"
            or p.get("enabled") is not True
            or self.directory != Path(p["jobs"]) / TARGET[0] / TARGET[1]
            or original != {"stage": "qa", "status": "uncertain_until_result"}
            or developed.get("state") != "ready_for_independent_qa"
            or (self.directory / "qa.result.json").exists()
            or (self.directory / "qa.failure.json").exists()
        ):
            raise Held("qa recovery: not the exact original held T-0005 QA attempt")
        reference = challenge.get("challenge")
        if not isinstance(reference, str) or not REFERENCE.fullmatch(reference):
            raise Held("qa recovery: development approval reference missing")
        grants = Path(p["grant_root"])
        claim_raw = self.owned(grants / f"execution-{reference}.json", self.alfred_uid)
        result_raw = self.owned(
            grants / f"execution-result-{reference}.json", self.alfred_uid
        )
        claim, outcome = json.loads(claim_raw), json.loads(result_raw)
        if (
            (claim.get("project"), claim.get("task_id")) != TARGET
            or outcome.get("status") != "completed"
            or outcome.get("claim_sha256") != digest(claim_raw)
        ):
            raise Held("qa recovery: Developer grant was not claimed and completed")
        bindings = {
            "job_sha256": job_sha,
            "original_attempt_sha256": attempt_sha,
            "developer_result_sha256": developer_sha,
            "execution_claim_sha256": digest(claim_raw),
            "execution_result_sha256": digest(result_raw),
            "policy_sha256": policy_sha,
            "qa_input_sha256": self.tree(self.directory / "qa-input"),
            "runtime_sha256": {
                n: digest(self.owned(self.library / n, self.uid)) for n in RUNTIME
            },
        }
        return bindings

    def inspection(self, bindings):
        return {
            "schema": INSPECTION,
            "project": TARGET[0],
            "task_id": TARGET[1],
            "bindings": bindings,
        }

    def before(self, *, include_decision=False):
        bindings = self.core()
        allowed = BEFORE | ({DECISION} if include_decision else set())
        names = {path.name for path in self.directory.iterdir()}
        if names != allowed:
            # qa-output would mean a QA worker was dispatched: never recover that.
            raise Held(
                "qa recovery: additional handoff evidence requires investigation: "
                + ", ".join(sorted(names ^ allowed))
            )
        return self.inspection(bindings)

    def verify(self, now=None):
        now = time.time() if now is None else now
        record, _ = self.protected(self.directory / DECISION)
        if (
            set(record)
            != {
                "schema",
                "project",
                "task_id",
                "decision",
                "reason",
                "operator_reference",
                "created_at",
                "expires_at",
                "inspection_sha256",
                "bindings",
            }
            or record.get("schema") != SCHEMA
            or (record.get("project"), record.get("task_id")) != TARGET
            or record.get("decision") != "one_new_qa_attempt_only"
            or record.get("reason") != "confirmed_host_setfacl_erofs_before_qa_dispatch"
            or not isinstance(record.get("operator_reference"), str)
            or not REFERENCE.fullmatch(record["operator_reference"])
            or any(
                type(record.get(k)) not in (int, float)
                for k in ("created_at", "expires_at")
            )
            or record["expires_at"] != record["created_at"] + 3600
        ):
            raise Held("qa recovery: invalid operator decision")
        bindings = self.core()
        if (
            bindings != record["bindings"]
            or digest(canonical(self.inspection(bindings)))
            != record["inspection_sha256"]
        ):
            raise Held("qa recovery: pinned task, policy, runtime or evidence changed")
        attempted = self.directory / ATTEMPT
        if not attempted.exists():
            if not record["created_at"] <= now <= record["expires_at"]:
                raise Held(
                    "qa recovery: unused operator decision expired or is future-dated"
                )
            report = self.before(include_decision=True)
            if digest(canonical(report)) != record["inspection_sha256"]:
                raise Held("qa recovery: pre-dispatch inspection differs")
        else:
            attempt, _ = self.protected(attempted)
            if attempt != {"stage": "qa-recovery-1", "status": "uncertain_until_result"}:
                raise Held("qa recovery: new attempt record differs")
        return True


def verify(policy_path, directory):
    return Evidence(policy_path, directory).verify()


def authorize(evidence, inspection_sha256, operator_reference, *, now=None):
    now = time.time() if now is None else now
    policy, _ = evidence.protected(evidence.policy_path)
    if not (Path(policy["gateway_state"]) / "PAUSE").is_file():
        raise Held("qa recovery: operator PAUSE required")
    if (evidence.directory / DECISION).exists():
        raise Held("qa recovery: operator decision already exists; never renew")
    report = evidence.before()
    if digest(canonical(report)) != inspection_sha256:
        raise Held("qa recovery: inspection pin differs")
    if not isinstance(operator_reference, str) or not REFERENCE.fullmatch(
        operator_reference
    ):
        raise Held("qa recovery: explicit operator decision reference required")
    write_once(
        evidence.directory / DECISION,
        {
            "schema": SCHEMA,
            "project": TARGET[0],
            "task_id": TARGET[1],
            "decision": "one_new_qa_attempt_only",
            "reason": "confirmed_host_setfacl_erofs_before_qa_dispatch",
            "operator_reference": operator_reference,
            "created_at": now,
            "expires_at": now + 3600,
            "inspection_sha256": inspection_sha256,
            "bindings": report["bindings"],
        },
    )


def main():
    if os.geteuid() != 0:
        raise PermissionError("existing privileged operator boundary required")
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inspect", "verify", "authorize"))
    parser.add_argument("--inspection-sha256")
    parser.add_argument("--operator-reference")
    args = parser.parse_args()
    p = Path("/etc/alfred-fresh-v1/policy.json")
    evidence = Evidence(p, Path("/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0005"))
    if args.action == "inspect":
        report = canonical(evidence.before())
        print(report.decode(), end="")
        print(json.dumps({"inspection_sha256": digest(report)}))
    elif args.action == "verify":
        evidence.verify()
        print('{"status":"QA_RECOVERY_EVIDENCE_VERIFIED_NO_EXECUTION"}')
    else:
        # Existing poll lock only; never create/replace task attempts or invoke a role.
        fd = os.open(
            evidence.directory.parent.parent / ".poll.lock", os.O_RDWR | os.O_NOFOLLOW
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            authorize(evidence, args.inspection_sha256, args.operator_reference)
        finally:
            os.close(fd)
        print('{"status":"ONE_QA_RECOVERY_AUTHORIZED_HELD"}')


if __name__ == "__main__":
    main()
