"""On-demand CTO-to-Developer runner. No service or scheduled activation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .execution import AssignmentStore, _git, build_assignments, invoke, qa_manifest
from .gateway_adapter import GatewayInputs, read_gateway_inputs
from .owner_grants import ProtectedDevelopmentAuthority, _digest
from . import agent_profiles, team_skills, team_snapshot
from .real_worker import (MAX_PRACTICES, CodexReadOnlyBroker, DeveloperWorker,
                          RoutingBroker, create_worktree)
from .router import (CAPABILITY_BY_ROLE, Denied, ModelChoice, route, select_model,
                     task_complexity)

PROVIDERS = {"codex", "claude"}
# V1 specialists whose built-in profile in agent_profiles.json has another id.
BUILTIN_PROFILE = {"code_reviewer": "reviewer"}
CHECK = ["/usr/bin/python3", "-m", "unittest", "discover", "-v"]


def _record_report(state: AssignmentStore, item: dict, report: dict) -> None:
    path = state.root / f"report-{item['id']}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(report, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def execute_approved(inputs: GatewayInputs, *, project: str, task_id: str,
                     worktree_root: Path, scope: list[str], grant_reference: str,
                     grant_root: Path, items: list[dict], models: dict,
                     state_root: Path, checks: list[list[str]] | None = None,
                     total_cost_limit: float, overrides: dict | None = None,
                     broker=None,
                     grant_environment: str = "host", baseline_revision: str | None = None,
                     delegation_policy: Path | None = None,
                     team_skills_root: Path = team_skills.ROOT,
                     team_skills_owner: int = 0, fix_round: int = 0,
                     team_snapshot_root: Path | None = None) -> tuple[list[dict], dict]:
    """Runs only after protected authority verifies the exact Gateway inputs.

    fix_round > 0 redoes the same approved work from the same baseline after QA or
    the Reviewer found problems; the items' objectives carry those findings."""
    approved_baseline = json.loads(inputs.plan_raw).get("baseline_revision")
    if baseline_revision is not None and approved_baseline != baseline_revision:
        raise Denied("baseline differs from the owner-approved CTO plan")
    baseline_revision = approved_baseline
    authority = ProtectedDevelopmentAuthority(grant_root, environment=grant_environment,
                                              delegation_policy=delegation_policy)
    dispatch = route(inputs.spec_raw, inputs.plan_raw, project=project, task_id=task_id,
                     repository=inputs.repository, worktree_root=worktree_root,
                     scope=scope, authorization_reference=grant_reference,
                     authority=authority, spec_decoder=inputs.spec_decoder)
    assignments = build_assignments(dispatch, items)
    broker = broker or RoutingBroker()
    if isinstance(broker, CodexReadOnlyBroker):
        broker.require_executable()
    if not broker.authenticated():
        raise Denied("configured model broker is not authenticated")
    providers = models.get("providers", {})
    if not providers or not set(providers) <= PROVIDERS:
        raise Denied("only the Codex and Claude brokers are installed")
    available = {(provider, name) for provider, catalog in providers.items() for name in catalog}
    spec, plan = inputs.spec_decoder(inputs.spec_raw), json.loads(inputs.plan_raw)
    complexity = task_complexity(spec, plan, dispatch["specialists"])
    # Verified before the grant is claimed, so a missing or altered snapshot
    # leaves the owner's grant unused.
    skills = team_skills.for_plan(plan, team_skills_root, owner=team_skills_owner)
    # Owner-approved Alfred OS files, when a verified snapshot exists; otherwise the
    # built-in profile exactly as before. Read once, before the grant is claimed.
    budget = MAX_PRACTICES - len(json.dumps(skills, ensure_ascii=False).encode())
    profiles = {s: team_snapshot.profile(
                    s, agent_profiles.identity(BUILTIN_PROFILE.get(s, s)),
                    root=team_snapshot_root, budget=budget)
                for s in dispatch["specialists"]}
    identities = {s: text for s, (text, _) in profiles.items()}
    team_records = {s: record for s, (_, record) in profiles.items()}
    overrides = overrides or {}
    if set(overrides) - set(dispatch["specialists"]):
        raise Denied("model override outside assigned specialists")
    choices: dict[str, tuple[ModelChoice, ModelChoice | None]] = {}
    remaining = float(total_cost_limit)
    for specialist in dispatch["specialists"]:
        first = select_model(models, specialist, available=available,
                             required_capabilities=CAPABILITY_BY_ROLE[specialist],
                             max_cost=remaining, complexity=complexity,
                             override=overrides.get(specialist))
        remaining -= providers[first.provider][first.model]["max_task_cost"]
        fallback = None
        if overrides.get(specialist) is None and not first.fallback_used:
            try:
                fallback = select_model(models, specialist,
                    available=available - {(first.provider, first.model)},
                    required_capabilities=CAPABILITY_BY_ROLE[specialist],
                    max_cost=remaining, complexity=complexity)
            except Denied:
                pass
        choices[specialist] = (first, fallback)
    expected = {key: dispatch[key] for key in (
        "project", "task_id", "spec_sha256", "plan_sha256", "repository",
        "worktree_root", "scope", "specialists")}
    expected["schema"] = "alfred.development-grant/1"
    expected["specialists"] = sorted(expected["specialists"])
    authority.claim(grant_reference, expected, run_sha256=_digest({
        "project": project, "task_id": task_id, "items": assignments,
        "scope": scope, "models": models, "overrides": overrides,
        "total_cost_limit": total_cost_limit}), fix_round=fix_round)
    try:
        result = _execute_claimed(inputs, dispatch, assignments, choices,
                                  worktree_root, state_root, project, task_id,
                                  broker, checks, authority, baseline_revision, skills,
                                  fix_round, identities, team_records)
    except BaseException as exc:
        authority.finish(grant_reference, status="failed" if isinstance(exc, Exception) else "uncertain",
                         fix_round=fix_round)
        raise
    authority.finish(grant_reference, status="completed", fix_round=fix_round)
    return result


def _execute_claimed(inputs, dispatch, assignments, choices, worktree_root,
                     state_root, project, task_id, broker, checks, authority, baseline_revision,
                     skills=(), fix_round=0, identities=None, team_records=None):
    state = AssignmentStore(state_root / project / task_id)
    # A single final branch carries every completed developer commit to QA.
    final = create_worktree(inputs.repository, worktree_root, project, task_id,
                            "final" if fix_round == 0 else f"final-r{fix_round}", baseline_revision)
    reports = []
    remaining_items = {item["id"]: item for item in assignments}
    while remaining_items:
        ready = [item for item in remaining_items.values()
                 if all(dep in {r["assignment_id"] for r in reports} for dep in item["depends_on"])]
        if not ready:
            raise Denied("dependent assignment cannot start")
        item = ready[0]
        first, fallback = choices[item["specialist"]]
        if "git_local_commit_if_granted" not in first.tools:
            raise Denied("QA requires authorized local commit")
        worktree = create_worktree(inputs.repository, worktree_root, project, task_id,
                                   item["id"], _git(final, "rev-parse", "HEAD"))
        worker = DeveloperWorker(broker, objective=item["objective"],
                                 checks=checks or [CHECK], fallback=fallback, skills=skills,
                                 identity=(identities or {}).get(item["specialist"], ""),
                                 team_profile=(team_records or {}).get(item["specialist"],
                                                                        team_snapshot.BUILTIN))
        report = invoke(dispatch, item, worktree=worktree, model=first, worker=worker,
                        store=state, trusted_authority=authority, approved_fallback=fallback)
        reports.append(report)
        _record_report(state, item, report)
        if report["status"] != "completed" or not report["commits"]:
            raise Denied(f"developer work incomplete: inspect {state.root / ('report-' + item['id'] + '.json')}")
        for commit in reversed(report["commits"]):
            subprocess.run(["git", "-C", str(final), "-c", "core.hooksPath=/dev/null",
                            "-c", "user.name=Alfred Development", "-c", "user.email=development@localhost",
                            "cherry-pick", commit], check=True, capture_output=True, timeout=20,
                           env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
                                "GIT_CONFIG_NOSYSTEM": "1"})
        del remaining_items[item["id"]]
    return reports, qa_manifest(reports, assignments, final)


def execute_gateway_task(*, gateway_root: Path, gateway_state: Path, registry_path: Path,
                         project: str, task_id: str, **kwargs):
    inputs = read_gateway_inputs(gateway_root=gateway_root, gateway_state=gateway_state,
                                 registry_path=registry_path, project_id=project, task_id=task_id)
    return execute_approved(inputs, project=project, task_id=task_id, **kwargs)
