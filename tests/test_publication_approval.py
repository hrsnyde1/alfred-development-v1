"""Staging-only publication approval and negative authorization tests."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from draft_pr_publisher.worker import verify_authorization
from developer_v1 import publication_approval as pub
from developer_v1 import stage_publication
from developer_v1.router import Denied
from developer_v1.trusted_intake_development import IntakeGate, IntakeRefused


class PublicationApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="publication-approval-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.now = 1700000000.0
        self.sent = []
        self.issuer = pub.PublicationApprovalIssuer(
            self.root, owner_sender_id="owner-id", sidecar_uid=1201, admin_uid=0,
            clock=lambda: self.now, preview_sender=self.send)
        self.plan = {"schema": "alfred.draft-pr-plan/1", "status": "READY_FOR_OWNER_AUTHORIZATION",
                     **pub.BOUND, "qa_report_sha256": "a" * 64}
        self.raw = (json.dumps(self.plan, indent=2, sort_keys=True) + "\n").encode()
        self.pin = patch.object(pub, "PLAN_SHA", hashlib.sha256(self.raw).hexdigest())
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def send(self, space, text):
        self.sent.append((space, text))
        return "outbound-challenge-id"

    def test_sidecar_send_failure_refuses_without_publication_evidence(self):
        def failed_send(_space, _text):
            raise OSError("fixture sidecar send failure")

        issuer = pub.PublicationApprovalIssuer(
            self.root, owner_sender_id="owner-id", sidecar_uid=1201,
            clock=lambda: self.now, preview_sender=failed_send)
        gate = IntakeGate.__new__(IntakeGate)
        gate.publication_issuer = issuer
        with self.assertRaises(IntakeRefused) as refusal:
            gate.dispatch({"op": "stage_publication_approval",
                           "plan_raw": self.raw.decode(), "space_id": "owner-dm"}, 0)
        self.assertEqual(refusal.exception.code, "publication_request_unavailable")
        self.assertFalse(list(self.root.glob("publication-*.json")))

    def stage(self):
        return self.issuer.stage(self.raw, space_id="owner-dm", peer_uid=0)

    def event(self, challenge, **changes):
        reference = challenge["challenge"]
        event = {"direction": "inbound", "sender": {"id": "owner-id"},
                 "space": {"id": "owner-dm", "type": "dm"},
                 "messageId": "fresh-owner-event", "nativeReplyTargetGuid": challenge["message_id"],
                 "nativeIsForward": False, "content": {"type": "text", "text": pub._phrase(reference)},
                 "timestamp": dt.datetime.fromtimestamp(self.now, dt.timezone.utc).isoformat()}
        event.update(changes)
        return event

    def test_exact_plan_challenge_and_prepared_record(self):
        challenge = self.stage()
        self.assertIn(pub.PLAN_SHA, self.sent[0][1])
        self.assertIn(pub.BOUND["destination"], self.sent[0][1])
        with self.assertRaises((Denied, FileNotFoundError)):
            self.issuer.prepare(challenge["challenge"], peer_uid=0)
        result = self.issuer.observe(self.event(challenge), peer_uid=1201)
        self.assertEqual(result["state"], "publication_approved")
        record = self.issuer.prepare(challenge["challenge"], peer_uid=0)
        self.assertEqual(record["owner_event_id"], "fresh-owner-event")
        self.assertEqual(record["publication_plan_sha256"], pub.PLAN_SHA)
        self.assertEqual(record["purpose"], "one_github_draft_pr")
        staged = self.root / "fixture-authorization.json"
        staged.write_text(json.dumps(record))
        staged.chmod(0o600)
        self.assertEqual(verify_authorization(staged, self.plan, pub.PLAN_SHA,
                         trusted_uid=staged.stat().st_uid, trusted_root=self.root), record)
        self.assertFalse(any(self.root.glob("grant-*.json")))
        self.assertFalse(any(self.root.glob("T-0002.json")))
        decision = json.loads((self.root / f"publication-decision-{challenge['challenge']}.json").read_text())
        self.assertEqual(decision["native_reply_target"], challenge["message_id"])
        self.assertEqual(decision["owner_event_id"], record["owner_event_id"])
        self.assertEqual((self.root / f"publication-decision-{challenge['challenge']}.json").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(Denied):
            self.issuer.observe(self.event(challenge), peer_uid=1201)

    def test_negative_authorization(self):
        cases = [
            {"sender": {"id": "other"}}, {"sender": {}},
            {"space": {"id": "other-dm", "type": "dm"}},
            {"space": {"id": "owner-dm", "type": "group"}},
            {"direction": "outbound"}, {"nativeIsForward": True},
            {"nativeIsForward": None}, {"messageId": "outbound-challenge-id"},
            {"messageId": ""}, {"content": {"type": "text", "text": "Approve development"}},
            {"content": {"type": "attachment", "text": "yes"}},
            {"timestamp": "2020-01-01T00:00:00+00:00"},
            {"timestamp": "invalid"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                with tempfile.TemporaryDirectory(prefix="publication-negative-") as tmp:
                    root = Path(tmp)
                    root.chmod(0o700)
                    issuer = pub.PublicationApprovalIssuer(root, owner_sender_id="owner-id",
                        sidecar_uid=1201, admin_uid=0, clock=lambda: self.now,
                        preview_sender=self.send)
                    challenge = issuer.stage(self.raw, space_id="owner-dm", peer_uid=0)
                    with self.assertRaises(Denied):
                        issuer.observe(self.event(challenge, **changes), peer_uid=1201)
                    with self.assertRaises((Denied, FileNotFoundError)):
                        issuer.prepare(challenge["challenge"], peer_uid=0)
                    self.assertFalse(any(root.glob("publication-decision-*.json")))

    def test_unthreaded_wrong_target_expired_and_replayed_event(self):
        challenge = self.stage()
        self.assertEqual(self.issuer.observe(self.event(challenge, nativeReplyTargetGuid=None),
                          peer_uid=1201)["state"], "not_publication_approval")
        self.assertEqual(self.issuer.observe(self.event(challenge, nativeReplyTargetGuid="elsewhere"),
                          peer_uid=1201)["state"], "not_publication_approval")
        with self.assertRaises(Denied):
            self.issuer.observe(self.event(challenge), peer_uid=1202)
        self.now += pub.MAX_AGE + 1
        with self.assertRaises(Denied):
            self.issuer.observe(self.event(challenge), peer_uid=1201)
        with self.assertRaises((Denied, FileNotFoundError)):
            self.issuer.prepare(challenge["challenge"], peer_uid=0)

    def test_mismatched_plan_and_untrusted_staging(self):
        with self.assertRaises(Denied):
            self.issuer.stage(self.raw, space_id="owner-dm", peer_uid=1201)
        with self.assertRaises(Denied):
            self.issuer.stage(self.raw.replace(b"hrsnyde1", b"attacker"),
                              space_id="owner-dm", peer_uid=0)
        self.assertFalse(self.sent)
        self.stage()
        with self.assertRaises(Denied):
            self.stage()

    def test_reused_development_event_and_tampered_evidence(self):
        challenge = self.stage()
        development = self.root / ("decision-" + "a" * 32 + ".json")
        development.write_text(json.dumps({"owner_event_id": "fresh-owner-event"}))
        development.chmod(0o600)
        with self.assertRaises(Denied):
            self.issuer.observe(self.event(challenge), peer_uid=1201)
        development.unlink()
        self.issuer.observe(self.event(challenge), peer_uid=1201)
        decision_path = self.root / f"publication-decision-{challenge['challenge']}.json"
        decision = json.loads(decision_path.read_text())
        decision["owner_event_id"] = "fabricated"
        decision_path.write_text(json.dumps(decision))
        with self.assertRaises(Denied):
            self.issuer.prepare(challenge["challenge"], peer_uid=0)

    def test_intake_dispatch_routes_publication_without_development_grant(self):
        gate = IntakeGate.__new__(IntakeGate)
        gate.sidecar_uid = 1201
        gate.publication_issuer = self.issuer
        gate.development_issuer = None
        challenge = gate.dispatch({"op": "stage_publication_approval",
            "plan_raw": self.raw.decode(), "space_id": "owner-dm"}, 0)
        with self.assertRaises(IntakeRefused):
            gate.dispatch({"op": "prepare_publication_authorization",
                           "reference": challenge["challenge"]}, 1201)
        result = gate.dispatch({"op": "observe", "event": self.event(challenge)}, 1201)
        self.assertEqual(result["state"], "publication_approved")
        prepared = gate.dispatch({"op": "prepare_publication_authorization",
                                 "reference": challenge["challenge"]}, 0)
        self.assertEqual(prepared["authorization"]["owner_event_id"], "fresh-owner-event")

    def test_root_client_installs_only_prepared_schema_once(self):
        target = self.root / "T-0002.json"
        original_lstat = Path.lstat
        def protected_parent(path):
            if path == self.root:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o750,
                                       st_uid=0, st_gid=1234)
            return original_lstat(path)
        record = {"schema": "alfred.github-draft-pr-authorization/1",
                  "decision": "approved", **pub.BOUND,
                  "publication_plan_sha256": pub.PLAN_SHA,
                  "owner_event_id": "fresh-owner-event", "purpose": "one_github_draft_pr"}
        with (patch.object(stage_publication, "AUTH_PATH", target),
              patch.object(stage_publication, "PLAN_SHA", pub.PLAN_SHA),
              patch.object(stage_publication.grp, "getgrnam",
                           return_value=SimpleNamespace(gr_gid=1234)),
              patch.object(Path, "lstat", protected_parent),
              patch.object(stage_publication.os, "fchown")):
            for forged in ({**record, "owner_event_id": ""},
                           {**record, "publication_plan_sha256": "0" * 64}):
                with self.assertRaises(ValueError):
                    stage_publication._install_authorization(forged)
                self.assertFalse(target.exists())
            stage_publication._install_authorization(record)
            self.assertEqual(json.loads(target.read_text()), record)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
            with self.assertRaises(FileExistsError):
                stage_publication._install_authorization(record)


if __name__ == "__main__":
    unittest.main()
