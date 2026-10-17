"""Disposable evidence, Git, GitHub, authorization, and retry tests."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import jsonschema

from draft_pr_publisher import worker

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "live-acceptance/repo"
QA = ROOT / "independent_reviewer/live-evidence/qa-report.json"
QA_HANDOFF = ROOT / "independent_reviewer/live-evidence/reviewer-handoff.json"
PLAN = Path("/home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0002.json")
GRANT = Path("/var/lib/alfred-development-grants/grant-445759a699d9423bbb5a8f1dd589689a.json")
SPEC = SOURCE / ".dev/tasks/T-0002-backend-calculator-subtract-helper.md"


def command(*args: str) -> str:
    return subprocess.check_output(["/usr/bin/git", *map(str, args)], stderr=subprocess.DEVNULL).decode().strip()


def save(path: Path, obj: dict) -> None:
    path.write_bytes(worker.canonical(obj))


class FakeGitHub:
    def __init__(self, bare: Path, destination: str = "testowner/fixture"):
        self.bare = bare
        self.destination = destination
        self.pr_list = []
        self.create_count = 0
        self.fail_create = False
        self.writes = []

    def repository(self, destination):
        return {"full_name": self.destination, "default_branch": "main"}

    def ref(self, destination, branch):
        try:
            revision = command("-C", self.bare, "rev-parse", f"refs/heads/{branch}")
        except subprocess.CalledProcessError:
            return None
        return {"object": {"sha": revision}}

    def prs(self, destination, owner, branch, base):
        return self.pr_list

    def create_draft(self, destination, payload):
        self.create_count += 1
        self.writes.append(payload)
        if self.fail_create:
            raise worker.PublicationError("github", "fixture API timeout")
        revision = self.ref(destination, payload["head"])["object"]["sha"]
        record = {"number": 1, "draft": payload["draft"], "state": "open",
                  "html_url": f"https://github.com/{destination}/pull/1", "body": payload["body"],
                  "head": {"sha": revision, "ref": payload["head"],
                           "repo": {"full_name": destination}},
                  "base": {"ref": payload["base"],
                           "sha": self.ref(destination, payload["base"])["object"]["sha"],
                           "repo": {"full_name": destination}}}
        self.pr_list = [record]
        return record


class PublisherFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="publisher-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.git"
        command("clone", "-q", "--no-local", "--bare", SOURCE, self.source)
        self.bare = self.root / "github.git"
        command("init", "--bare", "-q", self.bare)
        self.qa = json.loads(QA.read_text())
        self.qa_handoff = json.loads(QA_HANDOFF.read_text())
        self.paths = {}
        for key, origin in (("qa_path", QA), ("qa_handoff_path", QA_HANDOFF),
                            ("plan_path", PLAN), ("grant_path", GRANT), ("spec_path", SPEC)):
            target = self.root / origin.name
            shutil.copyfile(origin, target)
            self.paths[key] = target
        baseline = self.qa["baseline_revision"]
        command("-C", self.source, "push", "-q", self.bare, f"{baseline}:refs/heads/main")
        diff = worker.git(self.source, "diff", "--no-ext-diff", "--no-textconv", "--binary",
                          baseline, self.qa["final_revision"], "--", binary=True)
        self.review = {
            "schema": "alfred.review-report/1", "project": self.qa["project"],
            "task_id": self.qa["task_id"], "developer_commits": self.qa["developer_commits"],
            "baseline_revision": baseline, "final_revision": self.qa["final_revision"],
            "qa_report_sha256": worker.sha(QA.read_bytes()),
            "reviewer_handoff_sha256": worker.sha(QA_HANDOFF.read_bytes()),
            "files_inspected": ["calculator.py"],
            "changed_file_hashes": self.qa["changed_file_hashes"],
            "diff_sha256": worker.sha(diff), "findings": [], "correctness": "PASS",
            "scope": "PASS", "acceptance_coverage": self.qa["acceptance_criteria"],
            "model_used": {"provider": "fixture", "model": "fixture-reviewer"},
            "model_fallback": None, "decision": "APPROVED", "input_fingerprint": "fixture",
            "evidence": {}, "next_authorized_stage": "github_draft_pr_preparation"}
        self.review_path = self.root / "review-report.json"
        save(self.review_path, self.review)
        self.handoff = {
            "schema": "alfred.publication-handoff/1", "project": self.qa["project"],
            "task_id": self.qa["task_id"], "developer_commits": self.qa["developer_commits"],
            "final_revision": self.qa["final_revision"],
            "changed_file_hashes": self.qa["changed_file_hashes"],
            "qa_report_sha256": worker.sha(QA.read_bytes()),
            "review_report_sha256": worker.sha(self.review_path.read_bytes()),
            "decision": "APPROVED", "next_stage": "github_draft_pr_preparation"}
        self.handoff_path = self.root / "publication-handoff.json"
        save(self.handoff_path, self.handoff)
        self.config = {"schema": "alfred.draft-pr-config/1", "project": self.qa["project"],
                       "task_id": self.qa["task_id"], "final_revision": self.qa["final_revision"],
                       "review_report_sha256": worker.sha(self.review_path.read_bytes()),
                       "publication_handoff_sha256": worker.sha(self.handoff_path.read_bytes()),
                       "qa_report_sha256": worker.sha(QA.read_bytes())}
        self.config_path = self.root / "config.json"
        save(self.config_path, self.config)
        self.registry_path = self.root / "projects.yaml"
        self.registry_path.write_text("version: 1\nprojects:\n  - id: dev-v1-accept\n    status: active\n"
                                      "    repo:\n      github: testowner/fixture\n      default_branch: main\n"
                                      "    local_path: /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo\n")
        self.paths.update(config_path=self.config_path, registry_path=self.registry_path,
                          handoff_path=self.handoff_path, review_path=self.review_path,
                          source_repo=self.source)
        self.output = self.root / "output"
        self.trust = self.root / "trusted"
        self.trust.mkdir(mode=0o700)
        self.token = self.root / "token"
        self.token.write_text("fixture-token\n")
        self.token.chmod(0o600)
        self.github = FakeGitHub(self.bare)
        self.push_count = 0

    def pin(self):
        self.config["review_report_sha256"] = worker.sha(self.review_path.read_bytes())
        self.handoff["review_report_sha256"] = self.config["review_report_sha256"]
        save(self.handoff_path, self.handoff)
        self.config["publication_handoff_sha256"] = worker.sha(self.handoff_path.read_bytes())
        save(self.config_path, self.config)

    def authorize(self, plan, digest):
        approval = {"schema": "alfred.github-draft-pr-authorization/1",
                    "decision": "approved", "project": plan["project"], "task_id": plan["task_id"],
                    "destination": plan["destination"], "base_branch": plan["base_branch"],
                    "publication_branch": plan["publication_branch"],
                    "final_revision": plan["final_revision"], "publication_plan_sha256": digest,
                    "owner_event_id": "fixture-owner-event", "purpose": "one_github_draft_pr"}
        path = self.trust / "authorization.json"
        save(path, approval)
        path.chmod(0o600)
        return path

    def pusher(self, source, plan, token):
        self.push_count += 1
        command("-C", source, "push", "-q", self.bare,
                f"{plan['final_revision']}:refs/heads/{plan['publication_branch']}")

    def stage(self):
        return worker.prepare(output_root=self.output, **self.paths)

    def publish(self, approval):
        return worker.publish(output_root=self.output, authorization_path=approval,
                              token_file=self.token, github=self.github, pusher=self.pusher,
                              trusted_uid=os.getuid(), trusted_root=self.trust, **self.paths)

    def rejected(self):
        with self.assertRaises(worker.PublicationError):
            self.stage()


class EvidenceTests(PublisherFixture):
    def test_canonical_registry_has_explicit_t0002_destination(self):
        destination, base, local = worker.registry_destination(
            Path("/home/alfred/Git/alfred/registry/projects.yaml"), "dev-v1-accept")
        self.assertEqual((destination, base), ("hrsnyde1/alfred-dev-v1-acceptance", "main"))
        self.assertEqual(local, str(SOURCE))

    def test_valid_t0002_evidence_and_registered_destination(self):
        plan, digest = self.stage()
        self.assertEqual(plan["destination"], "testowner/fixture")
        self.assertEqual(plan["final_revision"], "89ba188f8a2f801d433a30c9c21363efb3e1043d")
        self.assertEqual(plan["changed_file_hashes"], {"calculator.py":
            "8b7592a111b9a05664ec660fb67d926fa3810ff816dd5fb50ea37eae72284c5b"})
        self.assertEqual(digest, worker.sha((self.output / "dev-v1-accept/T-0002/publication-plan.json").read_bytes()))

    def test_unregistered_destination_denied(self):
        self.registry_path.write_text("version: 1\nprojects: []\n")
        self.rejected()

    def test_handoff_or_report_digest_mismatch_denied(self):
        self.handoff["decision"] = "BLOCKED"
        save(self.handoff_path, self.handoff)
        self.rejected()
        self.handoff["decision"] = "APPROVED"
        save(self.handoff_path, self.handoff)
        self.review["decision"] = "BLOCKED"
        save(self.review_path, self.review)
        self.rejected()

    def test_nonapproved_review_denied_with_recomputed_digests(self):
        self.review["decision"] = "BLOCKED"
        save(self.review_path, self.review)
        self.pin()
        self.rejected()

    def test_nonapproved_handoff_denied_with_recomputed_digest(self):
        self.handoff["decision"] = "CHANGES_REQUESTED"
        save(self.handoff_path, self.handoff)
        self.config["publication_handoff_sha256"] = worker.sha(self.handoff_path.read_bytes())
        save(self.config_path, self.config)
        self.rejected()

    def test_output_schemas_validate(self):
        plan, digest = self.stage()
        plan_schema = json.loads((ROOT / "draft_pr_publisher/schemas/publication-plan.schema.json").read_text())
        jsonschema.validate(plan, plan_schema)
        approval = self.authorize(plan, digest)
        auth_schema = json.loads((ROOT / "draft_pr_publisher/schemas/owner-authorization.schema.json").read_text())
        jsonschema.validate(json.loads(approval.read_text()), auth_schema)
        result = self.publish(approval)
        result_schema = json.loads((ROOT / "draft_pr_publisher/schemas/publication-result.schema.json").read_text())
        jsonschema.validate(result, result_schema)

    def test_qa_failure_denied_even_if_review_approved(self):
        qa = copy.deepcopy(self.qa)
        qa["decision"] = "FAIL"
        save(self.paths["qa_path"], qa)
        self.rejected()

    def test_wrong_revision_denied_even_with_recomputed_pins(self):
        wrong = "0" * 40
        self.review["final_revision"] = wrong
        self.handoff["final_revision"] = wrong
        save(self.review_path, self.review)
        self.pin()
        self.rejected()

    def test_unauthorized_scope_denied(self):
        bad = copy.deepcopy(self.qa["changed_file_hashes"])
        bad["test_calculator.py"] = hashlib.sha256(b"bad").hexdigest()
        self.review["changed_file_hashes"] = bad
        self.handoff["changed_file_hashes"] = bad
        save(self.review_path, self.review)
        self.pin()
        self.rejected()

    def test_changed_file_hash_denied(self):
        bad = {"calculator.py": "0" * 64}
        self.review["changed_file_hashes"] = bad
        self.handoff["changed_file_hashes"] = bad
        save(self.review_path, self.review)
        self.pin()
        self.rejected()

    def test_missing_acceptance_denied(self):
        self.review["acceptance_coverage"] = self.review["acceptance_coverage"][:-1]
        save(self.review_path, self.review)
        self.pin()
        self.rejected()

    def test_tampered_plan_denied(self):
        plan = json.loads(self.paths["plan_path"].read_text())
        plan["scope"] = "Change everything"
        save(self.paths["plan_path"], plan)
        self.rejected()

    def test_prepare_is_idempotent_and_read_only(self):
        before = command("-C", self.source, "rev-parse", "refs/heads/main")
        first = self.stage()
        second = self.stage()
        self.assertEqual(first, second)
        self.assertEqual(before, command("-C", self.source, "rev-parse", "refs/heads/main"))
        self.assertEqual(self.github.create_count, 0)


class PublicationTests(PublisherFixture):
    def test_owner_authorization_required_before_any_write(self):
        self.stage()
        with self.assertRaises(worker.PublicationError):
            self.publish(self.trust / "missing.json")
        self.assertEqual(self.push_count, 0)
        self.assertEqual(self.github.create_count, 0)

    def test_authorization_must_bind_exact_plan(self):
        plan, digest = self.stage()
        approval = self.authorize(plan, "0" * 64)
        with self.assertRaises(worker.PublicationError):
            self.publish(approval)
        self.assertEqual(self.push_count, 0)

    def test_unprotected_authorization_denied(self):
        plan, digest = self.stage()
        approval = self.authorize(plan, digest)
        approval.chmod(0o666)
        with self.assertRaises(worker.PublicationError):
            self.publish(approval)
        self.assertEqual(self.push_count, 0)

    def test_publish_only_draft_and_retry_reuses_result(self):
        plan, digest = self.stage()
        approval = self.authorize(plan, digest)
        first = self.publish(approval)
        self.assertEqual(first["status"], "PUBLISHED_DRAFT")
        self.assertEqual(first["draft_pr_url"], "https://github.com/testowner/fixture/pull/1")
        self.assertEqual(self.push_count, 1)
        self.assertEqual(self.github.create_count, 1)
        self.assertTrue(self.github.writes[0]["draft"])
        self.assertEqual(command("-C", self.bare, "rev-parse", "refs/heads/" + plan["publication_branch"]),
                         plan["final_revision"])
        self.assertEqual(self.publish(approval), first)
        self.assertEqual(self.push_count, 1)
        self.assertEqual(self.github.create_count, 1)

    def test_real_isolated_push_routine_to_disposable_remote(self):
        plan, digest = self.stage()
        before = command("-C", self.source, "rev-parse", "refs/heads/main")
        worker.push_branch(self.source, plan, self.token, _fixture_remote=str(self.bare))
        self.assertEqual(command("-C", self.bare, "rev-parse", "refs/heads/" + plan["publication_branch"]),
                         plan["final_revision"])
        self.assertEqual(command("-C", self.bare, "diff", "--name-only",
                                 plan["baseline_revision"], plan["final_revision"]), "calculator.py")
        self.assertEqual(command("-C", self.source, "rev-parse", "refs/heads/main"), before)
        self.assertEqual(self.github.create_count, 0)

    def test_root_owned_source_fetch_trust_is_exact_and_ephemeral(self):
        plan, _ = self.stage()
        source_before = {str(p.relative_to(self.source)): (hashlib.sha256(p.read_bytes()).hexdigest(),
                                                         p.stat().st_mode)
                         for p in self.source.rglob("*") if p.is_file()}
        run = subprocess.run
        with tempfile.TemporaryDirectory(prefix="publisher-old-fetch-") as name:
            command("init", "--bare", "-q", name)
            env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                   "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}
            # Simulate different ownership only for the source: the parent
            # repository is explicitly trusted on its own command line.
            old = run(["/usr/bin/git", "-c", f"safe.directory={name}", "-C", name,
                       "fetch", "--no-tags", str(self.source), plan["baseline_revision"],
                       plan["final_revision"]], env=env, capture_output=True, timeout=20)
            self.assertEqual(old.returncode, 128)
            self.assertIn(b"dubious ownership", old.stderr)

        configs = []
        steps = []

        def different_source_owner(args, **kwargs):
            steps.append(args)
            if "fetch" in args:
                env = {**kwargs["env"], "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}
                config = Path(env["GIT_CONFIG_GLOBAL"])
                configs.append(config)
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                trusted = run(["/usr/bin/git", "config", "--global", "--get-all", "safe.directory"],
                              env=env, capture_output=True, check=True).stdout.decode().splitlines()
                self.assertEqual(trusted, [str(self.source.resolve())])
                unrelated = run(["/usr/bin/git", "-C", str(self.bare), "rev-parse", "--git-dir"],
                                env=env, capture_output=True)
                self.assertEqual(unrelated.returncode, 128)
                self.assertIn(b"dubious ownership", unrelated.stderr)
                parent = args[args.index("-C") + 1]
                args = [args[0], "-c", f"safe.directory={parent}", *args[1:]]
                kwargs["env"] = env
            else:
                self.assertEqual(kwargs["env"]["GIT_CONFIG_GLOBAL"], os.devnull)
            return run(args, **kwargs)

        with patch.object(worker.subprocess, "run", side_effect=different_source_owner):
            worker.push_branch(self.source, plan, self.token, _fixture_remote=str(self.bare))
        self.assertEqual(len(steps), 3)
        self.assertEqual(len(configs), 1)
        self.assertFalse(configs[0].exists())
        self.assertEqual({str(p.relative_to(self.source)): (hashlib.sha256(p.read_bytes()).hexdigest(),
                                                          p.stat().st_mode)
                          for p in self.source.rglob("*") if p.is_file()}, source_before)
        self.assertEqual(command("-C", self.bare, "rev-parse",
                                 "refs/heads/" + plan["publication_branch"]), plan["final_revision"])

    def test_api_failure_stops_and_retry_finds_existing_branch(self):
        plan, digest = self.stage()
        approval = self.authorize(plan, digest)
        self.github.fail_create = True
        first = self.publish(approval)
        self.assertEqual(first["status"], "ERROR")
        self.assertEqual(self.push_count, 1)
        self.assertEqual(self.github.create_count, 1)
        self.github.fail_create = False
        second = self.publish(approval)
        self.assertEqual(second["status"], "PUBLISHED_DRAFT")
        self.assertEqual(self.push_count, 1)
        self.assertEqual(self.github.create_count, 2)

    def test_existing_draft_is_reused_after_uncertain_response(self):
        plan, digest = self.stage()
        approval = self.authorize(plan, digest)
        self.pusher(self.source, plan, self.token)
        payload = {"head": plan["publication_branch"], "base": plan["base_branch"],
                   "draft": True, "body": plan["qa_report_sha256"] + " " + plan["review_report_sha256"] + " " + digest}
        self.github.create_draft(plan["destination"], payload)
        before = self.github.create_count
        result = self.publish(approval)
        self.assertEqual(result["status"], "PUBLISHED_DRAFT")
        self.assertEqual(self.github.create_count, before)
        self.assertEqual(self.push_count, 1)

    def test_non_draft_existing_pr_is_rejected(self):
        plan, digest = self.stage()
        approval = self.authorize(plan, digest)
        self.pusher(self.source, plan, self.token)
        self.github.create_draft(plan["destination"],
            {"head": plan["publication_branch"], "base": plan["base_branch"], "draft": True,
             "body": plan["qa_report_sha256"] + " " + plan["review_report_sha256"] + " " + digest})
        self.github.pr_list[0]["draft"] = False
        result = self.publish(approval)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(self.github.create_count, 1)
        self.assertEqual(self.push_count, 1)

    def test_remote_baseline_mismatch_prevents_writes(self):
        plan, digest = self.stage()
        approval = self.authorize(plan, digest)
        command("-C", self.source, "push", "-q", "--force", self.bare,
                f"{plan['final_revision']}:refs/heads/main")
        result = self.publish(approval)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(self.push_count, 0)
        self.assertEqual(self.github.create_count, 0)

    def test_pr_response_with_moved_base_is_not_accepted(self):
        plan, digest = self.stage()
        approval = self.authorize(plan, digest)
        create = self.github.create_draft

        def moved_base(destination, payload):
            record = create(destination, payload)
            record["base"]["sha"] = "0" * 40
            return record

        self.github.create_draft = moved_base
        result = self.publish(approval)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(self.push_count, 1)
        self.assertEqual(self.github.create_count, 1)


if __name__ == "__main__":
    unittest.main()
