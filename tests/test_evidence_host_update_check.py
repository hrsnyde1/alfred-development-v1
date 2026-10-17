import hashlib
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from developer_v1.owner_grants import PERMISSIONS


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "live-acceptance" / "verify_evidence_host_update.py"
SPEC = importlib.util.spec_from_file_location("verify_evidence_host_update", SCRIPT)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class EvidenceHostUpdateCheck(unittest.TestCase):
    def test_operator_command_is_pinned_and_precedes_activation(self):
        procedure = (ROOT / "developer_v1" / "HOST_ACCEPTANCE.md").read_text()
        digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        self.assertIn(digest, procedure)
        update = procedure[procedure.index("## Approval-evidence update"):]
        activation = update.index('sudo mv -T "$DEV_BACKUP/active" "$DEV_ROOT/active"')
        acceptance = update.index('"$DEV_UPDATE/verify_evidence_host_update.py" --cto-sha256')
        self.assertLess(acceptance, activation)

    def test_updated_intake_imports_and_isolated_synthetic_grant(self):
        CHECK.import_installed_intake(ROOT / "developer_v1" / "trusted_intake_development.py")
        CHECK.synthetic_evidence()

    def test_historical_grant_is_rejected_for_missing_evidence(self):
        with tempfile.TemporaryDirectory(prefix="alfred-historical-check-") as temporary:
            root = Path(temporary)
            expected = {"schema": "alfred.development-grant/1", "project": "dev-v1-accept",
                        "task_id": "T-0002", "spec_sha256": "a" * 64,
                        "plan_sha256": "b" * 64, "repository": str(root / "repo"),
                        "worktree_root": str(root / "worktrees"), "scope": ["calculator.py"],
                        "specialists": ["backend"]}
            reference = "1" * 32
            grant = {**expected, "reference": reference, "issuer": "trusted_owner_authority",
                     "state": "approved", "source": "photon_native_owner_reply",
                     "environment": "staging", "permissions": sorted(PERMISSIONS),
                     "expires_at": time.time() + 300}
            path = root / f"grant-{reference}.json"
            path.write_text(json.dumps(grant))
            path.chmod(0o600)
            CHECK.historical_rejected(root, expected, root / "unused", environment="staging")
            (root / f"challenge-{reference}.json").write_text("{}")
            with self.assertRaises(CHECK.AcceptanceFailed):
                CHECK.historical_rejected(root, expected, root / "unused", environment="staging")

    def test_services_gateway_and_cto_must_match_baseline(self):
        with tempfile.TemporaryDirectory(prefix="alfred-service-check-") as temporary:
            cto = Path(temporary) / "cto.py"
            cto.write_text("unchanged")
            gateway = b"ActiveState=inactive\nResult=success\n\nActiveState=inactive\nResult=success\n"
            cto_sha = hashlib.sha256(cto.read_bytes()).hexdigest()
            gateway_sha = hashlib.sha256(gateway).hexdigest()
            with (patch.object(CHECK, "CTO", cto),
                  patch.object(CHECK.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as active,
                  patch.object(CHECK.subprocess, "check_output", return_value=gateway)):
                CHECK.services_and_code_unchanged(cto_sha, gateway_sha)
                self.assertEqual(active.call_count, 3)
                with self.assertRaises(CHECK.AcceptanceFailed):
                    CHECK.services_and_code_unchanged("0" * 64, gateway_sha)
                with self.assertRaises(CHECK.AcceptanceFailed):
                    CHECK.services_and_code_unchanged(cto_sha, "0" * 64)
            with (patch.object(CHECK, "CTO", cto),
                  patch.object(CHECK.subprocess, "run", return_value=SimpleNamespace(returncode=1)),
                  patch.object(CHECK.subprocess, "check_output", return_value=gateway)):
                with self.assertRaises(CHECK.AcceptanceFailed):
                    CHECK.services_and_code_unchanged(cto_sha, gateway_sha)


if __name__ == "__main__":
    unittest.main()
