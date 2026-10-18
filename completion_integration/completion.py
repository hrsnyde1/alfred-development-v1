"""Verify Linux Publisher evidence and reconcile GitHub before preparing text."""

import re
from dataclasses import dataclass

from jsonschema import validate


@dataclass(frozen=True)
class CompletionNotification:
    project: str
    task_id: str
    pr_url: str
    commit: str
    summary: str
    text: str


def prepare(
    *,
    result: dict,
    plan: dict,
    authorization: dict,
    binding: dict,
    plan_digest: str,
    result_schema: dict,
    get_pr,
    owner_login: str,
    owner_merge_attested: bool = False,
) -> CompletionNotification:
    """Inputs must come from the pinned protected handoff, never a requester outbox."""
    validate(result, result_schema)
    if (
        result["status"] != "PUBLISHED_DRAFT"
        or result["detail"] is not None
        or result["next_stage"] != "alfred_completion_notification"
        or plan.get("schema") != "alfred.draft-pr-plan/1"
        or plan.get("status") != "READY_FOR_OWNER_AUTHORIZATION"
        or result["publication_plan_sha256"] != plan_digest
    ):
        raise ValueError("verified Publisher success required")
    for key in (
        "project",
        "task_id",
        "destination",
        "base_branch",
        "publication_branch",
    ):
        if plan.get(key) != binding[key] or result[key] != binding[key]:
            raise ValueError("publication identity mismatch")
    if (
        plan.get("final_revision") != binding["final_revision"]
        or result["commit"] != binding["final_revision"]
        or any(
            result[key] != plan.get(key)
            for key in ("qa_report_sha256", "review_report_sha256")
        )
        or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", result["project"]) is None
        or re.fullmatch(r"T-[0-9]{4,}", result["task_id"]) is None
    ):
        raise ValueError("publication revision or evidence mismatch")
    expected_auth = {
        "schema": "alfred.github-draft-pr-authorization/1",
        "decision": "approved",
        "purpose": "one_github_draft_pr",
        **binding,
        "publication_plan_sha256": plan_digest,
        "owner_event_id": authorization.get("owner_event_id"),
    }
    if (
        authorization != expected_auth
        or type(authorization.get("owner_event_id")) is not str
        or not authorization["owner_event_id"].strip()
    ):
        raise ValueError("separate publication authorization mismatch")
    match = re.fullmatch(
        r"https://github\.com/"
        + re.escape(binding["destination"])
        + r"/pull/([1-9][0-9]{0,9})",
        result["draft_pr_url"] or "",
    )
    if match is None:
        raise ValueError("publication URL mismatch")
    number = int(match[1])
    pr = get_pr(binding["destination"], number)
    if (
        type(pr) is not dict
        or any(type(pr.get(k)) is not dict for k in ("head", "base"))
        or any(type(pr[k].get("repo")) is not dict for k in ("head", "base"))
    ):
        raise ValueError("GitHub publication readback mismatch")
    if (
        type(pr) is not dict
        or type(pr.get("number")) is not int
        or pr["number"] != number
        or pr.get("html_url") != result["draft_pr_url"]
        or pr.get("head", {}).get("sha") != result["commit"]
        or pr.get("head", {}).get("ref") != binding["publication_branch"]
        or pr.get("head", {}).get("repo", {}).get("full_name") != binding["destination"]
        or pr.get("base", {}).get("ref") != binding["base_branch"]
        or pr.get("base", {}).get("repo", {}).get("full_name") != binding["destination"]
        or type(pr.get("draft")) is not bool
        or type(pr.get("merged")) is not bool
    ):
        raise ValueError("GitHub publication readback mismatch")
    summary = f"Alfred successfully created Draft PR #{number}."
    if pr["merged"]:
        actor = (
            pr["merged_by"].get("login") if type(pr.get("merged_by")) is dict else None
        )
        if (
            pr.get("state") != "closed"
            or pr["draft"]
            or not pr.get("merged_at")
            or re.fullmatch(r"[0-9a-f]{40}", pr.get("merge_commit_sha") or "") is None
            or type(actor) is not str
            or re.fullmatch(r"[A-Za-z0-9-]{1,39}", actor) is None
        ):
            raise ValueError("inconsistent GitHub merge readback")
        if owner_merge_attested is True and actor == owner_login:
            current = (
                f"You subsequently merged it as {actor} in a separate authorized "
                "owner action."
            )
        else:
            current = f"GitHub now records it as merged by {actor}."
    elif pr.get("merged_at") is not None:
        raise ValueError("inconsistent GitHub merge readback")
    elif pr.get("state") == "open":
        current = (
            "It remains a draft awaiting owner review."
            if pr["draft"]
            else "It is now open and ready for review."
        )
    elif pr.get("state") == "closed":
        current = "The PR is now closed without a recorded merge."
    else:
        raise ValueError("unknown GitHub PR state")
    # Plain language for the owner; the technical summary above stays in the record.
    if pr["merged"]:
        # "You merged it" only with both GitHub readback and the owner's attestation.
        status = ("You merged it on GitHub" if current.startswith("You subsequently")
                  else f"GitHub shows it merged by {actor}") + \
            ", but it isn't live until it's deployed."
    elif pr.get("state") == "open" and pr["draft"]:
        status = "Built, tested and reviewed. It's ready for you to push."
    elif pr.get("state") == "open":
        status = "It's on GitHub, ready for your review. Nothing is live yet."
    else:
        status = "It's on GitHub but was closed without merging."
    text = f"All done with {result['project']}. {status}\n{result['draft_pr_url']}"
    if len(text) > 4000:
        raise ValueError("completion notification exceeds Photon text limit")
    return CompletionNotification(
        result["project"],
        result["task_id"],
        result["draft_pr_url"],
        result["commit"],
        summary,
        text,
    )
