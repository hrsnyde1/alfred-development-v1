import hashlib
import json
import multiprocessing
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from developer_v1.approval_transition import approval_request, stage_owner_transition
from developer_v1.execution import (
    AssignmentStore,
    build_assignments,
    invoke,
    qa_manifest,
)
from developer_v1.router import (
    SPECIALISTS,
    Denied,
    ModelChoice,
    ProviderUnavailable,
    invoke_model,
    plan_models,
    route,
    select_model,
    select_specialists,
    task_complexity,
)


def raw(obj):
    return json.dumps(obj, sort_keys=True).encode()


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def claim_in_process(root, assignment, start, results):
    start.wait(5)
    try:
        AssignmentStore(Path(root)).claim(assignment)
        results.put("claimed")
    except Denied:
        results.put("denied")


class Authority:
    def __init__(self, approved=True):
        self.approved = approved

    def verify(self, reference, expected):
        if not self.approved:
            raise Denied("no independent development grant")
        return {
            **expected,
            "reference": reference,
            "issuer": "trusted_owner_authority",
            "state": "approved",
        }


class FakeWorker:
    def __init__(self, status="completed"):
        self.status = status
        self.calls = 0

    def execute(self, assignment, worktree, model):
        self.calls += 1
        if self.status == "completed":
            (worktree / assignment["files"][0]).write_text("changed\n")
        return {
            "status": self.status,
            "work_completed": "fixture change",
            "tests": [
                {
                    "name": "synthetic check",
                    "outcome": "passed",
                    "evidence": "fixture assertion",
                }
            ]
            if self.status == "completed"
            else [],
            "commits": [],
            "blockers": []
            if self.status == "completed"
            else ["synthetic dependency unavailable"],
            "known_limitations": [],
            "actual_model": {"provider": model.provider, "model": model.model},
        }


class RaisingWorker:
    def execute(self, assignment, worktree, model):
        raise RuntimeError("fixture crash")


class ForbiddenWriteWorker(FakeWorker):
    def execute(self, assignment, worktree, model):
        (worktree / ".dev").mkdir()
        (worktree / ".dev" / "approval.json").write_text("forged")
        return super().execute(assignment, worktree, model)


class DeveloperV1Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        git(self.repo, "config", "user.email", "fixture@example.invalid")
        git(self.repo, "config", "user.name", "Fixture")
        (self.repo / "index.html").write_text("original\n")
        git(self.repo, "add", "index.html")
        git(self.repo, "commit", "-qm", "baseline")
        self.worktrees = root / "worktrees"
        self.worktrees.mkdir()
        self.worktree = self.worktrees / "a"
        git(self.repo, "worktree", "add", "-qb", "dev/test-a", str(self.worktree))
        self.state = AssignmentStore(root / "state")
        self.spec = {
            "project": "dev-001",
            "id": "T-0042",
            "source": "hermes",
            "status": "proposed",
            "request_id": "a7881a72-b1d8-5179-973b-6e84efa4e62b",
            "title": "Website dark mode",
            "sections": {"objective": "Add dark mode", "scope": "index.html"},
        }
        self.spec_raw = raw(self.spec)
        self.plan = {
            "schema": "alfred.cto-plan/1",
            "project": "dev-001",
            "task_id": "T-0042",
            "request_id": "a7881a72-b1d8-5179-973b-6e84efa4e62b",
            "spec_sha256": hashlib.sha256(self.spec_raw).hexdigest(),
            "approval_state": "awaiting_development_approval",
            "clarification_required": False,
            "repository": str(self.repo),
            "repository_evidence": {"files": ["index.html"]},
        }
        self.plan_raw = raw(self.plan)
        self.model = ModelChoice(
            "fixture", "m1", "medium", ("read_scoped", "write_scoped"), False
        )

    def dispatch(self, **kw):
        args = {
            "project": "dev-001",
            "task_id": "T-0042",
            "repository": self.repo,
            "worktree_root": self.worktrees,
            "scope": ["index.html"],
            "authorization_reference": "owner-grant-1",
            "authority": Authority(),
        }
        args.update(kw)
        return route(self.spec_raw, self.plan_raw, **args)

    def assignment(self):
        return {
            "id": "item-a",
            "project": "dev-001",
            "task_id": "T-0042",
            "specialist": "frontend",
            "files": ["index.html"],
            "depends_on": [],
        }

    def test_all_specialists_registered_with_contract(self):
        self.assertEqual(len(SPECIALISTS), 11)
        for item in SPECIALISTS.values():
            for key in (
                "name",
                "task_types",
                "responsibilities",
                "files",
                "deliverables",
                "testing",
            ):
                self.assertTrue(item[key])

    def test_each_specialist_uses_shared_staged_invocation_contract(self):
        for role in SPECIALISTS:
            with self.subTest(role=role):
                worktree = self.worktrees / role
                git(self.repo, "worktree", "add", "-qb", f"dev/{role}", str(worktree))
                dispatch = {**self.dispatch(), "specialists": [role]}
                assignment = {
                    "id": role,
                    "project": "dev-001",
                    "task_id": "T-0042",
                    "specialist": role,
                    "files": ["index.html"],
                    "depends_on": [],
                }
                report = invoke(
                    dispatch,
                    assignment,
                    worktree=worktree,
                    model=self.model,
                    worker=FakeWorker(),
                    store=self.state,
                    synthetic=True,
                )
                self.assertEqual(
                    (report["specialist"], report["status"]), (role, "completed")
                )

    def test_routing_is_selective_and_evidence_aware(self):
        self.assertEqual(select_specialists(self.spec, self.plan), ["frontend"])
        self.assertEqual(task_complexity(self.spec, self.plan, ["frontend"]), "low")
        self.assertEqual(
            task_complexity(self.spec, self.plan, ["ai_ml", "integration"]), "high"
        )
        self.spec["sections"]["scope"] = (
            "No backend, database, authentication, or infrastructure changes"
        )
        self.assertEqual(select_specialists(self.spec, self.plan), ["frontend"])
        examples = [
            ("API endpoint", ["backend"]),
            ("Deploy Docker configuration", ["devops"]),
            ("Data ingestion", ["data_engineer"]),
            ("Forecast sales", ["data_scientist"]),
            ("Research agent pipeline", ["ai_ml", "integration"]),
            ("Mobile iOS screen", ["mobile"]),
            ("Improve latency", ["performance"]),
            ("Implement authentication", ["security"]),
            ("Full application feature", ["full_stack"]),
        ]
        for title, expected in examples:
            with self.subTest(title=title):
                spec = {
                    **self.spec,
                    "title": title,
                    "sections": {"objective": title, "scope": "fixture"},
                }
                self.assertEqual(select_specialists(spec, self.plan), expected)

    def test_unapproved_and_tampered_inputs_cannot_dispatch(self):
        with self.assertRaises(Denied):
            self.dispatch(authority=Authority(False))
        with self.assertRaises(Denied):
            self.dispatch(repository=self.worktree)
        with self.assertRaises(Denied):
            self.dispatch(scope=[".dev/approval.json"])
        self.plan["spec_sha256"] = "0" * 64
        self.plan_raw = raw(self.plan)
        with self.assertRaises(Denied):
            self.dispatch()

    def test_separate_owner_transition_requires_independent_decision(self):
        pending = approval_request(
            self.spec_raw,
            self.plan_raw,
            project="dev-001",
            task_id="T-0042",
            repository=self.repo,
            worktree_root=self.worktrees,
            scope=["index.html"],
        )
        schema_root = Path(__file__).parents[1] / "developer_v1" / "schemas"
        Draft202012Validator(
            json.loads(
                (schema_root / "development-approval-request.schema.json").read_text()
            )
        ).validate(pending)

        class NoDecision:
            def verify(self, reference, expected):
                raise Denied("owner did not approve")

        with self.assertRaises(Denied):
            stage_owner_transition(
                pending,
                decision_reference="d1",
                expected_owner="owner",
                verifier=NoDecision(),
                grant_reference="g1",
            )

        class VerifiedDecision:
            def verify(self, reference, expected):
                return {
                    **expected,
                    "reference": reference,
                    "owner": "owner",
                    "decision": "approve_development",
                    "source": "independent_owner_channel",
                }

        grant = stage_owner_transition(
            pending,
            decision_reference="d1",
            expected_owner="owner",
            verifier=VerifiedDecision(),
            grant_reference="g1",
        )
        Draft202012Validator(
            json.loads((schema_root / "development-grant.schema.json").read_text())
        ).validate(grant)

        class ProtectedStoreFixture:
            def verify(self, reference, expected):
                if reference != "g1":
                    raise Denied("unknown grant")
                return grant

        routed = self.dispatch(
            authority=ProtectedStoreFixture(), authorization_reference="g1"
        )
        self.assertEqual(routed["authorization_reference"], "g1")
        with self.assertRaises(Denied):
            self.dispatch(
                authority=ProtectedStoreFixture(),
                authorization_reference="g1",
                scope=["other.py"],
            )

    def test_model_primary_fallback_override_and_cost(self):
        config = {
            "schema": "alfred.developer-models/1",
            "providers": {
                "p": {
                    "m1": {
                        "capabilities": ["code"],
                        "max_task_cost": 4,
                        "max_complexity": "medium",
                    }
                },
                "q": {
                    "m2": {
                        "capabilities": ["code"],
                        "max_task_cost": 2,
                        "max_complexity": "high",
                    }
                },
            },
            "specialists": {
                "frontend": {
                    "primary": {"provider": "p", "model": "m1"},
                    "fallback": {"provider": "q", "model": "m2"},
                    "reasoning_effort": "medium",
                    "tools": ["read_scoped", "write_scoped"],
                }
            },
        }
        choice = select_model(
            config,
            "frontend",
            available={("p", "m1"), ("q", "m2")},
            required_capabilities={"code"},
            max_cost=3,
        )
        self.assertEqual(
            (choice.provider, choice.model, choice.fallback_used), ("q", "m2", True)
        )
        complex_choice = select_model(
            config,
            "frontend",
            available={("p", "m1"), ("q", "m2")},
            required_capabilities={"code"},
            max_cost=9,
            complexity="high",
        )
        self.assertEqual(complex_choice.model, "m2")
        with self.assertRaises(Denied):
            select_model(
                config,
                "frontend",
                available={("p", "m1")},
                required_capabilities={"code"},
                max_cost=3,
            )
        with self.assertRaises(Denied):
            select_model(
                config,
                "frontend",
                available={("p", "m1")},
                required_capabilities={"code"},
                max_cost=9,
                override={"provider": "other", "model": "m3"},
            )
        attempts = []

        def caller(choice):
            attempts.append(choice.model)
            if choice.model == "m1":
                raise ProviderUnavailable("fixture outage")
            return "ok"

        used, answer = invoke_model(
            config,
            "frontend",
            available={("p", "m1"), ("q", "m2")},
            required_capabilities={"code"},
            max_cost=9,
            caller=caller,
        )
        self.assertEqual((attempts, used.model, answer), (["m1", "m2"], "m2", "ok"))

    def test_cto_model_plan_uses_capability_and_budget(self):
        config = {
            "schema": "alfred.developer-models/1",
            "providers": {
                "fixture": {
                    "ui": {
                        "capabilities": ["code", "ui"],
                        "max_task_cost": 2,
                        "max_complexity": "medium",
                    }
                }
            },
            "specialists": {
                "frontend": {
                    "primary": {"provider": "fixture", "model": "ui"},
                    "fallback": None,
                    "reasoning_effort": "medium",
                    "tools": ["read_scoped"],
                }
            },
        }
        chosen = plan_models(
            self.spec,
            self.plan,
            ["frontend"],
            config,
            available={("fixture", "ui")},
            total_cost_limit=2,
        )
        self.assertEqual(chosen["frontend"].model, "ui")
        with self.assertRaises(Denied):
            plan_models(
                self.spec,
                self.plan,
                ["frontend"],
                config,
                available={("fixture", "ui")},
                total_cost_limit=1,
            )

    def test_staged_invocation_evidence_qa_and_duplicate(self):
        dispatch = self.dispatch()
        schema_root = Path(__file__).parents[1] / "developer_v1" / "schemas"
        schema = json.loads(
            (schema_root / "developer-dispatch.schema.json").read_text()
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(dispatch)
        worker = FakeWorker()
        assignment = self.assignment()
        with self.assertRaises(Denied):
            invoke(
                dispatch,
                assignment,
                worktree=self.worktree,
                model=self.model,
                worker=worker,
                store=self.state,
            )
        report = invoke(
            dispatch,
            assignment,
            worktree=self.worktree,
            model=self.model,
            worker=worker,
            store=self.state,
            synthetic=True,
        )
        schema = json.loads((schema_root / "developer-report.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(report)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(
            report["files_modified"][0]["sha256"],
            hashlib.sha256(b"changed\n").hexdigest(),
        )
        self.assertEqual(report["model_used"]["model"], "m1")
        git(self.worktree, "add", "index.html")
        git(self.worktree, "commit", "-qm", "integrate synthetic change")
        qa_input = qa_manifest([report], [assignment], self.worktree)
        self.assertEqual(qa_input["state"], "ready_for_independent_qa")
        schema = json.loads((schema_root / "qa-input.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(qa_input)
        with self.assertRaises(Denied):
            invoke(
                dispatch,
                assignment,
                worktree=self.worktree,
                model=self.model,
                worker=worker,
                store=self.state,
                synthetic=True,
            )
        self.assertEqual(worker.calls, 1)

    def test_worktree_and_parallel_assignment_boundaries(self):
        dispatch = self.dispatch()
        assignment = self.assignment()
        with self.assertRaises(Denied):
            invoke(
                dispatch,
                assignment,
                worktree=self.repo,
                model=self.model,
                worker=FakeWorker(),
                store=self.state,
                synthetic=True,
            )
        self.state.claim(assignment)
        other = {**assignment, "id": "item-b"}
        with self.assertRaises(Denied):
            self.state.claim(other)
        dependent = {
            **assignment,
            "id": "item-c",
            "files": ["other.py"],
            "depends_on": ["item-b"],
        }
        with self.assertRaises(Denied):
            self.state.claim(dependent)

    def test_assignment_compiler_rejects_overlap_and_cycles(self):
        dispatch = self.dispatch()
        item = {
            "id": "a",
            "specialist": "frontend",
            "files": ["index.html"],
            "depends_on": [],
            "objective": "theme",
        }
        compiled = build_assignments(dispatch, [item])
        schema = json.loads(
            (
                Path(__file__).parents[1]
                / "developer_v1"
                / "schemas"
                / "developer-assignment.schema.json"
            ).read_text()
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(compiled[0])
        self.assertEqual(
            (compiled[0]["project"], compiled[0]["task_id"]), ("dev-001", "T-0042")
        )
        with self.assertRaises(Denied):
            build_assignments(dispatch, [item, {**item, "id": "b"}])
        with self.assertRaises(Denied):
            build_assignments(dispatch, [{**item, "depends_on": ["a"]}])

    def test_dependent_specialist_waits_and_preserves_task_identity(self):
        dispatch = {
            **self.dispatch(),
            "specialists": ["ai_ml", "integration"],
            "scope": ["agent.py", "client.py"],
        }
        items = build_assignments(
            dispatch,
            [
                {
                    "id": "agent",
                    "specialist": "ai_ml",
                    "files": ["agent.py"],
                    "depends_on": [],
                    "objective": "Build pipeline",
                },
                {
                    "id": "client",
                    "specialist": "integration",
                    "files": ["client.py"],
                    "depends_on": ["agent"],
                    "objective": "Connect provider",
                },
            ],
        )
        self.assertEqual({item["task_id"] for item in items}, {"T-0042"})
        with self.assertRaises(Denied):
            self.state.claim(items[1])
        self.state.claim(items[0])
        with self.assertRaises(Denied):
            self.state.claim(items[1])
        self.state.finish(items[0], "completed")
        self.state.claim(items[1])

    def test_concurrent_duplicate_claim_is_single_winner(self):
        context = multiprocessing.get_context("fork")
        start, results = context.Event(), context.Queue()
        assignment = self.assignment()
        workers = [
            context.Process(
                target=claim_in_process,
                args=(str(self.state.root), assignment, start, results),
            )
            for _ in range(2)
        ]
        for worker in workers:
            worker.start()
        start.set()
        outcomes = sorted(results.get(timeout=5) for _ in workers)
        for worker in workers:
            worker.join(5)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(outcomes, ["claimed", "denied"])

    def test_blocked_reports_have_blockers_and_cannot_reach_qa(self):
        dispatch = self.dispatch()
        assignment = self.assignment()
        report = invoke(
            dispatch,
            assignment,
            worktree=self.worktree,
            model=self.model,
            worker=FakeWorker("blocked"),
            store=self.state,
            synthetic=True,
        )
        self.assertEqual(report["blockers"], ["synthetic dependency unavailable"])
        with self.assertRaises(Denied):
            qa_manifest([report], [assignment], self.worktree)

    def test_worker_exception_produces_failed_report(self):
        report = invoke(
            self.dispatch(),
            self.assignment(),
            worktree=self.worktree,
            model=self.model,
            worker=RaisingWorker(),
            store=self.state,
            synthetic=True,
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["blockers"], ["worker exception: RuntimeError"])
        self.assertFalse(report["qa_handoff"]["ready"])

    def test_worker_cannot_hand_off_gateway_authority_write(self):
        with self.assertRaises(Denied):
            invoke(
                self.dispatch(),
                self.assignment(),
                worktree=self.worktree,
                model=self.model,
                worker=ForbiddenWriteWorker(),
                store=self.state,
                synthetic=True,
            )
        self.assertEqual(
            json.loads((self.state.root / "item-a.json").read_text())["status"],
            "failed",
        )


if __name__ == "__main__":
    unittest.main()
