"""Run the documented release transactions only inside disposable fixtures."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "draft_pr_publisher"
INSTALLED = Path("/opt/alfred-draft-pr-publisher-v1")
OLD_WORKER = "88eace873994d080000ed0ef12d25107e63223b3fbcf1253e22450e25fde7f76"
OLD_MANIFEST = "53f5a14a58ccaa5d8b9b85242f913a34866a19f31ee7de36f068c682a012fcda"
NEW_WORKER = "051ed86f1fe07260fd663636b665bbef5ddab6c2b8852ecc0a777264ee944ec3"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UpgradeProcedureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="publisher-upgrade-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.live = self.root / "installed"
        self.stage = self.root / "handoff"
        self.backup = self.root / "rollback"
        self.live.mkdir()
        self.stage.mkdir()
        files = [line.split("  ", 1)[1] for line in (PACKAGE / "release.sha256").read_text().splitlines()]
        for name in files + ["release.sha256"]:
            target = self.live / name
            target.parent.mkdir(parents=True, exist_ok=True)
            origin = INSTALLED if name in ("worker.py", "release.sha256") else PACKAGE
            shutil.copyfile(origin / name, target)
        self.assertEqual(digest(self.live / "worker.py"), OLD_WORKER)
        self.assertEqual(digest(self.live / "release.sha256"), OLD_MANIFEST)
        for name in ("worker.py", "release.sha256"):
            shutil.copyfile(PACKAGE / name, self.stage / name)
        # These siblings model retained protected records. Only fixture files
        # are created; real evidence and credentials are never opened.
        for name in ("publication-result.json", "publication-plan.json", "owner-authorization.json",
                     "developer-grant.json", "qa-report.json", "review-report.json", "github-token"):
            path = self.root / "protected-evidence" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('{"fixture": "retained", "status": "ERROR"}\n')
            path.chmod(0o400)
        self.original_evidence = self.snapshot()

    def snapshot(self):
        return {p.name: (p.read_bytes(), p.stat().st_mode) for p in
                (self.root / "protected-evidence").iterdir()}

    def script(self, marker):
        document = (PACKAGE / "UPGRADE_V1_1_0.md").read_text()
        body = document.split("<<'" + marker + "'\n", 1)[1].split("\n" + marker + "\n", 1)[0]
        # The exact documented body runs with only fixture paths and current
        # fixture ownership. Privileged host operations are never invoked.
        body = body.replace("/opt/alfred-draft-pr-publisher-v1", str(self.live))
        body = body.replace("/root/alfred-publisher-v1.1.0-handoff", str(self.stage))
        body = body.replace("/root/alfred-publisher-v1.0-rollback", str(self.backup))
        body = body.replace('test "$(id -u)" = 0\n', "")
        body = body.replace(" -o root -g root", "")
        self.assertNotIn("/opt/", body)
        self.assertNotIn("/root/", body)
        return body

    def run_script(self, body):
        return subprocess.run(["/bin/bash"], input=body, text=True,
                              capture_output=True, timeout=20)

    def test_upgrade_and_manual_rollback_preserve_evidence(self):
        installed = self.run_script(self.script("INSTALL_PUBLISHER_V1_1_0"))
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.assertEqual(digest(self.live / "worker.py"), NEW_WORKER)
        self.assertEqual(self.snapshot(), self.original_evidence)
        rolled_back = self.run_script(self.script("ROLLBACK_PUBLISHER_V1_1_0"))
        self.assertEqual(rolled_back.returncode, 0, rolled_back.stdout + rolled_back.stderr)
        self.assertEqual(digest(self.live / "worker.py"), OLD_WORKER)
        self.assertEqual(digest(self.live / "release.sha256"), OLD_MANIFEST)
        self.assertEqual(self.snapshot(), self.original_evidence)
        self.assertTrue((self.backup / "worker.py").exists())

    def test_failure_between_replacements_restores_original_release(self):
        body = self.script("INSTALL_PUBLISHER_V1_1_0")
        first_move = '/bin/mv -f -- "$live/.worker.v1.1.0" "$live/worker.py"'
        self.assertEqual(body.count(first_move), 1)
        result = self.run_script(body.replace(first_move, first_move + "\n/usr/bin/false"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("original Publisher V1 restored", result.stderr)
        self.assertEqual(digest(self.live / "worker.py"), OLD_WORKER)
        self.assertEqual(digest(self.live / "release.sha256"), OLD_MANIFEST)
        self.assertEqual(self.snapshot(), self.original_evidence)

    def test_bad_handoff_is_rejected_before_installation(self):
        (self.stage / "worker.py").write_text("tampered fixture\n")
        result = self.run_script(self.script("INSTALL_PUBLISHER_V1_1_0"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(digest(self.live / "worker.py"), OLD_WORKER)
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.snapshot(), self.original_evidence)


if __name__ == "__main__":
    unittest.main()
