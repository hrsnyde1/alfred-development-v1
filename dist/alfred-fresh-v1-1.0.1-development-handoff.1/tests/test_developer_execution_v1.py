import hashlib
import json
import os
import subprocess
import tempfile
import time
import unittest
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from developer_v1.approval_transition import approval_request
from developer_v1.gateway_adapter import GatewayInputs
from developer_v1.owner_grants import DevelopmentGrantIssuer, ProtectedDevelopmentAuthority
from developer_v1 import owner_grants
from developer_v1.pipeline import execute_approved
from developer_v1.real_worker import CodexReadOnlyBroker
from developer_v1.router import (CAPABILITY_BY_ROLE, Denied, ProviderUnavailable,
                                 SPECIALISTS, canonical_binding, select_model)
from developer_v1.trusted_intake_development import IntakeGate, IntakeRefused


def raw(value):
    return json.dumps(value, sort_keys=True).encode()


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


class FixtureBroker:
    def authenticated(self):
        return True

    def generate(self, choice, *, objective, sources):
        return {"edits": [{"path": "calculator.py", "content":
                 "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n"}],
                "summary": "Added subtract"}


class FallbackBroker(FixtureBroker):
    def generate(self, choice, *, objective, sources):
        if choice.model == "gpt-6-sol":
            raise ProviderUnavailable("fixture primary outage")
        return super().generate(choice, objective=objective, sources=sources)


class OutsideScopeBroker(FixtureBroker):
    def generate(self, choice, *, objective, sources):
        return {"edits": [{"path": ".dev/approval.json", "content": "forged"}],
                "summary": "unauthorized"}


class ExecutionFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="alfred-dev-v1-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
        (self.repo / "test_calculator.py").write_text(
            "import unittest\nfrom calculator import add, subtract\n"
            "class CalculatorTest(unittest.TestCase):\n"
            "    def test_subtract(self):\n        self.assertEqual(subtract(7, 3), 4)\n")
        git(self.repo, "add", ".")
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "-qm", "baseline"], check=True)
        self.worktrees = self.root / "worktrees"
        self.worktrees.mkdir()
        self.grants = self.root / "grants"
        self.grants.mkdir(mode=0o700)
        self.spec = {"project": "dev-999", "id": "T-0099", "source": "hermes", "status": "proposed",
                     "request_id": "0a424953-c874-49a2-a2dd-cd62a5e19712", "title": "API endpoint",
                     "sections": {"objective": "Add subtract helper to calculator.py"}}
        self.spec_raw = raw(self.spec)
        self.plan = {"schema": "alfred.cto-plan/1", "project": "dev-999", "task_id": "T-0099",
                     "request_id": self.spec["request_id"],
                     "spec_sha256": hashlib.sha256(self.spec_raw).hexdigest(),
                     "approval_state": "awaiting_development_approval", "clarification_required": False,
                     "repository": str(self.repo), "repository_evidence": {"files": ["calculator.py"]},
                     "developer_work_items": ["Add subtract"], "expected_components_files": ["calculator.py"]}
        self.plan_raw = raw(self.plan)
        self.inputs = GatewayInputs(self.repo, self.spec_raw, self.plan_raw, json.loads)
        self.request = approval_request(self.spec_raw, self.plan_raw, project="dev-999",
                     task_id="T-0099", repository=self.repo, worktree_root=self.worktrees,
                     scope=["calculator.py"])
        self.issuer = DevelopmentGrantIssuer(self.grants, owner_sender_id="owner", sidecar_uid=1234, admin_uid=0,
                                             environment="staging",
                                             preview_sender=lambda space, text: "photon-plan-message")
        self.items = [{"id": "backend-work", "specialist": "backend", "files": ["calculator.py"],
                       "depends_on": [], "objective": "Add subtract(a, b) returning a minus b."}]
        model = {"provider": "codex", "model": "gpt-6-sol"}
        self.models = {"schema": "alfred.developer-models/1",
                       "providers": {"codex": {name: {"capabilities": ["code"],
                                     "max_complexity": "high", "max_task_cost": 1}
                                     for name in ("gpt-6-sol", "gpt-6.1-sol")}},
                       "specialists": {role: {"primary": model,
                                       "fallback": {"provider": "codex", "model": "gpt-6.1-sol"},
                                       "reasoning_effort": "low",
                                       "tools": ["read_scoped", "write_scoped", "run_approved_check",
                                                 "git_local_commit_if_granted"]} for role in SPECIALISTS}}

    def grant(self):
        self.issuer.stage(self.request, space_id="dm-owner", peer_uid=0)
        event = {"messageId": "photon-owner-reply", "direction": "inbound",
                 "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "sender": {"id": "owner"}, "space": {"id": "dm-owner", "type": "dm"},
                 "nativeReplyTargetGuid": "photon-plan-message", "nativeIsForward": False,
                 "content": {"type": "text", "text":
                             "Approve development dev-999 T-0099 " + self.request["plan_sha256"][:12]}}
        return self.issuer.observe(event, peer_uid=1234)["reference"]

    def expected(self):
        return canonical_binding(self.spec_raw, self.plan_raw, project="dev-999",
                    task_id="T-0099", repository=self.repo, worktree_root=self.worktrees,
                    scope=["calculator.py"], specialists=["backend"])[2]

    def execute(self, reference, broker):
        return execute_approved(self.inputs, project="dev-999", task_id="T-0099",
                   worktree_root=self.worktrees, scope=["calculator.py"], grant_reference=reference,
                   grant_root=self.grants, items=self.items, models=self.models,
                   state_root=self.root / "state", total_cost_limit=3, broker=broker,
                   grant_environment="staging")

    def test_grant_requires_native_owner_target_and_exact_binding(self):
        self.assertEqual(len(SPECIALISTS), 11)
        with self.assertRaises(Denied):
            self.execute("unapproved", FixtureBroker())
        self.issuer.stage(self.request, space_id="dm-owner", peer_uid=0)
        bad = {"messageId": "reply", "direction": "inbound", "sender": {"id": "owner"},
               "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
               "space": {"id": "dm-owner", "type": "dm"}, "nativeReplyTargetGuid": "wrong",
               "nativeIsForward": False, "content": {"type": "text", "text": "Approve development"}}
        self.assertEqual(self.issuer.observe(bad, peer_uid=1234)["state"], "not_development_approval")
        with self.assertRaises(Denied):
            self.issuer.observe({**bad, "nativeReplyTargetGuid": "photon-plan-message"}, peer_uid=1234)
        # A new issuer fixture owns only this temporary directory. It is never
        # a grant in the configured production authority store.
        self.assertFalse(list(self.grants.glob("grant-*.json")))

    def test_verified_model_config_has_independent_slots_for_all_specialists(self):
        config = json.loads((Path(__file__).parents[1] / "developer_v1" /
                             "models.codex-verified.example.json").read_text())
        self.assertEqual(set(config["specialists"]), set(SPECIALISTS))
        available = {("codex", model) for model in config["providers"]["codex"]}
        for role in SPECIALISTS:
            with self.subTest(role=role):
                primary = select_model(config, role, available=available,
                            required_capabilities=CAPABILITY_BY_ROLE[role],
                            max_cost=2, complexity="high")
                self.assertEqual(primary.model, config["specialists"][role]["primary"]["model"])
                fallback = select_model(config, role, available=available - {(primary.provider, primary.model)},
                            required_capabilities=CAPABILITY_BY_ROLE[role],
                            max_cost=2, complexity="high")
                self.assertTrue(fallback.fallback_used)

    def test_intake_extension_only_accepts_root_staging_and_photon_observation(self):
        gate = object.__new__(IntakeGate)
        gate.sidecar_uid = 1234
        gate.hermes_uid = 5678
        gate.development_issuer = self.issuer
        gate.development_inputs = lambda project, task: self.inputs
        request = {"op": "stage_development_approval", "project": "dev-999", "task_id": "T-0099",
                   "scope": ["calculator.py"], "worktree_root": str(self.worktrees), "space_id": "dm-owner"}
        with self.assertRaises(IntakeRefused):
            gate.dispatch(request, 5678)
        self.assertEqual(gate.dispatch(request, 0)["state"], "awaiting_native_owner_reply")
        event = {"messageId": "reply", "direction": "inbound", "sender": {"id": "owner"},
                 "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "space": {"id": "dm-owner", "type": "dm"}, "nativeReplyTargetGuid": "photon-plan-message",
                 "nativeIsForward": False, "content": {"type": "text", "text":
                 "Approve development dev-999 T-0099 " + self.request["plan_sha256"][:12]}}
        with self.assertRaises(IntakeRefused):
            gate.dispatch({"op": "observe", "event": event}, 5678)
        result = gate.dispatch({"op": "observe", "event": event}, 1234)
        self.assertEqual(result["state"], "development_approved")
        expected = canonical_binding(self.spec_raw, self.plan_raw, project="dev-999",
                    task_id="T-0099", repository=self.repo, worktree_root=self.worktrees,
                    scope=["calculator.py"], specialists=["backend"])[2]
        with self.assertRaises(Denied):
            ProtectedDevelopmentAuthority(self.grants).verify(result["reference"], expected)
        self.assertEqual(ProtectedDevelopmentAuthority(self.grants, environment="staging").verify(result["reference"], expected)["owner_event_id"], "reply")
        (self.grants / f"revoke-{result['reference']}").touch(mode=0o600)
        with self.assertRaises(Denied):
            ProtectedDevelopmentAuthority(self.grants, environment="staging").verify(result["reference"], expected)

    def test_authorized_worker_handoff_and_duplicate(self):
        reference = self.grant()
        reports, qa = self.execute(reference, FixtureBroker())
        self.assertEqual(reports[0]["status"], "completed")
        self.assertEqual(reports[0]["model_used"]["model"], "gpt-6-sol")
        self.assertEqual(reports[0]["tests"][0]["outcome"], "passed")
        self.assertEqual(len(reports[0]["commits"]), 1)
        self.assertEqual(qa["state"], "ready_for_independent_qa")
        self.assertIn("return a - b", (Path(qa["final_worktree"]) / "calculator.py").read_text())
        self.assertEqual(json.loads((self.grants / f"execution-result-{reference}.json").read_text())["status"], "completed")
        with self.assertRaises(Denied):
            self.execute(reference, FixtureBroker())
        self.plan_raw = raw({**self.plan, "planning_note": "changed after approval"})
        self.inputs = GatewayInputs(self.repo, self.spec_raw, self.plan_raw, json.loads)
        with self.assertRaises(Denied):
            self.execute(reference, FixtureBroker())

    def test_approved_fallback_is_recorded(self):
        reference = self.grant()
        reports, qa = self.execute(reference, FallbackBroker())
        self.assertTrue(reports[0]["model_used"]["fallback_used"])
        self.assertEqual(reports[0]["model_used"]["model"], "gpt-6.1-sol")
        self.assertEqual(qa["state"], "ready_for_independent_qa")

    def test_codex_absolute_path_survives_restricted_path_and_pins_target(self):
        executable = self.root / "codex-fixture"
        executable.write_text("#!/bin/sh\n"
                              "if [ \"$1\" = login ] && [ \"$2\" = status ]; then\n"
                              "  echo 'Logged in'\n  exit 0\nfi\nexit 1\n")
        executable.chmod(0o755)
        link = self.root / ".local" / "bin" / "codex"
        link.parent.mkdir(parents=True)
        link.symlink_to(executable)
        with patch("developer_v1.real_worker.pwd.getpwuid",
                   return_value=SimpleNamespace(pw_dir=str(self.root))), \
             patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            broker = CodexReadOnlyBroker()
            self.assertEqual(broker.require_executable(), str(executable))
            self.assertTrue(broker.authenticated())
            link.unlink()
            other = self.root / "other-codex-fixture"
            other.write_text("#!/bin/sh\nexit 1\n")
            other.chmod(0o755)
            link.symlink_to(other)
            self.assertEqual(broker.require_executable(), str(executable))
            self.assertTrue(broker.authenticated())

    def test_missing_codex_fails_before_single_use_claim(self):
        reference = self.grant()
        missing = self.root / "missing-codex"
        with self.assertRaisesRegex(Denied, "Codex executable unavailable at configured path"):
            self.execute(reference, CodexReadOnlyBroker(executable=str(missing)))
        self.assertFalse((self.grants / f"execution-{reference}.json").exists())
        self.assertFalse((self.grants / f"execution-result-{reference}.json").exists())
        self.assertFalse(list(self.worktrees.iterdir()))
        self.assertFalse((self.root / "state").exists())

    def test_failed_worker_records_blocker_without_qa(self):
        reference = self.grant()
        with self.assertRaises(Denied):
            self.execute(reference, OutsideScopeBroker())
        report = json.loads((self.root / "state" / "dev-999" / "T-0099" /
                             "report-backend-work.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["blockers"])
        self.assertFalse(report["qa_handoff"]["ready"])
        self.assertFalse((self.repo / ".dev" / "approval.json").exists())
        self.assertEqual(json.loads((self.grants / f"execution-result-{reference}.json").read_text())["status"], "failed")

    def test_challenge_and_native_decision_evidence(self):
        reference = self.grant()
        receipt = json.loads((self.grants / f"challenge-{reference}.json").read_text())
        decision = json.loads((self.grants / f"decision-{reference}.json").read_text())
        issuance = json.loads((self.grants / f"issuance-{reference}.json").read_text())
        self.assertEqual(receipt["request"], self.request)
        self.assertEqual(decision["native_reply_target"], receipt["message_id"])
        self.assertEqual(decision["sender_id"], receipt["owner_id"])
        self.assertEqual(set(decision["checks"].values()), {True})
        self.assertEqual(issuance["challenge_sha256"], owner_grants._digest(receipt))
        self.assertFalse((self.grants / f"pending-{reference}.json").exists())
        authority = ProtectedDevelopmentAuthority(self.grants, environment="staging")
        self.assertEqual(authority.verify(reference, self.expected())["task_id"], "T-0099")
        with self.assertRaises(Denied):
            self.issuer.observe({"nativeReplyTargetGuid": receipt["message_id"]}, peer_uid=1234)

    def test_attempted_send_does_not_create_challenge_receipt(self):
        self.issuer.send = lambda space, text: None
        with self.assertRaises(owner_grants.DevelopmentSendFailure) as failure:
            self.issuer.stage(self.request, space_id="dm-owner", peer_uid=0)
        self.assertEqual(failure.exception.delivery_state, "uncertain")
        # The durable one-use intent survives an invalid ACK; no receipt/grant
        # is fabricated and a fresh process cannot silently send it again.
        self.assertFalse(list(self.grants.glob("challenge-*.json")))
        self.assertFalse(list(self.grants.glob("grant-*.json")))
        self.assertEqual(len(list(self.grants.glob("development-send-*.json"))), 2)

    def test_forged_forwarded_stale_unthreaded_and_mismatched_replies(self):
        self.issuer.stage(self.request, space_id="dm-owner", peer_uid=0)
        good = {"messageId": "fresh-reply", "direction": "inbound",
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                "sender": {"id": "owner"}, "space": {"id": "dm-owner", "type": "dm"},
                "nativeReplyTargetGuid": "photon-plan-message", "nativeIsForward": False,
                "content": {"type": "text", "text":
                            "Approve development dev-999 T-0099 " + self.request["plan_sha256"][:12]}}
        self.assertEqual(self.issuer.observe({**good, "nativeReplyTargetGuid": None}, peer_uid=1234)["state"], "not_development_approval")
        self.assertEqual(self.issuer.observe({**good, "nativeReplyTargetGuid": "wrong"}, peer_uid=1234)["state"], "not_development_approval")
        for altered in ({"sender": {"id": "forged"}}, {"space": {"id": "other", "type": "dm"}},
                        {"nativeIsForward": True}, {"content": {"type": "text", "text": "quoted approval"}},
                        {"content": {"type": "text", "text": " " + good["content"]["text"]}},
                        {"timestamp": "2000-01-01T00:00:00Z"}):
            with self.subTest(altered=tuple(altered)):
                with self.assertRaises(Denied):
                    self.issuer.observe({**good, **altered}, peer_uid=1234)
        with self.assertRaises(Denied):
            self.issuer.observe(good, peer_uid=5678)
        self.assertFalse(list(self.grants.glob("grant-*.json")))
        self.issuer.clock = lambda: time.time() + 301
        with self.assertRaises(Denied):
            self.issuer.observe(good, peer_uid=1234)
        self.issuer.clock = time.time
        self.assertEqual(self.issuer.observe(good, peer_uid=1234)["state"], "development_approved")

    def test_tampering_or_missing_historical_evidence_fails(self):
        reference = self.grant()
        authority = ProtectedDevelopmentAuthority(self.grants, environment="staging")
        for prefix in ("grant", "challenge", "decision", "issuance"):
            path = self.grants / f"{prefix}-{reference}.json"
            original = path.read_bytes()
            record = json.loads(original)
            record["tampered"] = True
            path.write_text(json.dumps(record))
            with self.subTest(prefix=prefix), self.assertRaises(Denied):
                authority.verify(reference, self.expected())
            path.write_bytes(original)
        (self.grants / f"issuance-{reference}.json").unlink()
        with self.assertRaises(Denied):
            authority.verify(reference, self.expected())

    def test_changed_plan_repository_scope_or_specialist_is_denied(self):
        reference = self.grant()
        authority = ProtectedDevelopmentAuthority(self.grants, environment="staging")
        grant_path = self.grants / f"grant-{reference}.json"
        original = grant_path.read_bytes()
        for field, value in (("plan_sha256", "0" * 64),
                             ("repository", str(self.root / "other-repo")),
                             ("scope", ["test_calculator.py"]),
                             ("specialists", ["frontend"])):
            with self.subTest(field=field):
                grant = json.loads(original)
                grant[field] = value
                grant_path.write_text(json.dumps(grant))
                with self.assertRaises(Denied):
                    authority.verify(reference, self.expected())
                grant_path.write_bytes(original)

    def test_claim_is_single_use_concurrent_and_crash_safe(self):
        reference = self.grant()
        authority = ProtectedDevelopmentAuthority(self.grants, environment="staging")
        expected = self.expected()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: self._try_claim(authority, reference, expected), range(2)))
        self.assertEqual(sorted(outcomes), ["claimed", "denied"])
        with self.assertRaises(Denied):
            authority.claim(reference, expected, run_sha256="a" * 64)
        self.assertFalse((self.grants / f"execution-result-{reference}.json").exists())
        self.assertEqual(json.loads((self.grants / f"execution-{reference}.json").read_text())[
            "status_if_no_result"], "uncertain")
        authority.finish(reference, status="uncertain")
        with self.assertRaises(Denied):
            authority.finish(reference, status="completed")

    @staticmethod
    def _try_claim(authority, reference, expected):
        try:
            authority.claim(reference, expected, run_sha256="a" * 64)
            return "claimed"
        except Denied:
            return "denied"

    def test_legacy_grant_requires_revoke_before_new_challenge(self):
        # Create an actual pre-intent historical fixture. Removing one evidence
        # file from a modern grant does not turn its one-use send into a legacy
        # send or authorize a second transmission.
        import importlib.util
        import sys
        original = Path(__file__).resolve().parents[1] / "dist/alfred-fresh-v1-1.0.1/developer_v1/owner_grants.py"
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), "d8e88bf8f42a0eb19e3f3d5a80d1985daf33ced47c318cd1826210799a40e463")
        loader = importlib.util.spec_from_file_location("developer_v1._legacy_grants_test", original)
        legacy = importlib.util.module_from_spec(loader)
        sys.modules[loader.name] = legacy
        loader.loader.exec_module(legacy)
        corrected = self.issuer
        self.issuer = legacy.DevelopmentGrantIssuer(self.grants, owner_sender_id="owner", sidecar_uid=1234,
            environment="staging", preview_sender=lambda *_: "photon-plan-message")
        reference = self.grant()
        self.issuer = corrected
        (self.grants / f"issuance-{reference}.json").unlink()
        with self.assertRaises(Denied):
            ProtectedDevelopmentAuthority(self.grants, environment="staging").verify(reference, self.expected())
        with self.assertRaises(Denied):
            self.execute(reference, FixtureBroker())
        self.assertFalse(list(self.grants.glob("execution-*.json")))
        self.assertFalse(list(self.worktrees.iterdir()))
        with self.assertRaises(Denied):
            self.issuer.stage(self.request, space_id="dm-owner", peer_uid=0)
        gate = object.__new__(IntakeGate)
        gate.sidecar_uid = 1234
        gate.hermes_uid = 5678
        gate.development_issuer = self.issuer
        operation = {"op": "revoke_development_grant", "project": "dev-999", "task_id": "T-0099"}
        with self.assertRaises(IntakeRefused):
            gate.dispatch(operation, 5678)
        self.assertEqual(gate.dispatch(operation, 0)["state"], "development_grant_revoked")
        with self.assertRaises(IntakeRefused):
            gate.dispatch(operation, 0)
        self.assertEqual(self.issuer.stage(self.request, space_id="dm-owner", peer_uid=0)["state"], "awaiting_native_owner_reply")

    def test_crash_after_decision_cannot_issue_or_replay(self):
        self.issuer.stage(self.request, space_id="dm-owner", peer_uid=0)
        event = {"messageId": "reply", "direction": "inbound",
                 "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "sender": {"id": "owner"}, "space": {"id": "dm-owner", "type": "dm"},
                 "nativeReplyTargetGuid": "photon-plan-message", "nativeIsForward": False,
                 "content": {"type": "text", "text":
                             "Approve development dev-999 T-0099 " + self.request["plan_sha256"][:12]}}
        original = owner_grants._write_once
        def fail_issuance(root, name, value):
            if name.startswith("issuance-"):
                raise OSError("synthetic crash")
            return original(root, name, value)
        with patch.object(owner_grants, "_write_once", side_effect=fail_issuance):
            with self.assertRaises(OSError):
                self.issuer.observe(event, peer_uid=1234)
        self.assertFalse(list(self.grants.glob("grant-*.json")))
        with self.assertRaises(Denied):
            self.issuer.observe(event, peer_uid=1234)

    def test_wrong_repository_binding_is_denied(self):
        reference = self.grant()
        other = self.root / "other-repo"
        other.mkdir()
        self.inputs = GatewayInputs(other, self.spec_raw, self.plan_raw, json.loads)
        with self.assertRaises(Denied):
            self.execute(reference, FixtureBroker())

    def test_clarification_plan_cannot_stage(self):
        plan = raw({**self.plan, "clarification_required": True})
        with self.assertRaises(Denied):
            approval_request(self.spec_raw, plan, project="dev-999", task_id="T-0099",
                             repository=self.repo, worktree_root=self.worktrees,
                             scope=["calculator.py"])

    def test_real_codex_model_invocation(self):
        if os.environ.get("ALFRED_REAL_MODEL_ACCEPTANCE") != "1":
            self.skipTest("explicit disposable real-model acceptance only")
        broker = CodexReadOnlyBroker()
        self.assertTrue(broker.authenticated())
        reference = self.grant()
        reports, qa = self.execute(reference, broker)
        self.assertEqual(reports[0]["model_used"]["model"], "gpt-6-sol")
        self.assertEqual(qa["state"], "ready_for_independent_qa")

