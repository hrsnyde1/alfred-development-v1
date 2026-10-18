"""Owner-delegated development approval: Alfred approves CTO plans for the projects the
owner's root-protected policy lists. Publication always stays with the owner."""

import hashlib
import json
import os
import unittest

from developer_v1 import owner_grants
from developer_v1.owner_grants import (DevelopmentGrantIssuer, ProtectedDevelopmentAuthority,
                                       load_delegation_policy)
from developer_v1.pipeline import execute_approved
from developer_v1.router import Denied
from independent_qa import worker as qa_worker
from tests import test_developer_execution_v1 as base


def policy(projects=("dev-999",), enabled=True, publication="owner"):
    return {"schema": "alfred.development-delegation-policy/1",
            "development_approval": {"enabled": enabled, "projects": list(projects)},
            "publication_approval": publication}


class DelegationFixture(unittest.TestCase):
    def setUp(self):
        # Reuse the execution fixture's repository, plan and grant store by composition,
        # so its own tests are not collected again here.
        self.f = base.ExecutionFixture("test_verified_model_config_has_independent_slots_for_all_specialists")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.grants = self.f.grants
        self.policy_path = self.f.root / "delegation.json"
        self.sent = []
        self.issuer = DevelopmentGrantIssuer(
            self.grants, owner_sender_id="owner", sidecar_uid=1234, admin_uid=0,
            environment="staging", delegation_policy=self.policy_path,
            preview_sender=lambda space, text: self.sent.append(text) or "photon-plan-message")

    def write_policy(self, value, mode=0o644):
        self.policy_path.unlink(missing_ok=True)
        self.policy_path.write_text(json.dumps(value))
        self.policy_path.chmod(mode)

    def authority(self):
        return ProtectedDevelopmentAuthority(self.grants, environment="staging",
                                             delegation_policy=self.policy_path)

    def delegate(self):
        return self.issuer.stage(self.f.request, space_id="dm-owner", peer_uid=0)

    def execute(self, reference):
        f = self.f
        return execute_approved(f.inputs, project="dev-999", task_id="T-0099",
                   worktree_root=f.worktrees, scope=["calculator.py"], grant_reference=reference,
                   grant_root=self.grants, items=f.items, models=f.models,
                   state_root=f.root / "state", total_cost_limit=3, broker=base.FixtureBroker(),
                   grant_environment="staging", delegation_policy=self.policy_path)


class DelegatedApprovalTest(DelegationFixture):
    def test_listed_project_is_approved_without_texting_the_owner(self):
        self.write_policy(policy())
        result = self.delegate()
        self.assertEqual(result["state"], "development_approved_by_delegation")
        self.assertEqual(result["challenge"], result["reference"])
        self.assertEqual(self.sent, [])
        grant = self.authority().verify(result["reference"], self.f.expected())
        self.assertEqual(grant["source"], "delegated_owner_policy")
        self.assertNotIn("owner_event_id", grant)
        record = json.loads((self.grants / f"delegation-{result['reference']}.json").read_text())
        self.assertEqual(record["decided_by"], "owner_delegation_policy")
        # Nothing that resembles an owner reply is ever written.
        self.assertFalse(list(self.grants.glob("decision-*.json")))
        self.assertFalse(list(self.grants.glob("challenge-*.json")))

    def test_unlisted_disabled_or_absent_policy_texts_the_owner(self):
        for value in (None, policy(projects=("other-project",)), policy(enabled=False)):
            with self.subTest(policy=value):
                for path in self.grants.iterdir():
                    path.unlink()
                self.sent.clear()
                self.policy_path.unlink(missing_ok=True)
                if value is not None:
                    self.write_policy(value)
                self.assertEqual(self.delegate()["state"], "awaiting_native_owner_reply")
                self.assertEqual(len(self.sent), 1)
                self.assertFalse(list(self.grants.glob("delegation-*.json")))

    def test_unknown_publication_modes_and_wildcards_are_refused(self):
        for value in (policy(publication="alfred"), policy(projects=("*",)),
                      policy(projects=("dev-999", "dev-999")),
                      {**policy(), "deploy": True}):
            with self.subTest(policy=value):
                self.write_policy(value)
                with self.assertRaises(Denied):
                    self.delegate()
        self.assertFalse(list(self.grants.glob("grant-*.json")))
        self.assertEqual(self.sent, [])

    def test_policy_writable_by_others_or_owned_by_another_user_is_refused(self):
        self.write_policy(policy(), mode=0o666)
        with self.assertRaises(Denied):
            self.delegate()
        self.write_policy(policy())
        with self.assertRaises(Denied):
            load_delegation_policy(self.policy_path, owner_uid=os.geteuid() + 1)

    def test_host_only_trusts_a_root_owned_policy(self):
        if os.geteuid() == 0:
            self.skipTest("must run as an unprivileged user")
        self.write_policy(policy())
        with self.assertRaises(Denied):
            load_delegation_policy(self.policy_path, owner_uid=owner_grants._policy_owner("host"))

    def test_staging_never_reads_the_host_policy_implicitly(self):
        self.assertIsNone(ProtectedDevelopmentAuthority(self.grants, environment="staging")
                          .delegation_policy)
        self.assertEqual(ProtectedDevelopmentAuthority(self.grants).delegation_policy,
                         owner_grants.DELEGATION_POLICY)

    def test_one_decision_per_task(self):
        self.write_policy(policy())
        self.delegate()
        with self.assertRaises(Denied):
            self.delegate()
        # A delegation attempt that crashed before its grant also blocks the owner path.
        for path in self.grants.glob("grant-*.json"):
            path.unlink()
        self.write_policy(policy(projects=()))
        with self.assertRaises(Denied):
            self.delegate()
        self.assertEqual(self.sent, [])

    def test_removing_the_project_revokes_unexecuted_delegated_grants(self):
        self.write_policy(policy())
        reference = self.delegate()["reference"]
        self.write_policy(policy(projects=()))
        with self.assertRaises(Denied):
            self.authority().verify(reference, self.f.expected())
        self.policy_path.unlink()
        with self.assertRaises(Denied):
            self.authority().verify(reference, self.f.expected())

    def test_tampered_delegation_evidence_is_denied(self):
        self.write_policy(policy())
        reference = self.delegate()["reference"]
        record_path = self.grants / f"delegation-{reference}.json"
        original = record_path.read_bytes()
        for change in ({"decided_by": "owner"}, {"policy": policy(projects=("x",))},
                       {"request": {**json.loads(original)["request"], "scope": ["other.py"]}}):
            with self.subTest(change=change):
                record_path.write_bytes(json.dumps({**json.loads(original), **change},
                                                   sort_keys=True, separators=(",", ":")).encode())
                with self.assertRaises(Denied):
                    self.authority().verify(reference, self.f.expected())
        record_path.write_bytes(original)
        self.authority().verify(reference, self.f.expected())
        (self.grants / f"issuance-{reference}.json").unlink()
        with self.assertRaises(Denied):
            self.authority().verify(reference, self.f.expected())

    def test_delegated_grant_runs_the_developer_once(self):
        self.write_policy(policy())
        reference = self.delegate()["reference"]
        reports, qa = self.execute(reference)
        self.assertEqual(reports[0]["status"], "completed")
        self.assertEqual(qa["state"], "ready_for_independent_qa")
        with self.assertRaises(Denied):
            self.execute(reference)


class QADelegatedEvidenceTest(DelegationFixture):
    """Independent QA accepts delegated evidence only when it binds the exact request."""

    def evidence(self, publication="owner"):
        self.write_policy(policy(publication=publication))
        reference = self.delegate()["reference"]
        self.execute(reference)
        grant_raw = (self.grants / f"grant-{reference}.json").read_bytes()
        issuance = json.loads((self.grants / f"issuance-{reference}.json").read_text())
        expected = json.loads(
            (self.grants / f"delegation-{reference}.json").read_text())["request"]
        return reference, json.loads(grant_raw), hashlib.sha256(grant_raw).hexdigest(), \
            issuance, expected

    def test_qa_accepts_exact_delegated_evidence(self):
        reference, grant, grant_sha, issuance, expected = self.evidence()
        self.assertTrue(qa_worker.delegated_decision(
            self.grants, reference, grant, grant_sha, issuance, expected))

    def test_qa_accepts_delegated_evidence_when_draft_prs_are_delegated_too(self):
        # demo-site T-0007 (2026-10-18): QA refused the evidence after handoff.29.
        reference, grant, grant_sha, issuance, expected = self.evidence("delegated")
        self.assertTrue(qa_worker.delegated_decision(
            self.grants, reference, grant, grant_sha, issuance, expected))

    def test_qa_owner_reply_check_never_accepts_a_delegated_grant(self):
        reference, grant, grant_sha, issuance, expected = self.evidence()
        with self.assertRaises(qa_worker.QAFailure):
            qa_worker.owner_reply_decision(self.grants, reference, grant, grant_sha,
                                           issuance, expected)

    def test_qa_rejects_mismatched_delegated_evidence(self):
        reference, grant, grant_sha, issuance, expected = self.evidence()
        for name, args in (
                ("scope", (grant, grant_sha, issuance, {**expected, "scope": ["x.py"]})),
                ("grant", ({**grant, "delegation_sha256": "0" * 64}, grant_sha, issuance, expected)),
                ("issuance", (grant, grant_sha, {**issuance, "policy_sha256": "0" * 64}, expected)),
                ("project", (grant, grant_sha, issuance, {**expected, "project": "other"}))):
            with self.subTest(name=name):
                self.assertFalse(qa_worker.delegated_decision(self.grants, reference, *args))


class OwnerReplyUnchangedTest(DelegationFixture):
    def test_owner_reply_grant_is_unchanged_when_no_policy(self):
        reference = self.f.grant()
        grant = ProtectedDevelopmentAuthority(self.grants, environment="staging").verify(
            reference, self.f.expected())
        self.assertEqual(grant["source"], "photon_native_owner_reply")
        self.assertEqual(grant["owner_event_id"], "photon-owner-reply")
