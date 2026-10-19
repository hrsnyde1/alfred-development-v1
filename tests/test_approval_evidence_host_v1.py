"""Pin the small Codex-path host delta without touching host state."""

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from developer_v1.host_install import verified_release


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "developer_v1"
HISTORICAL = ROOT / "tests/fixtures/developer-v1-publication/developer_v1"
INSTALLED = Path("/opt/alfred-developer-v1/developer_v1")
INTAKE = Path("/usr/local/lib/alfred-v1.1/trusted_intake.py")
STAGED_MANIFEST = "32f6b3c717b044a9e516314984dea314c9d448b4d1c59b9bc1407932e269f568"
INSTALLED_EVIDENCE_MANIFEST = "586f92ef61d6cc328c4c5202e5d86dd0d3e47bfa3e42a1e1e08750fef721576c"
NEW_INTAKE = "01c8911332d2314ccbe8db187a4a6d3ba63ceb9d2475c2ad252af7c9a1855ef0"
OLD_INTAKE = "dbc1ecbdf69d7772557aa4181e46301ea5db32a3b0c701512c5c5aacb466cf3f"
CHANGED = {"trusted_intake_development.py", "host_install.py", "stage_publication.py",
           "release.sha256", "publication_approval.py", "install_config.py", "owner_grants.py"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ApprovalEvidenceHostDelta(unittest.TestCase):
    def test_staged_release_and_operator_pins(self):
        with tempfile.TemporaryDirectory(prefix="alfred-evidence-release-") as temporary:
            clean = Path(temporary)
            shutil.copytree(HISTORICAL, clean / "developer_v1",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            verified_release(clean, STAGED_MANIFEST)
        self.assertEqual(digest(HISTORICAL / "release.sha256"), STAGED_MANIFEST)
        self.assertEqual(digest(HISTORICAL / "trusted_intake_development.py"), NEW_INTAKE)
        procedure = (ROOT / "PUBLICATION_APPROVAL_HOST.md").read_text()
        for expected in (STAGED_MANIFEST, INSTALLED_EVIDENCE_MANIFEST, NEW_INTAKE):
            self.assertIn(expected, procedure)

    def test_fresh_delta_is_bounded_against_pinned_historical_release(self):
        different = {name.name for name in PACKAGE.iterdir()
                     if name.is_file() and name.name != "HOST_ACCEPTANCE.md"
                     and (not (HISTORICAL / name.name).exists()
                          or (HISTORICAL / name.name).read_bytes() != name.read_bytes())}
        # real_worker.py: handoff.6 accepts Codex progress notes before the final answer.
        # team_skills.py: handoff.13 loads the owner-approved team skills for specialists.
        # execution.py: handoff.15's claim scan reads only claim records.
        # agent_profiles.*: handoff.21 gives each agent its owner-reviewed identity.
        # team_snapshot.py, router.py, specialists.json, README.md and the example
        # models: owner-approved Alfred OS team snapshots and builder, qa, code_reviewer.
        # undo_approval.py: handoff.31's owner "undo" reply to a merged change's text.
        self.assertEqual(different, {"team_snapshot.py", "router.py", "specialists.json",
                                    "README.md", "models.codex-verified.example.json",
                                    "pipeline.py", "owner_grants.py", "run_task.py", "publication_approval.py",
                                    "trusted_intake_development.py", "stage_approval.py", "release.sha256",
                                    "real_worker.py", "team_skills.py", "execution.py",
                                    "agent_profiles.py", "agent_profiles.json",
                                    "undo_approval.py",
                                    # Alfred OS passkey approvals.
                                    "owner_passkey.py", "owner_approval.py",
                                    "enroll_owner_passkey.py", "stage_publication.py",
                                    "alfred-development-intake-owner-approval.conf",
                                    # handoff.34 Repo Intelligence.
                                    "repo_intelligence.py"})
        self.assertNotEqual(HISTORICAL.joinpath("trusted_intake_development.py").read_bytes(),
                            PACKAGE.joinpath("trusted_intake_development.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
