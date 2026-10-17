"""Offline Developer V1 routing and handoff. Authority is an external trusted port.

The package cannot mint grants, contact Hermes, or launch host workers. An operator
must provide an authority implementation and an isolated execution backend.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).parent
SPECIALISTS = json.loads((ROOT / "specialists.json").read_text())["specialists"]
EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
TOOLS = frozenset(
    {"read_scoped", "write_scoped", "run_approved_check", "git_local_commit_if_granted"}
)
COMPLEXITY = {"low": 0, "medium": 1, "high": 2}
CAPABILITY_BY_ROLE = {
    "frontend": {"code", "ui"},
    "backend": {"code"},
    "full_stack": {"code", "ui"},
    "devops": {"code"},
    "data_engineer": {"code", "data"},
    "data_scientist": {"analysis"},
    "ai_ml": {"ml"},
    "integration": {"code"},
    "security": {"code"},
    "mobile": {"mobile"},
    "performance": {"code"},
}
ID = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
TASK = re.compile(r"T-[0-9]{4}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
PROTECTED = (
    ".git/",
    ".dev/",
    ".github/",
    ".claude/",
    "registry/",
    "secrets/",
    "credentials/",
)


class Denied(ValueError):
    pass


class DevelopmentAuthority(Protocol):
    def verify(self, reference: str, expected: dict) -> dict:
        """Read independently issued grant from a protected source; never trust caller data."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_object(raw: bytes, maximum: int = 65536) -> dict:
    if not isinstance(raw, bytes) or len(raw) > maximum:
        raise Denied("artifact size or type")
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Denied("invalid JSON artifact") from exc
    if type(obj) is not dict:
        raise Denied("artifact must be an object")
    return obj


def scoped_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
    ):
        raise Denied("invalid assigned path")
    parts = value.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise Denied("invalid assigned path")
    if (
        value.startswith(PROTECTED)
        or value in {".env", "CLAUDE.md"}
        or any(p.startswith(".env") for p in parts)
    ):
        raise Denied("protected assigned path")
    return value


def canonical_binding(
    spec_raw: bytes,
    plan_raw: bytes,
    *,
    project: str,
    task_id: str,
    repository: Path,
    worktree_root: Path,
    scope: list[str],
    specialists: list[str],
    spec_decoder: Callable[[bytes], dict] = json_object,
) -> tuple[dict, dict, dict]:
    """Check canonical task, CTO plan, registry repo and proposed development scope."""
    if not ID.fullmatch(project) or not TASK.fullmatch(task_id):
        raise Denied("invalid canonical identity")
    spec, plan = spec_decoder(spec_raw), json_object(plan_raw)
    if (
        spec.get("project") != project
        or spec.get("id") != task_id
        or spec.get("source") != "hermes"
        or spec.get("status") != "proposed"
    ):
        raise Denied("canonical task identity or state mismatch")
    if (
        plan.get("schema"),
        plan.get("project"),
        plan.get("task_id"),
        plan.get("spec_sha256"),
    ) != ("alfred.cto-plan/1", project, task_id, digest(spec_raw)):
        raise Denied("CTO plan does not bind canonical task")
    if (
        not isinstance(spec.get("request_id"), str)
        or plan.get("request_id") != spec["request_id"]
    ):
        raise Denied("CTO plan request identity mismatch")
    if (
        plan.get("approval_state") != "awaiting_development_approval"
        or plan.get("clarification_required") is not False
    ):
        raise Denied("plan is not ready for approval")
    if (
        not repository.is_absolute()
        or repository.is_symlink()
        or not repository.is_dir()
        or str(repository) != plan.get("repository")
    ):
        raise Denied("repository binding mismatch")
    if (
        not worktree_root.is_absolute()
        or worktree_root.is_symlink()
        or not worktree_root.is_dir()
        or worktree_root.resolve() == repository.resolve()
    ):
        raise Denied("invalid authorized worktree root")
    if not scope or len(scope) != len(set(scope)):
        raise Denied("empty or duplicate scope")
    for path in scope:
        scoped_path(path)
    if (
        not specialists
        or len(specialists) != len(set(specialists))
        or any(s not in SPECIALISTS for s in specialists)
    ):
        raise Denied("invalid specialist assignments")
    expected = {
        "schema": "alfred.development-grant/1",
        "project": project,
        "task_id": task_id,
        "spec_sha256": digest(spec_raw),
        "plan_sha256": digest(plan_raw),
        "repository": str(repository),
        "worktree_root": str(worktree_root),
        "scope": sorted(scope),
        "specialists": sorted(specialists),
    }
    return spec, plan, expected


def verify_input(
    spec_raw: bytes,
    plan_raw: bytes,
    *,
    project: str,
    task_id: str,
    repository: Path,
    worktree_root: Path,
    scope: list[str],
    specialists: list[str],
    authorization_reference: str,
    authority: DevelopmentAuthority,
    spec_decoder: Callable[[bytes], dict] = json_object,
) -> tuple[dict, dict, dict]:
    """Accept only a separate owner grant matching the exact canonical binding."""
    spec, plan, expected = canonical_binding(
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
    if not isinstance(authorization_reference, str) or not authorization_reference:
        raise Denied("missing development authorization reference")
    grant = authority.verify(authorization_reference, expected)
    if type(grant) is not dict or any(grant.get(k) != v for k, v in expected.items()):
        raise Denied("development grant binding mismatch")
    if (
        grant.get("issuer") != "trusted_owner_authority"
        or grant.get("state") != "approved"
    ):
        raise Denied("development grant not independently approved")
    if grant.get("reference") != authorization_reference:
        raise Denied("development grant reference mismatch")
    return spec, plan, grant


ROUTES = (
    (
        "security",
        ("authentication", "authorization", "credential", "security", "permission"),
    ),
    ("mobile", ("ios", "android", "mobile", "swift", "kotlin")),
    ("devops", ("deployment", "docker", "terraform", "infrastructure", "ci pipeline")),
    ("data_scientist", ("forecast", "statistical", "experiment", "prediction")),
    ("ai_ml", ("research-agent", "research agent", "llm pipeline", "model inference")),
    ("data_engineer", ("ingestion", "etl", "data pipeline")),
    ("integration", ("external api", "webhook", "third-party", "provider integration")),
    ("performance", ("latency", "throughput", "profiling", "performance")),
    ("full_stack", ("full application", "end-to-end feature", "frontend and backend")),
    (
        "frontend",
        ("website", "dark mode", "theme toggle", "frontend", "user interface"),
    ),
    ("backend", ("api endpoint", "backend", "database", "service endpoint")),
)


def select_specialists(spec: dict, plan: dict) -> list[str]:
    """Conservative, evidence-aware CTO routing proposal; grant must permit it."""
    sections = spec.get("sections") or {}
    # Scope often lists exclusions (for example "no backend or auth"). Route from
    # the requested outcome, then use repository evidence as a separate check.
    text = " ".join(
        str(x) for x in (spec.get("title", ""), sections.get("objective", ""))
    ).lower()
    files = plan.get("repository_evidence", {}).get("files", [])
    if type(files) is not list or any(type(f) is not str for f in files):
        raise Denied("invalid repository evidence")
    result = [role for role, terms in ROUTES if any(term in text for term in terms)]
    if "ai_ml" in result and (
        "integration" in result or "research agent" in text or "research-agent" in text
    ):
        result = [r for r in result if r != "integration"] + ["integration"]
    if "full_stack" in result:
        result = [r for r in result if r not in ("frontend", "backend")]
    if "frontend" in result and not any(
        Path(f).suffix.lower()
        in {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
        for f in files
    ):
        raise Denied("frontend source absent from registered repository")
    if not result:
        raise Denied("no supported specialty found; CTO must clarify")
    return list(dict.fromkeys(result))


def task_complexity(spec: dict, plan: dict, specialists: list[str]) -> str:
    """Conservative CTO complexity signal from canonical risk and planned work."""
    risk = spec.get("risk")
    if risk not in (None, "low", "medium", "high"):
        raise Denied("invalid task risk")
    work = plan.get("developer_work_items", [])
    files = plan.get("expected_components_files", [])
    if type(work) is not list or type(files) is not list:
        raise Denied("invalid CTO work evidence")
    if risk == "high" or len(specialists) > 1 or len(files) > 8 or len(work) > 5:
        return "high"
    if risk == "medium" or len(files) > 2 or len(work) > 2:
        return "medium"
    return "low"


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    reasoning_effort: str
    tools: tuple[str, ...]
    fallback_used: bool


class ProviderUnavailable(RuntimeError):
    """An approved model route failed before producing developer output."""


def invoke_model(
    config: dict,
    specialist: str,
    *,
    available: set[tuple[str, str]],
    required_capabilities: set[str],
    max_cost: float,
    caller,
    complexity: str = "low",
    override: dict | None = None,
) -> tuple[ModelChoice, object]:
    """Use one Hermes-backed caller. Only provider outages permit approved fallback."""
    first = select_model(
        config,
        specialist,
        available=available,
        required_capabilities=required_capabilities,
        max_cost=max_cost,
        complexity=complexity,
        override=override,
    )
    try:
        return first, caller(first)
    except ProviderUnavailable:
        if override is not None or first.fallback_used:
            raise
        remaining = available - {(first.provider, first.model)}
        second = select_model(
            config,
            specialist,
            available=remaining,
            required_capabilities=required_capabilities,
            max_cost=max_cost,
            complexity=complexity,
        )
        if not second.fallback_used:
            raise Denied("fallback route invalid")
        return second, caller(second)


def select_model(
    config: dict,
    specialist: str,
    *,
    available: set[tuple[str, str]],
    required_capabilities: set[str],
    max_cost: float,
    complexity: str = "low",
    override: dict | None = None,
) -> ModelChoice:
    """Resolve named provider routes; auth and actual LLM calls remain with Hermes."""
    if (
        specialist not in SPECIALISTS
        or config.get("schema") != "alfred.developer-models/1"
    ):
        raise Denied("invalid model configuration")
    if complexity not in COMPLEXITY:
        raise Denied("invalid task complexity")
    slot = config.get("specialists", {}).get(specialist)
    if type(slot) is not dict:
        raise Denied("missing specialist model slot")
    effort, tools = slot.get("reasoning_effort"), slot.get("tools")
    if effort not in EFFORTS or type(tools) is not list or not set(tools) <= TOOLS:
        raise Denied("invalid effort or tool permissions")
    if override is not None and override not in (
        slot.get("primary"),
        slot.get("fallback"),
    ):
        raise Denied("unapproved model override")
    candidates = [override] if override else [slot.get("primary"), slot.get("fallback")]
    for index, route in enumerate(candidates):
        if type(route) is not dict:
            continue
        provider, model = route.get("provider"), route.get("model")
        catalog = config.get("providers", {}).get(provider, {}).get(model)
        if type(catalog) is not dict or (provider, model) not in available:
            continue
        if not required_capabilities <= set(catalog.get("capabilities", [])):
            continue
        supported = catalog.get("max_complexity")
        if (
            supported not in COMPLEXITY
            or COMPLEXITY[supported] < COMPLEXITY[complexity]
        ):
            continue
        cost = catalog.get("max_task_cost")
        if type(cost) not in (float, int) or cost > max_cost:
            continue
        return ModelChoice(
            provider, model, effort, tuple(tools), bool(index and not override)
        )
    raise Denied("no approved available model within capability and cost limits")


def plan_models(
    spec: dict,
    plan: dict,
    specialists: list[str],
    config: dict,
    *,
    available: set[tuple[str, str]],
    total_cost_limit: float,
    overrides: dict[str, dict] | None = None,
) -> dict[str, ModelChoice]:
    """CTO model proposal constrained by capabilities, complexity and total cost."""
    if type(total_cost_limit) not in (int, float) or total_cost_limit <= 0:
        raise Denied("invalid model cost limit")
    overrides = overrides or {}
    if set(overrides) - set(specialists):
        raise Denied("model override names unassigned specialist")
    complexity = task_complexity(spec, plan, specialists)
    remaining = float(total_cost_limit)
    chosen = {}
    for specialist in specialists:
        choice = select_model(
            config,
            specialist,
            available=available,
            required_capabilities=CAPABILITY_BY_ROLE[specialist],
            max_cost=remaining,
            complexity=complexity,
            override=overrides.get(specialist),
        )
        chosen[specialist] = choice
        remaining -= config["providers"][choice.provider][choice.model]["max_task_cost"]
    return chosen


def route(
    spec_raw: bytes,
    plan_raw: bytes,
    *,
    project: str,
    task_id: str,
    repository: Path,
    worktree_root: Path,
    scope: list[str],
    authorization_reference: str,
    authority: DevelopmentAuthority,
    assigned_specialists: list[str] | None = None,
    spec_decoder: Callable[[bytes], dict] = json_object,
) -> dict:
    spec, plan = spec_decoder(spec_raw), json_object(plan_raw)
    selected = select_specialists(spec, plan)
    if assigned_specialists is not None and assigned_specialists != selected:
        raise Denied("assignment differs from CTO routing")
    _, _, grant = verify_input(
        spec_raw,
        plan_raw,
        project=project,
        task_id=task_id,
        repository=repository,
        worktree_root=worktree_root,
        scope=scope,
        specialists=selected,
        authorization_reference=authorization_reference,
        authority=authority,
        spec_decoder=spec_decoder,
    )
    return {
        "schema": "alfred.developer-dispatch/1",
        "project": project,
        "task_id": task_id,
        "spec_sha256": digest(spec_raw),
        "plan_sha256": digest(plan_raw),
        "repository": str(repository),
        "worktree_root": str(worktree_root),
        "scope": sorted(scope),
        "specialists": selected,
        "authorization_reference": grant["reference"],
    }
