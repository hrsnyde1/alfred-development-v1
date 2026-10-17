"""Staged QA release and installation invariants; no host paths are changed."""

import hashlib
import os
import pwd
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from independent_qa import host_acceptance, host_install, host_preflight, host_release
from independent_qa.worker import verify as verify_qa_input


SOURCE = Path(__file__).resolve().parents[1] / "independent_qa"


class QAHostInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qa-host-install-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_release_manifest_pins_exact_file_inventory(self):
        release = self.root / "release"
        pin = host_release.build(SOURCE, release)
        self.assertEqual(host_release.verify(release, pin), pin)
        self.assertEqual({str(p.relative_to(release)) for p in release.rglob("*") if p.is_file()},
                         set(host_release.PACKAGE_FILES) | {"release.sha256"})

    def test_staged_install_copies_only_pinned_bytes(self):
        release = self.root / "release"
        pin = host_release.build(SOURCE, release)
        staged = self.root / "installed"
        self.assertEqual(host_install.stage_copy(release, staged, pin), pin)
        package = staged / "independent_qa"
        self.assertEqual(host_release.verify(package, pin), pin)
        self.assertFalse(any(p.stat().st_mode & 0o022 for p in package.rglob("*") if p.is_file()))
        self.assertEqual(stat.S_IMODE((package / "worker.py").stat().st_mode), 0o555)

    def test_tampered_release_is_rejected(self):
        release = self.root / "release"
        pin = host_release.build(SOURCE, release)
        (release / "worker.py").chmod(0o644)
        (release / "worker.py").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            host_install.stage_copy(release, self.root / "installed", pin)

    def test_wrong_pin_and_overwrite_are_rejected(self):
        release = self.root / "release"
        pin = host_release.build(SOURCE, release)
        with self.assertRaises(ValueError):
            host_release.verify(release, "0" * 64)
        installed = self.root / "installed"
        host_install.stage_copy(release, installed, pin)
        with self.assertRaises(FileExistsError):
            host_install.stage_copy(release, installed, pin)

    def test_installer_rejects_user_writable_release(self):
        release = self.root / "writable-release"
        pin = host_release.build(SOURCE, release)
        with self.assertRaisesRegex(PermissionError, "root-owned"):
            host_install.trusted_release(release, pin)

    def test_acl_plan_is_narrow(self):
        self.assertNotIn(host_preflight.STATE, host_install.TRAVERSE)
        self.assertNotIn(host_preflight.GRANTS, host_install.TRAVERSE)
        self.assertNotIn(host_preflight.GATEWAY, host_install.TRAVERSE)
        self.assertEqual(host_install.EXACT_READ, ())
        self.assertIn(host_install.REPOSITORY, host_install.TREES)
        self.assertEqual({path for path, _ in host_preflight.HANDOFF_FILES if path in host_preflight.GRANT_FILES},
                         set(host_preflight.GRANT_FILES))
        self.assertNotIn(host_preflight.QA_INPUT.parent / ".lock",
                         {path for path, _ in host_preflight.HANDOFF_FILES})
        self.assertNotIn(host_preflight.QA_INPUT.parent / "backend-subtract.json",
                         {path for path, _ in host_preflight.HANDOFF_FILES})
        self.assertEqual(len(host_install.TREES), 3)

    def test_disposable_acl_apply_and_exact_restore(self):
        single = self.root / "protected.json"
        single.write_text("{}")
        tree = self.root / "repo"
        (tree / ".git/objects/aa").mkdir(parents=True)
        blob = tree / ".git/objects/aa/object"
        blob.write_text("blob")
        other = self.root / "other-project"
        other.mkdir()
        before_single = host_install.command("/usr/bin/getfacl", "-p", str(single))
        before_tree = host_install.command("/usr/bin/getfacl", "-R", "-p", str(tree))
        before_other = host_install.command("/usr/bin/getfacl", "-p", str(other))
        backup = self.root / "backup"
        with patch.object(host_install, "TRAVERSE", (self.root,)), \
                patch.object(host_install, "EXACT_READ", (single,)), \
                patch.object(host_install, "TREES", (tree,)), \
                patch.object(host_install, "QA_DENY", (other,)):
            host_install.acl_backup(backup)
            host_install.acl_apply()
            self.assertIn(b"user:alfredqa:r--", host_install.command("/usr/bin/getfacl", "-p", str(single)))
            self.assertIn(b"user:alfredqa:r--", host_install.command("/usr/bin/getfacl", "-p", str(blob)))
            self.assertIn(b"user:alfredqa:---", host_install.command("/usr/bin/getfacl", "-p", str(other)))
            host_install.acl_restore(backup)
        self.assertEqual(before_single, host_install.command("/usr/bin/getfacl", "-p", str(single)))
        self.assertEqual(before_tree, host_install.command("/usr/bin/getfacl", "-R", "-p", str(tree)))
        self.assertEqual(before_other, host_install.command("/usr/bin/getfacl", "-p", str(other)))

    def test_root_handoff_copies_pinned_bytes_before_python_import(self):
        release = self.root / "user-release"
        pin = host_release.build(SOURCE, release)
        prepared = self.root / "root-owned-simulation" / "independent_qa"
        subprocess.run(["/usr/bin/install", "-d", "-m", "0700", str(prepared / "schemas")], check=True)
        for name in (*host_release.PACKAGE_FILES, "release.sha256"):
            subprocess.run(["/usr/bin/install", "-m", "0444", str(release / name),
                            str(prepared / name)], check=True)
        subprocess.run(["/usr/bin/sha256sum", "-c", "release.sha256"], cwd=prepared,
                       capture_output=True, check=True)
        self.assertEqual(hashlib.sha256((prepared / "release.sha256").read_bytes()).hexdigest(), pin)
        self.assertEqual(host_release.verify(prepared, pin), pin)
        (release / "worker.py").chmod(0o644)
        (release / "worker.py").write_bytes(b"tampered after handoff")
        self.assertEqual(host_release.verify(prepared, pin), pin)
        result = subprocess.run(["/usr/bin/python3", "-B", "-c",
                                 "from independent_qa.host_release import verify; "
                                 "from pathlib import Path; import sys; "
                                 "print(verify(Path(sys.argv[1]), sys.argv[2]))",
                                 str(prepared), pin], cwd="/tmp",
                                env={**os.environ, "PYTHONPATH": str(prepared.parent)},
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), pin)
        self.assertFalse(any(p.stat().st_mode & 0o022 for p in prepared.rglob("*") if p.is_file()))

    def test_operator_handoff_uses_only_verified_root_copy_for_admin_python(self):
        guide = (SOURCE / "HOST_OPERATOR.md").read_text()
        pin = host_release.verify(SOURCE / "host-candidate-v9/independent_qa")
        self.assertIn(pin, guide)
        self.assertNotIn("sudo /usr/bin/env PYTHONPATH=/home/alfred", guide)
        self.assertLess(guide.index("sudo /usr/bin/install -o root"),
                        guide.index("sudo /usr/bin/sha256sum /var/lib/alfred-independent-qa-prepared-v3"))
        self.assertLess(guide.index("sudo /bin/sh -c 'cd /var/lib/alfred-independent-qa-prepared-v3"),
                        guide.index("sudo /usr/bin/python3 -I -B -c"))
        self.assertIn("--release /var/lib/alfred-independent-qa-prepared-v3/independent_qa", guide)

    def test_effective_access_probe_and_change_detection(self):
        path = self.root / "access-probe"
        path.write_text("fixture")
        user = pwd.getpwuid(os.geteuid()).pw_name
        before = host_preflight.observe_access((path,), (user,))
        self.assertEqual(before["access"][user][str(path)][:2], [True, True])
        path.chmod(0o400)
        after = host_preflight.observe_access((path,), (user,))
        self.assertEqual(after["access"][user][str(path)][:2], [True, False])
        baseline = {"schema": host_preflight.ACCESS_SCHEMA,
                    "users": list(host_preflight.SERVICE_USERS),
                    "access": {name: before["access"][user] for name in host_preflight.SERVICE_USERS}}
        current = {**baseline, "access": {name: after["access"][user] for name in host_preflight.SERVICE_USERS}}
        with self.assertRaisesRegex(PermissionError, "effective access"):
            host_preflight.assert_access_preserved(baseline, current)
        host_preflight.assert_access_preserved(baseline, baseline)

    def test_unrelated_evidence_requires_real_read_denial(self):
        parent = self.root / "protected"
        parent.mkdir()
        (self.root / "cto-plans").mkdir()
        allowed = parent / "required.json"
        allowed.write_text("required")
        other = parent / "other.json"
        other.write_text("private")
        user = pwd.getpwuid(os.geteuid()).pw_name
        real_probe = host_preflight.observe_access
        def own_os_probe(paths, users):
            observed = real_probe(paths, (user,))
            return {"access": {"alfredqa": observed["access"][user]}}
        with patch.object(host_preflight, "STATE", parent), \
                patch.object(host_preflight, "QA_INPUT", allowed), \
                patch.object(host_preflight, "GRANTS", parent), \
                patch.object(host_preflight, "GATEWAY", parent.parent), \
                patch.object(host_preflight, "REGISTRY", allowed), \
                patch.object(host_preflight, "READ_FILES", (allowed,)), \
                patch.object(host_preflight, "observe_access", side_effect=own_os_probe):
            with self.assertRaisesRegex(PermissionError, "unrelated evidence"):
                host_preflight.assert_other_evidence_denied()
            other.chmod(0o000)
            allowed.chmod(0o000)
            self.assertEqual(host_preflight.assert_other_evidence_denied(), 2)

    def test_separate_evidence_handoff_exposes_only_required_copies(self):
        source = self.root / "developer-state"
        source.mkdir()
        required = source / "qa-input.json"
        required.write_bytes(b"canonical")
        unrelated = source / ".lock"
        unrelated.write_bytes(b"private execution state")
        lock_before = (unrelated.read_bytes(), unrelated.stat().st_mode,
                       host_install.command("/usr/bin/getfacl", "-p", str(unrelated)))
        target = self.root / "qa-evidence"
        files = ((required, "fixture/T-0002/qa-input.json"),)
        old_umask = os.umask(0o022)
        try:
            sha = host_install.stage_evidence(target, files, {}, require_root=False)
        finally:
            os.umask(old_umask)
        self.assertEqual(host_preflight.verify_handoff(target, files, {}, require_root=False), sha)
        with self.assertRaisesRegex(PermissionError, "root-owned"):
            host_preflight.verify_handoff(target, files, {}, require_root=True)
        for directory in (target, target / "fixture", target / "fixture/T-0002"):
            self.assertEqual(directory.stat().st_mode & 0o027, 0, str(directory))
            acl = host_install.command("/usr/bin/getfacl", "-cp", str(directory))
            self.assertIn(b"user:alfredqa:r-x", acl)
            self.assertIn(b"other::---", acl)
        self.assertEqual({p.name for p in target.rglob("*") if p.is_file()},
                         {"qa-input.json", "evidence.sha256"})
        self.assertNotIn(b"private execution state", (target / "fixture/T-0002/qa-input.json").read_bytes())
        self.assertEqual((unrelated.read_bytes(), unrelated.stat().st_mode,
                          host_install.command("/usr/bin/getfacl", "-p", str(unrelated))), lock_before)
        copied_acl = host_install.command("/usr/bin/getfacl", "-cp", str(target / "fixture/T-0002/qa-input.json"))
        self.assertIn(b"user:alfredqa:r--", copied_acl)
        self.assertIn(b"other::---", copied_acl)
        self.assertNotIn(b"user:alfredqa:rw", copied_acl)
        required.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "differs from canonical"):
            host_preflight.verify_handoff(target, files, {}, require_root=False)
        required.write_bytes(b"canonical")
        (target / "fixture/T-0002/.lock").write_bytes(b"should never be handed off")
        with self.assertRaisesRegex(ValueError, "unlisted path"):
            host_preflight.verify_handoff(target, files, {}, require_root=False)

    def test_handoff_verifier_rejects_public_intermediate_directory(self):
        source = self.root / "source.json"
        source.write_text("{}")
        target = self.root / "qa-evidence"
        files = ((source, "project/task/qa-input.json"),)
        host_install.stage_evidence(target, files, {}, require_root=False)
        host_install.command("/usr/bin/setfacl", "-m", "o::r-x", str(target / "project"))
        with self.assertRaisesRegex(PermissionError, "evidence directory"):
            host_preflight.verify_handoff(target, files, {}, require_root=False)

    def test_failed_install_restores_acl_and_preserves_partial_evidence(self):
        release = self.root / "release"
        pin = host_release.build(SOURCE, release)
        (self.root / "opt").mkdir()
        protected = self.root / "protected"
        protected.mkdir()
        tree = self.root / "repo"
        tree.mkdir()
        (tree / "source.py").write_text("pass\n")
        other = self.root / "other-project"
        other.mkdir()
        required = self.root / "source.json"
        required.write_text("{}")
        before = {path: host_install.command("/usr/bin/getfacl", "-p", str(path))
                  for path in (protected, tree, tree / "source.py", other)}
        real_stage = host_install.stage_evidence
        def disposable_stage(target):
            return real_stage(target, ((required, "fixture/T-0002/qa-input.json"),),
                              {}, require_root=False)
        with patch.object(host_install, "INSTALL", self.root / "opt/install"), \
                patch.object(host_install, "OUTPUT", self.root / "qa-output"), \
                patch.object(host_install, "EVIDENCE", self.root / "qa-evidence"), \
                patch.object(host_install, "BACKUPS", self.root / "backups"), \
                patch.object(host_install, "TRAVERSE", (protected,)), \
                patch.object(host_install, "TREES", (tree,)), \
                patch.object(host_install, "QA_DENY", (other,)), \
                patch.object(host_install, "EXACT_READ", ()), \
                patch.object(host_install, "trusted_release"), \
                patch.object(host_install, "observe_access", return_value={"schema": "fixture"}), \
                patch.object(host_install, "stage_evidence", side_effect=disposable_stage), \
                patch.object(host_install, "administrator", side_effect=(RuntimeError("preflight rejected"),
                                                                           {"result": "PASS"})), \
                patch.object(host_install.time, "strftime", side_effect=("failed", "retry")), \
                patch.object(host_install.os, "geteuid", return_value=0), \
                patch.object(host_install.os, "chown"):
            with self.assertRaisesRegex(RuntimeError, "preflight rejected"):
                host_install.install(release, pin)
            result = host_install.install(release, pin)
            self.assertEqual(result["result"], "INSTALLED")
            host_install.acl_restore(self.root / "backups/retry")
        for path, acl in before.items():
            self.assertEqual(host_install.command("/usr/bin/getfacl", "-p", str(path)), acl)
        backup = self.root / "backups/failed"
        self.assertTrue((backup / "unaccepted-package/independent_qa/release.sha256").is_file())
        self.assertTrue((backup / "unaccepted-output").is_dir())
        self.assertEqual((backup / "unaccepted-evidence/fixture/T-0002/qa-input.json").read_text(), "{}")
        self.assertTrue((self.root / "backups/retry/acl-single.txt").is_file())
        self.assertEqual((self.root / "qa-evidence/fixture/T-0002/qa-input.json").read_text(), "{}")
        self.assertTrue((self.root / "qa-output").is_dir())

    def test_stage_evidence_failure_preserves_partial_copy_and_allows_retry(self):
        release = self.root / "release"
        pin = host_release.build(SOURCE, release)
        (self.root / "opt").mkdir()
        protected = self.root / "protected"
        protected.mkdir()
        tree = self.root / "repo"
        tree.mkdir()
        source_file = tree / "source.py"
        source_file.write_text("pass\n")
        other = self.root / "other-project"
        other.mkdir()
        required = self.root / "source.json"
        required.write_text("{}")
        missing = self.root / "missing.json"
        before = {path: host_install.command("/usr/bin/getfacl", "-p", str(path))
                  for path in (protected, tree, source_file, other)}
        real_stage = host_install.stage_evidence
        attempts = 0

        def disposable_stage(target):
            nonlocal attempts
            attempts += 1
            files = ((required, "fixture/T-0002/qa-input.json"),)
            if attempts == 1:
                files += ((missing, "fixture/T-0002/missing.json"),)
            return real_stage(target, files, {}, require_root=False)

        with patch.object(host_install, "INSTALL", self.root / "opt/install"), \
                patch.object(host_install, "OUTPUT", self.root / "qa-output"), \
                patch.object(host_install, "EVIDENCE", self.root / "qa-evidence"), \
                patch.object(host_install, "BACKUPS", self.root / "backups"), \
                patch.object(host_install, "TRAVERSE", (protected,)), \
                patch.object(host_install, "TREES", (tree,)), \
                patch.object(host_install, "QA_DENY", (other,)), \
                patch.object(host_install, "EXACT_READ", ()), \
                patch.object(host_install, "trusted_release"), \
                patch.object(host_install, "observe_access", return_value={"schema": "fixture"}), \
                patch.object(host_install, "stage_evidence", side_effect=disposable_stage), \
                patch.object(host_install, "administrator", return_value={"result": "PASS"}), \
                patch.object(host_install.time, "strftime", side_effect=("failed-stage", "retry-stage")), \
                patch.object(host_install.os, "geteuid", return_value=0), \
                patch.object(host_install.os, "chown"):
            with self.assertRaises(FileNotFoundError):
                host_install.install(release, pin)
            failed = self.root / "backups/failed-stage"
            self.assertTrue((failed / "unaccepted-package/independent_qa/release.sha256").is_file())
            self.assertEqual((failed / "unaccepted-evidence/fixture/T-0002/qa-input.json").read_text(), "{}")
            self.assertFalse((failed / "unaccepted-output").exists())
            self.assertFalse((self.root / "qa-evidence").exists())
            self.assertFalse((self.root / "qa-output").exists())
            for path, acl in before.items():
                self.assertEqual(host_install.command("/usr/bin/getfacl", "-p", str(path)), acl)
            result = host_install.install(release, pin)
            self.assertEqual(result["result"], "INSTALLED")
            host_install.acl_restore(self.root / "backups/retry-stage")
        self.assertEqual(attempts, 2)
        self.assertEqual((self.root / "qa-evidence/fixture/T-0002/qa-input.json").read_text(), "{}")
        for path, acl in before.items():
            self.assertEqual(host_install.command("/usr/bin/getfacl", "-p", str(path)), acl)

    def test_t0002_handoff_copy_passes_existing_evidence_verifier(self):
        target = self.root / "qa-evidence"
        host_install.stage_evidence(target, require_root=False)
        context = verify_qa_input(target / "dev-v1-accept/T-0002/qa-input.json",
                                  target / "dev-v1-accept/T-0002", target / "registry/projects.yaml",
                                  target / "gateway", target / "grants")
        self.assertEqual(context["revision"], "89ba188f8a2f801d433a30c9c21363efb3e1043d")

    def test_staged_t0002_acceptance_verifier(self):
        output = SOURCE / "staging-release"
        if not (output / "dev-v1-accept/T-0002/qa-report.json").is_file():
            self.skipTest("host staged T-0002 artifact unavailable")
        self.assertEqual(host_acceptance.inspect(SOURCE.parent, output, evidence_root=None)["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
