"""Read-only CTO/router check for the disposable acceptance fixture.

This does not create a Gateway filing, CTO plan artifact, grant, or model call.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GATEWAY = Path("/home/alfred/Git/alfred")
sys.path.insert(0, str(GATEWAY / "src"))
sys.path.insert(0, str(GATEWAY / ".dev" / "bin"))
sys.path.insert(0, str(ROOT.parent))

from alfred.registry.loader import parse_registry, read_registry_data  # noqa: E402
from developer_v1.router import CAPABILITY_BY_ROLE, select_model, select_specialists, task_complexity  # noqa: E402
from taskspec import mentions_protected, next_id, render, validate  # noqa: E402
from cto import _central_cto, _repo_evidence, _validate_plan  # noqa: E402


def main() -> None:
    repo = ROOT / "repo"
    draft = json.loads((ROOT / "task-draft.json").read_text())
    registry = parse_registry(read_registry_data(ROOT / "projects.proposed.yaml"))
    project = registry.project("dev-v1-accept")
    assert project is not None and project.resolved_path(Path.home()) == repo
    task_id = next_id(repo / ".dev" / "tasks")
    sections = {key: draft[key] for key in (
        "objective", "scope", "requirements", "constraints", "acceptance_criteria",
        "security_considerations", "testing_requirements")}
    sections.update(implementation_notes="(CTO planning only.)", log="Synthetic preparation only.")
    doc = {"id": task_id, "title": draft["title"], "status": "proposed",
           "source": "hermes", "risk": "high" if mentions_protected(
               {"title": draft["title"], "sections": sections}) else None,
           "company": "alfred", "created": "2026-10-15", "approved_by": None,
           "branch": None, "pr": None, "project": project.id,
           "request_id": "b6d51fb2-2586-4cd5-a5c2-e3578f273d20", "sections": sections}
    filename = f"{task_id}-backend-calculator-subtract-helper.md"
    assert not validate(doc, filename, project.company)
    raw = render(doc).encode()
    parsed = __import__("taskspec").parse(raw.decode())
    assert not validate(parsed, filename, project.company)
    evidence = _repo_evidence(repo, filename)
    plan = _central_cto(parsed, repo, evidence, hashlib.sha256(raw).hexdigest())
    _validate_plan(plan)
    specialists = select_specialists(parsed, plan)
    models = json.loads(Path("/var/lib/alfred-development-state/models.json").read_text())
    available = {("codex", name) for name in models["providers"]["codex"]}
    complexity = task_complexity(parsed, plan, specialists)
    model = select_model(models, "backend", available=available,
                         required_capabilities=CAPABILITY_BY_ROLE["backend"],
                         max_cost=2, complexity=complexity)
    assert plan["clarification_required"] is False
    assert specialists == ["backend"]
    assert "test_calculator.py" in evidence["test_files"]
    assert model.provider == "codex"
    print(json.dumps({"state": "prepared_synthetic_only", "project": project.id,
                      "predicted_task_id": task_id, "clarification_required": False,
                      "specialists": specialists, "complexity": complexity,
                      "model": {"provider": model.provider, "name": model.model,
                                "reasoning_effort": model.reasoning_effort},
                      "repository": str(repo), "test_files": evidence["test_files"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
