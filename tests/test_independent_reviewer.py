"""Reviewer staging tests. Git writes occur only in disposable fixtures."""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import jsonschema

from independent_reviewer import host_release, worker
from tests.test_independent_qa import Fixture, git, sha


def model_answer(context):
    return ({"decision": "APPROVED", "findings": [], "coverage": [
        {"criterion": row["criterion"], "result": "PASS", "evidence": "Git diff and QA result"}
        for row in context["report"]["acceptance_criteria"]]},
        {"provider": "codex", "model": "gpt-6-astra", "reasoning_effort": "medium",
         "fallback_used": False, "identity_source": "fixture"})


def model_with_general_row(context):
    answer, used = model_answer(context)
    answer["coverage"].append({"criterion": worker.GENERAL_REVIEW_CRITERION,
                               "result": "PASS", "evidence": "Git diff and approved scope"})
    return answer, used


class ReviewerFixture:
    def __init__(self, root: Path):
        self.qa = Fixture(root)
        self.root = root
        self.out = root / "review-output"
        self.spec = self.qa.repo / ".dev/tasks/T-0002-fixture.md"
        self.plan = self.qa.gateway / "cto-plans/fixture-qa-T-0002.json"
        self.grant = self.qa.grants / ("grant-" + "f" * 32 + ".json")
        self.qa_dir = root / "qa-state/fixture-qa/T-0002"
        self.qa_dir.mkdir(parents=True)
        self.report = {
            "schema": "alfred.qa-report/1", "project": "fixture-qa", "task_id": "T-0002",
            "decision": "PASS", "developer_commits": [self.qa.commit],
            "final_revision": self.qa.revision, "baseline_revision": self.qa.base,
            "files_inspected": ["calculator.py", "test_calculator.py"],
            "changed_file_hashes": copy.deepcopy(self.qa.manifest["changed_file_hashes"]),
            "tests": [{"id": "calculator_examples", "command": ["python3"], "exit_code": 0,
                       "result": "PASS", "output": "add=10 subtract=4"}],
            "acceptance_criteria": [
                {"criterion": criterion, "result": "PASS", "evidence": "calculator_examples"}
                for criterion in ("add(7, 3) returns 10.", "subtract(7, 3) returns 4.",
                                  "The existing unittest discovery command passes.")],
            "findings": [], "qa_model": None,
            "evidence": {"cto_plan_sha256": sha(self.plan.read_bytes()),
                         "development_grant_sha256": sha(self.grant.read_bytes()),
                         "canonical_task_sha256": sha(self.spec.read_bytes()),
                         "development_grant_reference": "f" * 32},
            "next_authorized_action": "independent_reviewer"}
        self.handoff = {"schema": "alfred.reviewer-handoff/1", "project": "fixture-qa", "task_id": "T-0002",
                        "final_revision": self.qa.revision, "baseline_revision": self.qa.base,
                        "developer_commits": [self.qa.commit],
                        "changed_file_hashes": copy.deepcopy(self.report["changed_file_hashes"]),
                        "qa_report_sha256": "", "decision": "PASS", "next_stage": "independent_reviewer"}
        self.config = {"schema": "alfred.reviewer-config/1", "project": "fixture-qa", "task_id": "T-0002",
                       "expected_qa_report_sha256": "", "model": {"provider": "codex", "model": "gpt-6-astra",
                       "reasoning_effort": "medium", "timeout_seconds": 180,
                       "cli": "/home/alfred/.local/bin/codex"}, "max_diff_bytes": 131072}
        self.save()

    def save(self):
        report_bytes = (json.dumps(self.report, sort_keys=True) + "\n").encode()
        (self.qa_dir / "qa-report.json").write_bytes(report_bytes)
        self.handoff["qa_report_sha256"] = sha(report_bytes)
        self.config["expected_qa_report_sha256"] = sha(report_bytes)
        (self.qa_dir / "reviewer-handoff.json").write_text(json.dumps(self.handoff, sort_keys=True) + "\n")
        (self.root / "review-config.json").write_text(json.dumps(self.config, sort_keys=True) + "\n")

    def args(self):
        return (self.qa_dir / "reviewer-handoff.json", self.qa_dir / "qa-report.json",
                self.qa.final, self.plan, self.grant, self.spec,
                self.root / "review-config.json", self.out)

    def run(self, model=model_answer):
        return worker.run(*self.args(), model_runner=model)


class IndependentReviewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="review-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.fx = ReviewerFixture(Path(self.temp.name))

    def test_01_valid_pass_handoff_approved_and_publication_pinned(self):
        result = self.fx.run()
        self.assertEqual(result["decision"], "APPROVED")
        self.assertEqual(result["files_inspected"], ["calculator.py"])
        self.assertEqual(result["model_used"]["model"], "gpt-6-astra")
        output = self.fx.out / "fixture-qa/T-0002"
        publication = json.loads((output / "publication-handoff.json").read_text())
        self.assertEqual(publication["final_revision"], self.fx.qa.revision)
        self.assertEqual(publication["qa_report_sha256"], result["qa_report_sha256"])
        self.assertEqual(publication["review_report_sha256"], sha((output / "review-report.json").read_bytes()))

    def test_02_wrong_qa_report_hash_blocked(self):
        self.fx.config["expected_qa_report_sha256"] = "0" * 64
        (self.fx.root / "review-config.json").write_text(json.dumps(self.fx.config))
        self.assertEqual(self.fx.run()["decision"], "BLOCKED")

    def test_03_wrong_revision_blocked(self):
        self.fx.report["final_revision"] = self.fx.handoff["final_revision"] = "0" * 40
        self.fx.save()
        self.assertEqual(self.fx.run()["decision"], "BLOCKED")

    def test_04_unauthorized_file_blocked(self):
        (self.fx.qa.final / "unapproved.txt").write_text("outside scope\n")
        git(self.fx.qa.final, "add", "unapproved.txt")
        git(self.fx.qa.final, "commit", "-m", "unauthorized")
        revision = git(self.fx.qa.final, "rev-parse", "HEAD")
        self.fx.report["final_revision"] = self.fx.handoff["final_revision"] = revision
        self.fx.save()
        self.assertEqual(self.fx.run()["decision"], "BLOCKED")

    def test_04b_intermediate_unauthorized_commit_blocked(self):
        extra = self.fx.qa.final / "unapproved.txt"
        extra.write_text("outside scope\n")
        git(self.fx.qa.final, "add", "unapproved.txt")
        git(self.fx.qa.final, "commit", "-m", "unauthorized intermediate")
        git(self.fx.qa.final, "rm", "unapproved.txt")
        git(self.fx.qa.final, "commit", "-m", "revert unauthorized file")
        revision = git(self.fx.qa.final, "rev-parse", "HEAD")
        self.fx.report["final_revision"] = self.fx.handoff["final_revision"] = revision
        self.fx.save()
        result = self.fx.run()
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertEqual(result["findings"][0]["requirement"], "approved_scope")

    def test_05_tampered_handoff_blocked(self):
        self.fx.handoff["next_stage"] = "github_draft_pr"
        self.fx.save()
        self.assertEqual(self.fx.run()["decision"], "BLOCKED")

    def test_06_no_source_or_qa_rewrite(self):
        before = (self.fx.qa.final / "calculator.py").read_bytes(), (self.fx.qa_dir / "qa-report.json").read_bytes()
        self.fx.run()
        self.assertEqual(before, ((self.fx.qa.final / "calculator.py").read_bytes(),
                                  (self.fx.qa_dir / "qa-report.json").read_bytes()))
        self.assertEqual(git(self.fx.qa.final, "status", "--porcelain"), "")

    def test_07_model_finding_requests_changes(self):
        def detects_bug(context):
            answer, used = model_answer(context)
            answer["decision"] = "CHANGES_REQUESTED"
            answer["findings"] = [{"severity": "high", "requirement": "subtraction",
                                    "detail": "subtract adds rather than subtracts", "evidence": "calculator.py diff"}]
            return answer, used
        result = self.fx.run(detects_bug)
        self.assertEqual(result["decision"], "CHANGES_REQUESTED")
        correction = json.loads((self.fx.out / "fixture-qa/T-0002/correction-request.json").read_text())
        self.assertFalse(correction["new_development_authorization"])
        root = Path(__file__).resolve().parents[1] / "independent_reviewer/schemas"
        jsonschema.validate(correction, json.loads((root / "correction-request.schema.json").read_text()))

    def test_08_model_failure_blocked_cannot_publish(self):
        def unavailable(_):
            raise worker.EvidenceError("model", "unavailable")
        result = self.fx.run(unavailable)
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertFalse((self.fx.out / "fixture-qa/T-0002/publication-handoff.json").exists())

    def test_09_qa_fail_cannot_approve(self):
        self.fx.report["decision"] = "FAIL"
        self.fx.save()
        self.assertEqual(self.fx.run()["decision"], "BLOCKED")

    def test_10_repeat_is_idempotent_and_changed_input_rejected(self):
        first = self.fx.run()
        self.assertEqual(first, self.fx.run())
        self.fx.handoff["next_stage"] = "wrong"
        self.fx.save()
        with self.assertRaisesRegex(worker.EvidenceError, "different or invalid evidence"):
            self.fx.run()

    def test_11_model_identity_and_fallback_recorded(self):
        result = self.fx.run()
        self.assertEqual(result["model_used"]["provider"], "codex")
        self.assertEqual(result["model_fallback"], "none")

    def test_12_no_github_invocation(self):
        from unittest.mock import patch
        real = worker.subprocess.run
        def guard(args, *rest, **kw):
            if "gh" in str(args) or "github" in str(args):
                raise AssertionError("publication invoked")
            return real(args, *rest, **kw)
        with patch.object(worker.subprocess, "run", side_effect=guard):
            self.fx.run()

    def test_13_staged_t0002_pass_artifact_is_accepted(self):
        root = Path(__file__).resolve().parents[1]
        qa = root / "independent_qa/staging-release/dev-v1-accept/T-0002"
        config = self.fx.root / "t0002-config.json"
        configured = copy.deepcopy(self.fx.config)
        configured["project"], configured["task_id"] = "dev-v1-accept", "T-0002"
        configured["expected_qa_report_sha256"] = sha((qa / "qa-report.json").read_bytes())
        config.write_text(json.dumps(configured))
        context = worker.verify_inputs(
            qa / "reviewer-handoff.json", qa / "qa-report.json",
            Path("/var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final"),
            Path("/home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0002.json"),
            Path("/var/lib/alfred-development-grants/grant-445759a699d9423bbb5a8f1dd589689a.json"),
            root / "live-acceptance/repo/.dev/tasks/T-0002-backend-calculator-subtract-helper.md", config)
        self.assertEqual(context["revision"], "89ba188f8a2f801d433a30c9c21363efb3e1043d")

    def test_14_read_only_clone_has_exact_git_objects(self):
        snapshot = self.fx.root / "review-snapshot"
        subprocess.run(["git", "clone", "--no-local", "--no-checkout", str(self.fx.qa.final),
                        str(snapshot)], capture_output=True, check=True)
        git(snapshot, "checkout", "--detach", self.fx.qa.revision)
        args = list(self.fx.args())
        args[2] = snapshot
        context = worker.verify_inputs(*args[:-1])
        self.assertEqual(context["revision"], self.fx.qa.revision)
        self.assertEqual(context["hashes"], self.fx.report["changed_file_hashes"])

    def test_15_report_and_handoff_match_schemas(self):
        self.fx.run()
        root = Path(__file__).resolve().parents[1] / "independent_reviewer/schemas"
        out = self.fx.out / "fixture-qa/T-0002"
        for stem, schema in (("review-report", "review-report"),
                             ("publication-handoff", "publication-handoff")):
            jsonschema.validate(json.loads((out / (stem + ".json")).read_text()),
                                json.loads((root / (schema + ".schema.json")).read_text()))

    def test_16_incomplete_coverage_blocks_approval(self):
        def incomplete(context):
            answer, used = model_answer(context)
            answer["coverage"].pop()
            return answer, used
        self.assertEqual(self.fx.run(incomplete)["decision"], "BLOCKED")

    def test_16a_live_fourth_general_row_does_not_block(self):
        result = self.fx.run(model_with_general_row)
        self.assertEqual(result["decision"], "APPROVED")
        self.assertEqual(result["correctness"], "PASS")
        self.assertEqual(len(result["acceptance_coverage"]), 4)
        self.assertTrue((self.fx.out / "fixture-qa/T-0002/publication-handoff.json").is_file())

    def test_16b_missing_task_criterion_with_general_row_blocks(self):
        def missing(context):
            answer, used = model_with_general_row(context)
            answer["coverage"].pop(1)
            return answer, used
        self.assertEqual(self.fx.run(missing)["decision"], "BLOCKED")

    def test_16c_materially_altered_task_criterion_blocks(self):
        def altered(context):
            answer, used = model_with_general_row(context)
            answer["coverage"][1]["criterion"] = "subtract(7, 3) returns 5."
            return answer, used
        self.assertEqual(self.fx.run(altered)["decision"], "BLOCKED")

    def test_16d_duplicate_task_criterion_blocks(self):
        def duplicate(context):
            answer, used = model_with_general_row(context)
            answer["coverage"].append(copy.deepcopy(answer["coverage"][1]))
            return answer, used
        self.assertEqual(self.fx.run(duplicate)["decision"], "BLOCKED")

    def test_16e_unsupported_extra_criterion_blocks(self):
        def unsupported(context):
            answer, used = model_answer(context)
            answer["coverage"].append({"criterion": "Unapproved fourth task objective.",
                                       "result": "PASS", "evidence": "model assertion"})
            return answer, used
        self.assertEqual(self.fx.run(unsupported)["decision"], "BLOCKED")

    def test_16f_general_row_failure_requests_changes(self):
        def failing(context):
            answer, used = model_with_general_row(context)
            answer["coverage"][-1]["result"] = "FAIL"
            return answer, used
        self.assertEqual(self.fx.run(failing)["decision"], "CHANGES_REQUESTED")

    def test_16g_retry_keeps_old_blocked_report(self):
        def unavailable(_):
            raise worker.EvidenceError("model", "fixture failure")
        self.assertEqual(self.fx.run(unavailable)["decision"], "BLOCKED")
        old = self.fx.out / "fixture-qa/T-0002/review-report.json"
        old_bytes = old.read_bytes()
        fresh = self.fx.root / "review-output-v4"
        result = worker.run(*self.fx.args()[:-1], fresh, model_runner=model_with_general_row)
        self.assertEqual(result["decision"], "APPROVED")
        self.assertEqual(old.read_bytes(), old_bytes)

    def test_16h_duplicate_general_row_blocks(self):
        def duplicate(context):
            answer, used = model_with_general_row(context)
            answer["coverage"].append(copy.deepcopy(answer["coverage"][-1]))
            return answer, used
        self.assertEqual(self.fx.run(duplicate)["decision"], "BLOCKED")

    def test_17_failed_coverage_requests_changes(self):
        def failing(context):
            answer, used = model_answer(context)
            answer["coverage"][1]["result"] = "FAIL"
            return answer, used
        self.assertEqual(self.fx.run(failing)["decision"], "CHANGES_REQUESTED")

    def test_18_retry_repairs_missing_publication_handoff(self):
        self.fx.run()
        output = self.fx.out / "fixture-qa/T-0002"
        (output / "publication-handoff.json").unlink()
        self.assertEqual(self.fx.run()["decision"], "APPROVED")
        self.assertTrue((output / "publication-handoff.json").is_file())

    def test_19_qa_criteria_must_cover_cto_plan(self):
        self.fx.report["acceptance_criteria"].pop()
        self.fx.save()
        self.assertEqual(self.fx.run()["decision"], "BLOCKED")

    def test_20_release_manifest_and_tamper_rejection(self):
        source = Path(__file__).resolve().parents[1] / "independent_reviewer"
        # v4 is the installed predecessor; v5 (handoff.6) accepts Codex progress notes
        # before the single final decision and is the current source.
        self.assertEqual(host_release.verify(
            source / "host-candidate-v4/independent_reviewer",
            "f6f789de9a8bb5e4e6b9dd67db9decc5e8ee760c203ebba6a45ef61532cc5832"),
            "f6f789de9a8bb5e4e6b9dd67db9decc5e8ee760c203ebba6a45ef61532cc5832")
        pinned = source / "host-candidate-v5/independent_reviewer"
        pin = "62481e522cb78e1284d49a49f6a377773e80485a587c941a052427c0afd4efbe"
        self.assertEqual(host_release.verify(pinned, pin), pin)
        self.assertTrue(all((source / name).read_bytes() == (pinned / name).read_bytes()
                            for name in host_release.FILES))
        disposable = self.fx.root / "release"
        self.assertEqual(host_release.build(source, disposable), pin)
        (disposable / "worker.py").write_text("tampered")
        with self.assertRaises(ValueError):
            host_release.verify(disposable, pin)

    def test_21_operator_commands_parse_and_use_verified_root_copy(self):
        source = Path(__file__).resolve().parents[1] / "independent_reviewer"
        guide = (source / "HOST_OPERATOR.md").read_text()
        self.assertIn("host-candidate-v3", guide)
        self.assertIn("a8eceb9b7a72bb2b601a28cde0cfe7c33e6cd65fb6cee8694abe6d0f1bf8c0d8", guide)
        self.assertLess(guide.index("sudo /bin/sh -c 'cd /var/lib/alfred-reviewer-prepared-v3"),
                        guide.index("sudo /usr/bin/python3 -I -B -c"))
        import re
        for block in re.findall(r"```sh\n(.*?)\n```", guide, re.S):
            subprocess.run(["bash", "-n"], input=block, text=True, check=True)

    def test_22_disposable_host_copy_verifies_before_import(self):
        source = Path(__file__).resolve().parents[1] / "independent_reviewer/host-candidate-v4/independent_reviewer"
        prepared = self.fx.root / "prepared/independent_reviewer"
        subprocess.run(["/usr/bin/install", "-d", "-m", "0700", str(prepared / "schemas")], check=True)
        for name in (*host_release.FILES, "release.sha256"):
            subprocess.run(["/usr/bin/install", "-m", "0444", str(source / name),
                            str(prepared / name)], check=True)
        pin = "f6f789de9a8bb5e4e6b9dd67db9decc5e8ee760c203ebba6a45ef61532cc5832"
        self.assertEqual(host_release.verify(prepared, pin), pin)
        subprocess.run(["/usr/bin/sha256sum", "-c", "release.sha256"], cwd=prepared,
                       capture_output=True, check=True)
        self.assertFalse(any(p.stat().st_mode & 0o022 for p in prepared.rglob("*") if p.is_file()))

    def test_23_upgrade_procedure_and_disposable_rollback(self):
        source = Path(__file__).resolve().parents[1] / "independent_reviewer"
        guide = (source / "UPGRADE_V4.md").read_text()
        pin_v4 = "f6f789de9a8bb5e4e6b9dd67db9decc5e8ee760c203ebba6a45ef61532cc5832"
        pin_v3 = "a8eceb9b7a72bb2b601a28cde0cfe7c33e6cd65fb6cee8694abe6d0f1bf8c0d8"
        self.assertIn(pin_v4, guide)
        self.assertIn("/var/lib/alfred-reviewer-state-v4", guide)
        self.assertLess(guide.index("sha256sum -c release.sha256"),
                        guide.index("from independent_reviewer.host_release import verify"))
        import re
        for block in re.findall(r"```sh\n(.*?)\n```", guide, re.S):
            subprocess.run(["bash", "-n"], input=block, text=True, check=True)
        installed = self.fx.root / "opt/alfred-reviewer-v1"
        installed.parent.mkdir(parents=True)
        old_package = source / "host-candidate-v3/independent_reviewer"
        shutil.copytree(old_package, installed / "independent_reviewer")
        old_output = self.fx.root / "reviewer-state/T-0002"
        old_output.mkdir(parents=True)
        (old_output / "review-report.json").write_text("historical BLOCKED report")
        before = (old_output / "review-report.json").read_bytes()
        backup = self.fx.root / "backups/v4"
        backup.mkdir(parents=True)
        installed.rename(backup / "v3-install")
        new_package = source / "host-candidate-v4/independent_reviewer"
        shutil.copytree(new_package, installed / "independent_reviewer")
        self.assertEqual(host_release.verify(installed / "independent_reviewer", pin_v4), pin_v4)
        fresh_output = self.fx.root / "reviewer-state-v4"
        fresh_output.mkdir()
        installed.rename(backup / "unaccepted-v4-install")
        (backup / "v3-install").rename(installed)
        fresh_output.rename(backup / "v4-output")
        self.assertEqual(host_release.verify(installed / "independent_reviewer", pin_v3), pin_v3)
        self.assertEqual((old_output / "review-report.json").read_bytes(), before)

    @unittest.skipUnless(os.environ.get("ALFRED_REVIEW_MODEL_TEST") == "1", "authenticated model probe opt-in")
    def test_24_real_model_detects_known_defective_diff(self):
        context = worker.verify_inputs(*self.fx.args()[:-1])
        context["diff"] = ("diff --git a/calculator.py b/calculator.py\n"
                           "--- a/calculator.py\n+++ b/calculator.py\n@@ -2,0 +3,2 @@\n"
                           "+def subtract(a, b):\n+    return a + b\n")
        answer, used = worker.review_with_model(context)
        self.assertEqual(used["model"], "gpt-6-astra")
        self.assertEqual(answer["decision"], "CHANGES_REQUESTED")
        self.assertTrue(any("subtract" in f["detail"].lower() for f in answer["findings"]))


if __name__ == "__main__":
    unittest.main()
