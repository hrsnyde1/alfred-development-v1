"""handoff.30: QA's worker replaced, on disposable /tmp fixture roots."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from development_handoff30 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
WORKER = transaction.QA + "worker.py"
POLICY = "/etc/alfred-development/delegation.json"
BASE_COMMIT = "12fdcd0"  # main before handoff.29; QA's worker unchanged since handoff.17


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    installed = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:independent_qa/worker.py"],
                               capture_output=True, check=True).stdout
    assert upgrade.digest(installed) == transaction.BASE[WORKER]
    write(upgrade.target(root, WORKER), installed)
    write(upgrade.target(root, POLICY), (ROOT / "development_handoff29/delegation.json").read_bytes())
    write(upgrade.target(root, transaction.LIBRARY + "upgrade.py"),
          (ROOT / "fresh_v1/upgrade.py").read_bytes())
    for name in (WORKER, POLICY, transaction.LIBRARY + "upgrade.py"):
        upgrade.target(root, name).parent.chmod(0o755)
    write(upgrade.target(root, PAUSE), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    source = transaction.DESTINATIONS[WORKER]
    write(release / source, (ROOT / source).read_bytes())
    raw = (hashlib.sha256((ROOT / source).read_bytes()).hexdigest() + "  " + source + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def test_install_replaces_the_qa_worker_and_rollback_restores_it(fixture):
    root, release, pin, backup = fixture
    before = upgrade.target(root, WORKER).read_bytes()
    assert transaction.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    assert upgrade.target(root, WORKER).read_bytes() == (ROOT / "independent_qa/worker.py").read_bytes()
    transaction.rollback(root, backup)
    assert upgrade.target(root, WORKER).read_bytes() == before


def test_it_needs_the_handoff_29_policy(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, POLICY), (ROOT / "development_handoff12/delegation.json").read_bytes())
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()
