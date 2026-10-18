"""Allowlisted failure evidence. Never retain commands, exception text or output."""

import json
import subprocess

from .handoffs import Held

SCHEMA = "alfred.fresh-v1-worker-failure/1"
STAGES = {"plan", "developer", "qa", "reviewer", "prepare", "publish", "completion",
          "merge", "revert"}
PHASES = {
    "worker_startup",
    "worker_output",
    "policy_read",
    "job_read",
    "python",
    "github_main_lookup",
    "git_fetch",
    "git_ref_verify",
    "git_tree",
    "git_blob",
}
CATEGORIES = {
    "permission_denied",
    "read_only_filesystem",
    "unsafe_repository_ownership",
    "authentication_refused",
    "network_unavailable",
    "missing_object",
    "pam_session_refused",
    "timeout",
    "process_failed",
    "python_failed",
    "invalid_worker_result",
}


class WorkerFailure(Held):
    def __init__(self, evidence):
        self.evidence = evidence
        super().__init__(
            f"{evidence['stage']}: {evidence['phase']}/{evidence['category']}"
        )


def failure(stage, phase, exc):
    category = "python_failed"
    rc = None
    if isinstance(exc, subprocess.TimeoutExpired):
        category = "timeout"
    elif isinstance(exc, subprocess.CalledProcessError):
        rc = exc.returncode
        category = "process_failed"
        stderr = (exc.stderr or b"")[:65536]
        if isinstance(stderr, str):
            stderr = stderr.encode()
        stderr = stderr.lower()
        for needles, value in (
            ((b"runuser: cannot open session",), "pam_session_refused"),
            (
                (b"dubious ownership", b"unsafe repository"),
                "unsafe_repository_ownership",
            ),
            ((b"read-only file system",), "read_only_filesystem"),
            ((b"permission denied", b"permissionerror"), "permission_denied"),
            (
                (b"authentication failed", b"http 401", b"gh auth login"),
                "authentication_refused",
            ),
            (
                (b"could not resolve", b"error connecting", b"network is unreachable"),
                "network_unavailable",
            ),
            ((b"not a valid object", b"bad object", b"not our ref"), "missing_object"),
        ):
            if any(needle in stderr for needle in needles):
                category = value
                break
    elif isinstance(exc, OSError):
        category = {13: "permission_denied", 30: "read_only_filesystem"}.get(
            exc.errno, "python_failed"
        )
    return {
        "schema": SCHEMA,
        "stage": stage,
        "phase": phase,
        "category": category,
        "operation_returncode": rc,
        "errno": getattr(exc, "errno", None),
    }


def worker_failure(stage, exc):
    """Accept only a bounded, exact schema from the unprivileged worker."""
    result = failure(stage, "worker_startup", exc)
    raw = getattr(exc, "stderr", None) or b""
    if isinstance(raw, str):
        raw = raw.encode()
    # The role emits one small line. Arbitrary output remains private and discarded.
    if len(raw) <= 4096:
        try:
            row = json.loads(raw)
            if (
                type(row) is dict
                and set(row) == set(result)
                and row["schema"] == SCHEMA
                and row["stage"] == stage
                and row["phase"] in PHASES
                and row["category"] in CATEGORIES
                and all(
                    v is None or (type(v) is int and -255 <= v <= 255)
                    for v in (row["operation_returncode"], row["errno"])
                )
            ):
                result = row
        except (ValueError, TypeError):
            pass
    result["worker_returncode"] = getattr(exc, "returncode", None)
    return result


def planning_output(phase, args, *, timeout, env=None):
    try:
        return subprocess.check_output(
            args, stderr=subprocess.PIPE, timeout=timeout, env=env
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise WorkerFailure(failure("plan", phase, exc)) from None
