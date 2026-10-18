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


MAX_FIX_ROUNDS = 3
MAX_PUBLISH_RETRIES = 3
FINDING = 300


def _line(text):
    text = " ".join(str(text).split())
    return text if len(text) <= FINDING else text[: FINDING - 1] + "…"


def qa_findings(qa):
    """What Independent QA found wrong, as short lines for the developers."""
    lines = [
        _line(f"{f.get('requirement')}: {f.get('detail')}")
        for f in qa.get("findings") or []
        if isinstance(f, dict) and f.get("severity") != "info"
    ]
    lines += [
        _line(f"check {t.get('check') or t.get('name')} did not pass: "
              f"{t.get('output_excerpt') or t.get('evidence') or t.get('result')}")
        for t in qa.get("tests") or []
        if isinstance(t, dict) and t.get("result") != "PASS"
    ]
    lines += [
        _line(f"acceptance criterion not met: {c.get('criterion')}")
        for c in qa.get("acceptance_criteria") or []
        if isinstance(c, dict) and c.get("result") != "PASS"
    ]
    return lines[:12] or ["Independent QA did not pass; re-check every acceptance criterion."]


def review_findings(review):
    """What the independent Reviewer asked to change, as short lines."""
    lines = [
        _line(f"{f.get('requirement')}: {f.get('detail')}")
        for f in review.get("findings") or []
        if isinstance(f, dict) and f.get("severity") != "info"
    ]
    lines += [
        _line(f"acceptance criterion not covered: {c.get('criterion')} ({c.get('evidence')})")
        for c in review.get("acceptance_coverage") or []
        if isinstance(c, dict) and c.get("result") != "PASS"
    ]
    return lines[:12] or ["The Reviewer did not approve; address correctness and scope."]


def started(directory, name):
    """Whether this stage was ever attempted (its outcome then decides, never a retry)."""
    return any(
        (directory / (name + suffix)).exists()
        for suffix in (".attempt.json", ".result.json")
    )


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


def recorded(directory, name, action):
    """An idempotent step's answer, recorded once. Unlike once(), a step that never
    answered is simply asked again: it only reads or writes its own idempotent record."""
    finished = directory / (name + ".result.json")
    if finished.exists():
        return json.loads(finished.read_bytes())
    result = action()
    if type(result) is not dict:
        raise Held(name + ": invalid stage result")
    write_once(finished, result)
    return result


def reviewer_blocker(review) -> str | None:
    """Why a recorded Reviewer result may not advance to draft PR preparation, or None.

    Informational findings never block, but they also never override anything else:
    the decision, correctness, scope and every acceptance criterion must all pass, and
    any finding that is not exactly severity "info" (warning, error, critical, unknown,
    missing or malformed) blocks.
    """
    if type(review) is not dict or review.get("decision") != "APPROVED":
        return "independent Reviewer did not approve"
    if (review.get("correctness") != "PASS" or review.get("scope") != "PASS"
            or review.get("next_authorized_stage") != "github_draft_pr_preparation"):
        return "independent Reviewer correctness or scope did not pass"
    coverage = review.get("acceptance_coverage")
    if (type(coverage) is not list or not coverage
            or any(type(row) is not dict or row.get("result") != "PASS" for row in coverage)):
        return "independent Reviewer acceptance criteria are not all PASS"
    findings = review.get("findings")
    if type(findings) is not list or any(
        type(finding) is not dict
        or finding.get("severity") != "info"
        or any(type(finding.get(k)) is not str or not finding[k]
               for k in ("requirement", "detail", "evidence"))
        for finding in findings
    ):
        return "independent Reviewer findings require resolution"
    return None


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
        if not started(directory, "development-challenge") and io.owner_text_open(
            "development"
        ):
            # One approval text is open at a time; wait without attempting a send.
            return {"state": "awaiting_development_approval"}
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
        # Fix loop (owner's choice): when QA or the Reviewer finds problems, the same
        # approved team redoes the work with those findings, up to MAX_FIX_ROUNDS.
        # Plans made before multi-project support (no recorded specialists) keep the
        # old behaviour: the first failed verdict holds the task.
        loops = "specialists" in job
        fix_round = 0
        while True:
            job["round"] = fix_round
            if fix_round:
                qa = once(directory, f"qa-fix-{fix_round}", lambda: io.qa(job))
            elif (directory / "qa.recovery.json").exists():
                # Exactly one separately authorized incident recovery. No generic retry.
                io.verify_qa_recovery(job)
                qa = once(directory, "qa-recovery-1", lambda: io.qa(job))
                io.verify_qa_recovery(job)
            else:
                qa = once(directory, "qa", lambda: io.qa(job))
            if qa.get("decision") != "PASS":
                blocker, findings = "independent QA did not pass", qa_findings(qa)
            else:
                name = f"reviewer-fix-{fix_round}" if fix_round else "reviewer"
                review = once(directory, name, lambda: io.reviewer(job))
                blocker = reviewer_blocker(review)
                if blocker is None:
                    break
                findings = review_findings(review)
            if not loops:
                raise Held(blocker)
            if fix_round >= MAX_FIX_ROUNDS:
                once(directory, "fix-rounds-exhausted",
                     lambda: io.notify_stuck(job, findings))
                raise Held("fix rounds exhausted; owner notified")
            fix_round += 1
            job["round"], job["fix_findings"] = fix_round, findings
            developed = once(directory, f"developer-fix-{fix_round}",
                             lambda: io.developer_fix(job))
            if developed.get("state") != "ready_for_independent_qa":
                raise Held("developer did not produce a completed handoff")
        publication = once(
            directory, "publication-plan", lambda: io.publication_plan(job)
        )
        job["publication"] = publication
        if not started(directory, "publication-challenge") and io.owner_text_open(
            "publication"
        ):
            return {"state": "awaiting_publication_approval"}
        challenge = once(
            directory, "publication-challenge", lambda: io.publication_challenge(job)
        )
        # An unanswered approval that expired is resent only when the owner ran
        # `alfred-dev-ops resend` for it, once per authorization, never on its own.
        n = 1
        while io.publication_resend_authorized(job, n):
            name = f"publication-challenge-resend-{n}"
            if not (directory / (name + ".result.json")).exists() and (
                not io.publication_expired(challenge["challenge"])
                or (not started(directory, name) and io.owner_text_open("publication"))
            ):
                break
            challenge = once(directory, name, lambda: io.publication_challenge(job))
            n += 1
        authorization = io.publication_authorization(job, challenge["challenge"])
        if authorization is None:
            return {"state": "awaiting_publication_approval"}
        job["authorization_path"] = authorization["path"]
        result = once(directory, "publisher", lambda: io.publish(job))
        # The Publisher reported a definite error (for example its token could not see
        # the repository). Only the owner, with `alfred-dev-ops republish`, authorizes
        # one more attempt under the same approval; the Publisher re-checks GitHub
        # for an existing branch or draft PR before it pushes.
        n = 1
        while (
            result.get("status") == "ERROR"
            and n <= MAX_PUBLISH_RETRIES
            and io.publish_retry_authorized(job, n)
        ):
            job["publish_stage"] = f"publisher-retry-{n}"
            result = once(directory, job["publish_stage"], lambda: io.publish(job))
            n += 1
        if result.get("status") != "PUBLISHED_DRAFT":
            raise Held(
                "Publisher success is unverified; publication investigation required"
            )
        # handoff.31: where the owner delegated merging, the Publisher squash-merges the
        # draft PR once. The policy is asked once per task and the answer recorded.
        job["draft_pr_url"] = result["draft_pr_url"]
        merged = None
        if recorded(directory, "merge-decision",
                    lambda: io.merge_decision(job)).get("merge") == "delegated":
            merged = once(directory, "merge", lambda: io.merge(job))
            if merged.get("status") not in {"MERGED", "NOT_MERGED"}:
                raise Held("merge outcome requires investigation")
        notice = once(directory, "completion", lambda: io.completion(job))
        if notice.get("status") not in {"sent", "already_sent"}:
            raise Held("completion delivery requires reconciliation")
        done = {
            "state": "complete",
            "draft_pr_url": result["draft_pr_url"],
            "notification": notice["status"],
        }
        if merged and merged["status"] == "MERGED":
            # The completion text says "Reply undo within 24 hours"; open that window.
            window = recorded(directory, "undo-window", lambda: io.open_undo_window(job))
            done.update(merge_commit=merged["merge_commit"], undo=window.get("state"))
        return done
    except Exception as exc:  # noqa: BLE001 - durable fail-closed stage boundary
        # Preserve attempted operations. Do not expose model/credential exception text.
        return {
            "state": "held",
            "reason": str(exc) if isinstance(exc, Held) else type(exc).__name__,
        }


def undo(directory: Path, job: dict, io):
    """A completed, merged task: the owner's verified "undo" reverts exactly its squash
    commit, once, and the owner gets one short text. None while there is nothing to do."""
    window_path = directory / "undo-window.result.json"
    if not window_path.exists() or (directory / "undone.json").exists():
        return None
    try:
        window = json.loads(window_path.read_bytes())
        if window.get("state") != "undo_window_open":
            return None
        if not started(directory, "undo"):
            if io.undo_authorization(job, window["reference"]) is None:
                return None
        result = once(directory, "undo", lambda: io.undo(job))
        if result.get("status") not in {"REVERTED", "NOT_REVERTED"}:
            raise Held("undo outcome requires investigation")
        notice = once(directory, "undo-notice", lambda: io.undo_notice(job, result))
        if notice.get("state") != "sent":
            raise Held("undo notice requires reconciliation")
        outcome = {"state": "undone" if result["status"] == "REVERTED" else "undo_refused",
                   "reason": result.get("reason"), "revert_commit": result.get("revert_commit")}
        write_once(directory / "undone.json", outcome)
        return outcome
    except Exception as exc:  # noqa: BLE001 - durable fail-closed stage boundary
        return {
            "state": "held",
            "reason": str(exc) if isinstance(exc, Held) else type(exc).__name__,
        }
