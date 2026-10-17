"""The fixed V1 stage handoffs, called by the existing privileged evidence poll.

Each external attempt is recorded before dispatch. An interrupted attempt is held,
never retried automatically. Workers, approvals and transports remain existing ports.
"""

import json
import os
from pathlib import Path


class Held(RuntimeError):
    pass


def write_once(path: Path, obj: dict):
    raw = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def once(directory, name, action):
    finished, attempted = (
        directory / (name + ".result.json"),
        directory / (name + ".attempt.json"),
    )
    if finished.exists():
        return json.loads(finished.read_bytes())
    if attempted.exists():
        raise Held(name + ": previous attempt requires reconciliation")
    write_once(attempted, {"stage": name, "status": "uncertain_until_result"})
    result = action()
    if type(result) is not dict:
        raise Held(name + ": invalid stage result")
    write_once(finished, result)
    return result


def advance(directory: Path, job: dict, io):
    """Only this literal chain is permitted. No dynamic command/stage selection."""
    try:
        if (directory / "plan.recovery.json").exists():
            # Exactly one separately authorized incident recovery. No generic retry.
            io.verify_plan_recovery(job)
            context = once(directory, "plan-recovery-1", lambda: io.plan(job))
            io.verify_plan_recovery(job)
        else:
            context = once(directory, "plan", lambda: io.plan(job))
        job = {**job, **context}
        challenge = once(
            directory, "development-challenge", lambda: io.development_challenge(job)
        )
        grant = io.development_grant(job, challenge["challenge"])
        if grant is None:
            return {"state": "awaiting_development_approval"}
        job["grant_reference"] = grant["reference"]
        developed = once(directory, "developer", lambda: io.developer(job))
        if developed.get("state") != "ready_for_independent_qa":
            raise Held("developer did not produce a completed handoff")
        if (directory / "qa.recovery.json").exists():
            # Exactly one separately authorized incident recovery. No generic retry.
            io.verify_qa_recovery(job)
            qa = once(directory, "qa-recovery-1", lambda: io.qa(job))
            io.verify_qa_recovery(job)
        else:
            qa = once(directory, "qa", lambda: io.qa(job))
        if qa.get("decision") != "PASS":
            raise Held("independent QA did not pass")
        review = once(directory, "reviewer", lambda: io.reviewer(job))
        if review.get("decision") != "APPROVED":
            raise Held("independent Reviewer did not approve")
        if review.get("findings") != []:
            raise Held("independent Reviewer findings require resolution")
        publication = once(
            directory, "publication-plan", lambda: io.publication_plan(job)
        )
        job["publication"] = publication
        challenge = once(
            directory, "publication-challenge", lambda: io.publication_challenge(job)
        )
        authorization = io.publication_authorization(job, challenge["challenge"])
        if authorization is None:
            return {"state": "awaiting_publication_approval"}
        job["authorization_path"] = authorization["path"]
        result = once(directory, "publisher", lambda: io.publish(job))
        if result.get("status") != "PUBLISHED_DRAFT":
            raise Held(
                "Publisher success is unverified; publication investigation required"
            )
        notice = once(directory, "completion", lambda: io.completion(job))
        if notice.get("status") not in {"sent", "already_sent"}:
            raise Held("completion delivery requires reconciliation")
        return {
            "state": "complete",
            "draft_pr_url": result["draft_pr_url"],
            "notification": notice["status"],
        }
    except Exception as exc:  # noqa: BLE001 - durable fail-closed stage boundary
        # Preserve attempted operations. Do not expose model/credential exception text.
        return {
            "state": "held",
            "reason": str(exc) if isinstance(exc, Held) else type(exc).__name__,
        }
