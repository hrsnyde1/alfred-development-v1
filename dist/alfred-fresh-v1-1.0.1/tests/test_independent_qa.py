"""Staged Independent QA acceptance tests; all writable Git trees are disposable."""

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from independent_qa.worker import run


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


REF = "f" * 32


class Fixture:
    def __init__(self, root: Path, *, faulty=False, extra=False):
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "qa-fixture@example.invalid")
        git(self.repo, "config", "user.name", "QA Fixture")
        (self.repo / ".dev/tasks").mkdir(parents=True)
        spec = ("---\nid: T-0002\nproject: fixture-qa\n---\n\n## Objective\n"
                "Add subtract.\n\n## Acceptance criteria\n- [ ] add(7, 3) returns 10.\n"
                "- [ ] subtract(7, 3) returns 4.\n"
                "- [ ] The existing unittest discovery command passes.\n")
        (self.repo / ".dev/tasks/T-0002-fixture.md").write_text(spec)
        (self.repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
        (self.repo / "test_calculator.py").write_text(
            "import unittest\nimport calculator\nclass Tests(unittest.TestCase):\n"
            "    def test_add(self): self.assertEqual(calculator.add(7, 3), 10)\n"
            "    def test_subtract(self): self.assertEqual(calculator.subtract(7, 3), 4)\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "baseline")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.dev = root / "developer"
        self.final = root / "final"
        git(self.repo, "worktree", "add", "-b", "developer/fixture", str(self.dev), self.base)
        change = "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return " + ("a + b" if faulty else "a - b") + "\n"
        (self.dev / "calculator.py").write_text(change)
        git(self.dev, "add", "calculator.py")
        git(self.dev, "commit", "-m", "subtract")
        self.commit = git(self.dev, "rev-parse", "HEAD")
        git(self.repo, "worktree", "add", "-b", "final/fixture", str(self.final), self.base)
        (self.final / "calculator.py").write_text(change)
        git(self.final, "add", "calculator.py")
        git(self.final, "commit", "-m", "subtract")
        if extra:
            (self.final / "unapproved.txt").write_text("unauthorized\n")
            git(self.final, "add", "unapproved.txt")
            git(self.final, "commit", "-m", "extra")
        self.revision = git(self.final, "rev-parse", "HEAD")
        file_sha = sha(change.encode())
        self.report = {
            "schema": "alfred.developer-report/1", "project": "fixture-qa", "task_id": "T-0002",
            "assignment_id": "backend-subtract", "specialist": "backend", "assigned_scope": ["calculator.py"],
            "repository": str(self.repo), "worktree": str(self.dev), "branch": "developer/fixture",
            "baseline_revision": self.base, "files_modified": [{"path": "calculator.py", "sha256": file_sha}],
            "work_completed": "self-reported", "tests": [{"name": "claimed test", "outcome": "passed", "evidence": "exit=0"}],
            "commits": [self.commit], "known_limitations": [], "blockers": [], "status": "completed",
            "model_used": {"provider": "codex", "model": "gpt-6-sol", "reasoning_effort": "high", "fallback_used": False},
            "qa_handoff": {"ready": True, "baseline_revision": self.base,
                           "changed_file_hashes": {"calculator.py": file_sha}}
        }
        self.input_dir = root / "developer-state/fixture-qa/T-0002"
        self.input_dir.mkdir(parents=True)
        (root / "developer-state/request-fixture-qa-T-0002.json").write_text(json.dumps({
            "schema": "alfred.developer-run-request/1", "project": "fixture-qa", "task_id": "T-0002",
            "authorization_reference": REF, "scope": ["calculator.py"],
            "worktree_root": str(root)}))
        self.manifest = {
            "schema": "alfred.qa-input/1", "project": "fixture-qa", "task_id": "T-0002",
            "repository": str(self.repo), "developer_reports": [self.report],
            "final_worktree": str(self.final), "final_revision": self.revision,
            "changed_file_hashes": {"calculator.py": file_sha}, "state": "ready_for_independent_qa"
        }
        self.gateway = root / "gateway"
        (self.gateway / "cto-plans").mkdir(parents=True)
        plan = {"schema": "alfred.cto-plan/1", "project": "fixture-qa", "task_id": "T-0002",
                "repository": str(self.repo), "spec_sha256": sha(spec.encode()), "clarification_required": False,
                "scope": "Change only calculator.py", "objective": "Add subtract",
                "acceptance_criteria": "- [ ] add(7, 3) returns 10.\n- [ ] subtract(7, 3) returns 4.\n- [ ] The existing unittest discovery command passes."}
        plan_bytes = json.dumps(plan).encode()
        (self.gateway / "cto-plans/fixture-qa-T-0002.json").write_bytes(plan_bytes)
        self.registry = root / "projects.yaml"
        self.registry.write_text(f"projects:\n  - id: fixture-qa\n    local_path: {self.repo}\n")
        self.grants = root / "grants"
        self.grants.mkdir()
        grant = {"schema": "alfred.development-grant/1", "project": "fixture-qa", "task_id": "T-0002",
                 "reference": REF, "state": "approved", "issuer": "trusted_owner_authority",
                 "repository": str(self.repo), "spec_sha256": sha(spec.encode()), "plan_sha256": sha(plan_bytes),
                 "scope": ["calculator.py"], "specialists": ["backend"],
                 "worktree_root": str(root), "owner_event_id": "owner-fixture"}
        grant_bytes = json.dumps(grant).encode()
        (self.grants / f"grant-{REF}.json").write_bytes(grant_bytes)
        challenge = {"schema": "alfred.development-challenge/1", "reference": REF,
                     "request": {"schema": "alfred.development-approval-request/1", "project": "fixture-qa",
                                 "task_id": "T-0002", "repository": str(self.repo), "spec_sha256": sha(spec.encode()),
                                 "plan_sha256": sha(plan_bytes), "scope": ["calculator.py"],
                                 "specialists": ["backend"], "worktree_root": str(root),
                                 "state": "pending_owner_decision"},
                     "owner_id": "fixture-owner", "space_id": "fixture-space", "message_id": "challenge-fixture",
                     "phrase_sha256": sha(b"fixture phrase")}
        challenge_bytes = json.dumps(challenge).encode()
        (self.grants / f"challenge-{REF}.json").write_bytes(challenge_bytes)
        decision = {"schema": "alfred.development-owner-decision/1", "reference": REF,
                    "challenge_sha256": sha(challenge_bytes), "sender_id": "fixture-owner",
                    "space_id": "fixture-space", "native_reply_target": "challenge-fixture",
                    "content_sha256": sha(b"fixture phrase"), "owner_event_id": "owner-fixture",
                    "direction": "inbound", "is_forward": False, "content_type": "text",
                    "checks": {k: True for k in ("authenticated_sender", "same_dm", "fresh_event",
                                               "native_direct_reply", "not_forwarded", "within_challenge_lifetime",
                                               "exact_phrase", "single_use")}}
        decision_bytes = json.dumps(decision).encode()
        (self.grants / f"decision-{REF}.json").write_bytes(decision_bytes)
        (self.grants / f"issuance-{REF}.json").write_text(json.dumps({"grant_sha256": sha(grant_bytes),
            "challenge_sha256": sha(challenge_bytes), "decision_sha256": sha(decision_bytes)}))
        claim_bytes = json.dumps({"grant_sha256": sha(grant_bytes), "reference": REF}).encode()
        (self.grants / f"execution-{REF}.json").write_bytes(claim_bytes)
        (self.grants / f"execution-result-{REF}.json").write_text(json.dumps({"status": "completed",
            "reference": REF, "claim_sha256": sha(claim_bytes)}))
        self.config = root / "config.json"
        self.config.write_text(json.dumps({"schema": "alfred.qa-config/1", "model": {"enabled": False},
            "projects": {"fixture-qa": {"checks": ["calculator_examples", "python_unittest"],
              "criteria": [{"contains": "add(7, 3)", "check": "calculator_examples"},
                           {"contains": "subtract(7, 3)", "check": "calculator_examples"},
                           {"contains": "unittest", "check": "python_unittest"}]}}}))
        self.save()

    def save(self):
        (self.input_dir / "qa-input.json").write_text(json.dumps(self.manifest))
        (self.input_dir / "report-backend-subtract.json").write_text(json.dumps(self.report))

    def run(self, *, bwrap="/usr/bin/bwrap", output=None):
        return run(self.input_dir / "qa-input.json", output or self.root / "qa-output",
                   self.registry, self.gateway, self.grants, self.config, bwrap=bwrap)


class IndependentQATests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qa-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.fx = Fixture(Path(self.temp.name))

    def test_01_valid_handoff_and_independent_execution(self):
        result = self.fx.run()
        self.assertEqual(result["decision"], "PASS")
        self.assertEqual([t["exit_code"] for t in result["tests"]], [0, 0])
        self.assertTrue((self.fx.root / "qa-output/fixture-qa/T-0002/reviewer-handoff.json").is_file())

    def test_02_incorrect_final_revision_rejected(self):
        self.fx.manifest["final_revision"] = "0" * 40
        self.fx.save()
        result = self.fx.run()
        self.assertEqual(result["decision"], "FAIL")
        self.assertEqual(result["findings"][0]["requirement"], "final_revision")

    def test_03_hash_mismatch_rejected(self):
        self.fx.manifest["changed_file_hashes"]["calculator.py"] = "0" * 64
        self.fx.save()
        result = self.fx.run()
        self.assertEqual(result["decision"], "FAIL")
        self.assertEqual(result["findings"][0]["requirement"], "changed_file_hashes")

    def test_04_unauthorized_git_change_rejected(self):
        (self.fx.final / "unapproved.txt").write_text("unauthorized\n")
        git(self.fx.final, "add", "unapproved.txt")
        git(self.fx.final, "commit", "-m", "extra")
        self.fx.manifest["final_revision"] = git(self.fx.final, "rev-parse", "HEAD")
        self.fx.save()
        result = self.fx.run()
        self.assertEqual(result["decision"], "FAIL")
        self.assertEqual(result["findings"][0]["requirement"], "changed_files")

    def test_05_missing_input_rejected(self):
        (self.fx.input_dir / "qa-input.json").unlink()
        self.assertEqual(self.fx.run()["decision"], "FAIL")

    def test_06_malformed_input_rejected(self):
        (self.fx.input_dir / "qa-input.json").write_text("{broken")
        self.assertEqual(self.fx.run()["decision"], "FAIL")

    def test_07_developer_report_is_untrusted(self):
        self.fx.report["tests"] = [{"name": "fake", "outcome": "passed", "evidence": "fake"}]
        self.fx.manifest["developer_reports"] = [copy.deepcopy(self.fx.report)]
        self.fx.save()
        result = self.fx.run()
        self.assertEqual(result["decision"], "PASS")
        self.assertIn("Ran 2 tests", result["tests"][1]["output"])

    def test_08_fake_report_cannot_replace_disk_report(self):
        self.fx.manifest["developer_reports"][0]["tests"] = []
        self.fx.save()
        self.assertEqual(self.fx.run()["decision"], "FAIL")

    def test_09_failing_code_produces_fail_and_correction(self):
        change = "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a + b\n"
        (self.fx.dev / "calculator.py").write_text(change)
        git(self.fx.dev, "add", "calculator.py")
        git(self.fx.dev, "commit", "-m", "bad")
        (self.fx.final / "calculator.py").write_text(change)
        git(self.fx.final, "add", "calculator.py")
        git(self.fx.final, "commit", "-m", "bad")
        self.fx.report["commits"] = git(self.fx.dev, "rev-list", f"{self.fx.base}..HEAD").splitlines()
        self.fx.manifest["final_revision"] = git(self.fx.final, "rev-parse", "HEAD")
        # The fixture's second commit on each branch makes their final trees equal.
        new_hash = sha(change.encode())
        self.fx.report["files_modified"][0]["sha256"] = new_hash
        self.fx.report["qa_handoff"]["changed_file_hashes"]["calculator.py"] = new_hash
        self.fx.manifest["changed_file_hashes"]["calculator.py"] = new_hash
        self.fx.manifest["developer_reports"] = [copy.deepcopy(self.fx.report)]
        self.fx.save()
        result = self.fx.run()
        self.assertEqual(result["decision"], "FAIL")
        self.assertEqual(result["tests"][0]["result"], "FAIL")
        self.assertTrue((self.fx.root / "qa-output/fixture-qa/T-0002/correction-request.json").is_file())

    def test_10_missing_execution_capability_blocked(self):
        self.assertEqual(self.fx.run(bwrap="/nonexistent/bwrap")["decision"], "BLOCKED")

    def test_11_duplicate_execution_returns_same_report(self):
        first = self.fx.run()
        second = self.fx.run()
        self.assertEqual(first, second)
        self.assertEqual(len(list((self.fx.root / "qa-output/fixture-qa/T-0002").glob("qa-report*.json"))), 1)

    def test_12_qa_cannot_change_developer_source(self):
        before = (self.fx.dev / "calculator.py").read_bytes(), (self.fx.final / "calculator.py").read_bytes()
        self.fx.run()
        after = (self.fx.dev / "calculator.py").read_bytes(), (self.fx.final / "calculator.py").read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(git(self.fx.final, "status", "--porcelain"), "")

    def test_13_qa_cannot_approve_publish_merge_or_deploy(self):
        before = {p.name: p.read_bytes() for p in self.fx.grants.iterdir()}
        ref = git(self.fx.repo, "rev-parse", "main")
        self.fx.run()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.fx.grants.iterdir()})
        self.assertEqual(ref, git(self.fx.repo, "rev-parse", "main"))
        self.assertFalse(list(self.fx.root.rglob("*.service")))

    def test_14_review_handoff_binds_exact_report_and_revision(self):
        self.fx.run()
        root = self.fx.root / "qa-output/fixture-qa/T-0002"
        handoff = json.loads((root / "reviewer-handoff.json").read_text())
        self.assertEqual(handoff["final_revision"], self.fx.revision)
        self.assertEqual(handoff["qa_report_sha256"], sha((root / "qa-report.json").read_bytes()))


if __name__ == "__main__":
    unittest.main()
