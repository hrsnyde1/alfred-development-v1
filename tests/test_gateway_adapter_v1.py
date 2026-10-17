import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from developer_v1.gateway_adapter import read_gateway_inputs
from developer_v1.router import Denied, route

GATEWAY = Path("/home/alfred/Git/alfred")


@unittest.skipUnless(
    importlib.util.find_spec("pydantic") and GATEWAY.is_dir(),
    "Gateway Python dependencies unavailable",
)
class GatewayAdapterTest(unittest.TestCase):
    def test_synthetic_gateway_markdown_and_plan_binding(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            repo = root / "repo"
            task_dir = repo / ".dev" / "tasks"
            task_dir.mkdir(parents=True)
            worktrees = root / "worktrees"
            worktrees.mkdir()
            (repo / "index.html").write_text("fixture\n")
            registry = root / "projects.yaml"
            registry.write_text(f"""version: 1
companies:
  - id: alfred
    display_name: Alfred
projects:
  - id: fixture
    company: alfred
    display_name: Fixture
    aliases: []
    description: Disposable fixture
    status: active
    repo:
      github: example/fixture
      default_branch: main
    local_path: {repo}
    stack:
      language: python
      version: "3.12"
      framework: none
      package_manager: uv
    checks:
      - uv run pytest
    engineering_kit: true
    context:
      always: [CLAUDE.md]
    permissions:
      hermes_requests: true
      max_auto_risk: medium
    allowed_task_types: [feature, bugfix, test, docs, refactor]
""")
            spec = """---
id: T-0042
title: Website dark mode
status: proposed
source: hermes
risk: null
company: alfred
created: '2026-10-15'
approved_by: null
branch: null
pr: null
project: fixture
request_id: a7881a72-b1d8-5179-973b-6e84efa4e62b
---

## Objective
Add dark mode to the website.

## Scope
Frontend only. No backend or auth.

## Requirements
Add a theme toggle.

## Constraints
No new dependency.

## Acceptance criteria
- [ ] Toggle works.

## Security considerations
No credentials.

## Testing requirements
Theme persists.

## Implementation notes
Pending CTO plan.

## Log
Proposed by Gateway.
"""
            raw = spec.encode()
            (task_dir / "T-0042-dark-mode.md").write_bytes(raw)
            state = root / "gateway"
            (state / "cto-plans").mkdir(parents=True)
            (state / "journal.jsonl").write_text(
                json.dumps(
                    {
                        "kind": "outcome",
                        "outcome": "filed",
                        "project": "fixture",
                        "task_id": "T-0042",
                        "revision": 1,
                        "request_id": "a7881a72-b1d8-5179-973b-6e84efa4e62b",
                    }
                )
                + "\n"
            )
            plan = {
                "schema": "alfred.cto-plan/1",
                "project": "fixture",
                "task_id": "T-0042",
                "request_id": "a7881a72-b1d8-5179-973b-6e84efa4e62b",
                "spec_sha256": hashlib.sha256(raw).hexdigest(),
                "approval_state": "awaiting_development_approval",
                "clarification_required": False,
                "objective": "Add dark mode",
                "scope": "index.html",
                "repository": str(repo),
                "repository_evidence": {
                    "files": ["index.html"],
                    "web_files": ["index.html"],
                    "test_files": [],
                    "inspected_files": ["index.html"],
                },
                "implementation_approach": "Theme toggle",
                "expected_components_files": ["index.html"],
                "developer_work_items": ["Add theme toggle"],
                "developer_deliverables": ["Source"],
                "qa_checklist": ["Check theme"],
                "independent_review_criteria": ["Review"],
                "dependencies_integrations": [],
                "risks_blockers": [],
                "clarification_questions": [],
                "acceptance_criteria": "Toggle works",
                "owner_summary": "Add dark mode",
                "planning_note": "No development approved",
                "delivery": {"state": "delivered", "message_id": "fixture"},
            }
            (state / "cto-plans" / "fixture-T-0042.json").write_text(json.dumps(plan))
            inputs = read_gateway_inputs(
                gateway_root=GATEWAY,
                gateway_state=state,
                project_id="fixture",
                task_id="T-0042",
                registry_path=registry,
            )
            self.assertEqual(inputs.repository, repo)
            self.assertEqual(
                inputs.spec_decoder(inputs.spec_raw)["sections"]["objective"],
                "Add dark mode to the website.",
            )

            class NoApproval:
                def verify(self, reference, expected):
                    raise Denied("no development grant")

            with self.assertRaises(Denied):
                route(
                    inputs.spec_raw,
                    inputs.plan_raw,
                    project="fixture",
                    task_id="T-0042",
                    repository=inputs.repository,
                    worktree_root=worktrees,
                    scope=["index.html"],
                    authorization_reference="absent",
                    authority=NoApproval(),
                    spec_decoder=inputs.spec_decoder,
                )


if __name__ == "__main__":
    unittest.main()
