"""Staged, separate development-approval transition.

This pure contract cannot create an authoritative grant. A host-owned service
must supply the independent owner verifier and persist the result in protected
storage before DevelopmentAuthority.verify may return it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .router import Denied, canonical_binding, json_object, select_specialists


class OwnerDecisionVerifier(Protocol):
    def verify(self, decision_reference: str, expected: dict) -> dict:
        """Verify owner identity and decision from a channel unavailable to workers."""


BOUND_FIELDS = (
    "schema",
    "project",
    "task_id",
    "spec_sha256",
    "plan_sha256",
    "repository",
    "worktree_root",
    "scope",
    "specialists",
)


def approval_request(
    spec_raw: bytes,
    plan_raw: bytes,
    *,
    project: str,
    task_id: str,
    repository: Path,
    worktree_root: Path,
    scope: list[str],
    spec_decoder: Callable[[bytes], dict] = json_object,
) -> dict:
    """Prepare an exact reviewable request; this has no approval authority."""
    specialists = select_specialists(spec_decoder(spec_raw), json_object(plan_raw))
    _, _, binding = canonical_binding(
        spec_raw,
        plan_raw,
        project=project,
        task_id=task_id,
        repository=repository,
        worktree_root=worktree_root,
        scope=scope,
        specialists=specialists,
        spec_decoder=spec_decoder,
    )
    return {
        "schema": "alfred.development-approval-request/1",
        **{key: binding[key] for key in BOUND_FIELDS if key != "schema"},
        "state": "pending_owner_decision",
    }


def stage_owner_transition(
    request: dict,
    *,
    decision_reference: str,
    expected_owner: str,
    verifier: OwnerDecisionVerifier,
    grant_reference: str,
) -> dict:
    """Produce a grant candidate only after an independently verified owner decision."""
    if (
        request.get("schema") != "alfred.development-approval-request/1"
        or request.get("state") != "pending_owner_decision"
    ):
        raise Denied("development approval request is not pending")
    if not decision_reference or not grant_reference or not expected_owner:
        raise Denied("missing owner-decision binding")
    expected = {key: request[key] for key in BOUND_FIELDS if key != "schema"}
    decision = verifier.verify(decision_reference, expected)
    if type(decision) is not dict or any(
        decision.get(key) != value for key, value in expected.items()
    ):
        raise Denied("owner decision binding mismatch")
    if (
        decision.get("owner"),
        decision.get("decision"),
        decision.get("source"),
        decision.get("reference"),
    ) != (
        expected_owner,
        "approve_development",
        "independent_owner_channel",
        decision_reference,
    ):
        raise Denied("owner development decision not verified")
    return {
        "schema": "alfred.development-grant/1",
        "reference": grant_reference,
        "issuer": "trusted_owner_authority",
        "state": "approved",
        **expected,
    }
