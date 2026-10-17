"""Protected-copy integrity checks for the staged release."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "draft_pr_publisher"
FILES = ("__init__.py", "askpass.py", "config.json", "worker.py", "README.md",
         "schemas/owner-authorization.schema.json", "schemas/publication-plan.schema.json",
         "schemas/publication-result.schema.json")
# Existing verified Publisher V1.1 release; V1.0's pin remains in its archive.
MANIFEST_SHA = "926c925fedcaad40ef9240c2558ff9d10f241329f290a99e212a449f1c66442e"


class ReleaseTests(unittest.TestCase):
    def copy_release(self, target: Path):
        for name in FILES + ("release.sha256",):
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)

    def test_manifest_and_protected_copy(self):
        digest = subprocess.check_output(["/usr/bin/sha256sum", str(ROOT / "release.sha256")]).decode().split()[0]
        self.assertEqual(digest, MANIFEST_SHA)
        self.assertEqual((ROOT / "askpass.py").stat().st_mode & 0o111, 0o111)
        with tempfile.TemporaryDirectory(prefix="publisher-release-") as name:
            target = Path(name)
            self.copy_release(target)
            proc = subprocess.run(["/usr/bin/sha256sum", "-c", "release.sha256"],
                                  cwd=target, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            self.assertEqual(set(FILES + ("release.sha256",)),
                             {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()})

    def test_tampered_protected_copy_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="publisher-release-") as name:
            target = Path(name)
            self.copy_release(target)
            (target / "worker.py").write_bytes((target / "worker.py").read_bytes() + b"# changed\n")
            proc = subprocess.run(["/usr/bin/sha256sum", "-c", "release.sha256"],
                                  cwd=target, capture_output=True)
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
