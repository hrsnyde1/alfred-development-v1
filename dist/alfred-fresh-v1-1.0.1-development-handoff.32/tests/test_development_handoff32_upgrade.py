"""handoff.32: per-specialist team skills files, only on disposable /tmp fixture roots."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from development_handoff32 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
# main after handoff.31 and the passkey approvals: exactly the installed bytes.
BASE_COMMIT = "ace129b"
SOURCES = {
    transaction.LIBRARY + "upgrade.py": "fresh_v1/upgrade.py",
    transaction.LIBRARY + "protected.py": "fresh_v1/protected.py",
    transaction.LIBRARY + "role.py": "fresh_v1/role.py",
    **{transaction.DEVELOPER + name: "developer_v1/" + name for name in (
        "router.py", "real_worker.py", "team_snapshot.py", "agent_profiles.py",
        "execution.py", "gateway_adapter.py", "owner_grants.py")},
}
RELEASE = ROOT / "dist/alfred-fresh-v1-1.0.1-development-handoff.32"


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def base_bytes(name):
    source = SOURCES.get(name) or transaction.DESTINATIONS[name]
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{source}"],
                          capture_output=True, check=True).stdout


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name, sha in {**transaction.BASE, **transaction.DEPENDENCIES}.items():
        raw = base_bytes(name)
        assert upgrade.digest(raw) == sha, name
        write(upgrade.target(root, name), raw)
    for name in {**transaction.BASE, **transaction.DEPENDENCIES}:
        upgrade.target(root, name).parent.chmod(0o755)
    write(upgrade.target(root, PAUSE), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    lines = []
    for source in sorted(set(transaction.DESTINATIONS.values())):
        write(release / source, (ROOT / source).read_bytes())
        lines.append(hashlib.sha256((ROOT / source).read_bytes()).hexdigest() + "  " + source)
    raw = ("\n".join(lines) + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def test_install_replaces_both_files_and_rollback_restores_them(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD"
    assert result["service_action"] == "none"
    for name, source in transaction.DESTINATIONS.items():
        assert upgrade.target(root, name).read_bytes() == (ROOT / source).read_bytes()
    assert transaction.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_a_fault_mid_install_rolls_back(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    with pytest.raises(OSError, match="disposable fixture fault"):
        transaction.install(release, pin, root, backup, fail_after=1)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_drift_refuses_before_any_change(fixture):
    root, release, pin, backup = fixture
    for name in (transaction.DEVELOPER + "pipeline.py", transaction.DEVELOPER + "router.py"):
        path = upgrade.target(root, name)
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        with pytest.raises(ValueError, match="installed contract mismatch"):
            transaction.install(release, pin, root, backup)
        assert not backup.exists()
        path.write_bytes(original)


def test_it_requires_pause(fixture):
    root, release, pin, backup = fixture
    upgrade.target(root, PAUSE).unlink()
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_the_plan_record_and_its_schema_are_unchanged():
    # Only the split at development time is new; plans already approved stay valid.
    changed = subprocess.run(["git", "-C", str(ROOT), "diff", "--name-only", BASE_COMMIT, "--",
                              "v1_cto/plan.schema.json", "fresh_v1/role.py"],
                             capture_output=True, text=True, check=True).stdout
    assert changed == ""


def test_installed_after_pins_are_the_release_files():
    lines = (ROOT / "development_handoff32/installed-after.sha256").read_text().splitlines()
    pins = dict(reversed(line.split("  ", 1)) for line in lines)
    assert set(pins) == set(transaction.DESTINATIONS)
    source_root = RELEASE if RELEASE.is_dir() else ROOT
    for name, source in transaction.DESTINATIONS.items():
        assert pins[name] == hashlib.sha256((source_root / source).read_bytes()).hexdigest()


def test_installed_sha256_lists_the_base_pins():
    pins = json.loads((ROOT / "development_handoff32/installed-sha256.json").read_text())
    assert pins == transaction.BASE
