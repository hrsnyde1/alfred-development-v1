"""handoff.29: one-yes flow files, only on disposable /tmp fixture roots."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from development_handoff29 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
# main before handoff.29: exactly the installed base (checked against BASE below).
BASE_COMMIT = "12fdcd0"
SOURCES = {
    "/etc/alfred-development/delegation.json": "development_handoff12/delegation.json",
    "/usr/local/lib/alfred-v1.1/trusted_intake.py": "developer_v1/trusted_intake_development.py",
}


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def base_bytes(name):
    if name in SOURCES and SOURCES[name].startswith("development_handoff12"):
        return (ROOT / SOURCES[name]).read_bytes()
    source = SOURCES.get(name) or transaction.DESTINATIONS.get(name) or (
        "fresh_v1/" + Path(name).name if name.startswith(transaction.LIBRARY)
        else "developer_v1/" + Path(name).name)
    for commit in (BASE_COMMIT,):
        out = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{source}"],
                             capture_output=True, check=False)
        if out.returncode == 0:
            return out.stdout
    raise AssertionError("no base for " + name)


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name, sha in {**transaction.BASE, **transaction.DEPENDENCIES}.items():
        raw = base_bytes(name)
        if upgrade.digest(raw) != sha:
            pytest.skip("base bytes for " + name + " are not in this checkout")
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


def test_install_replaces_every_file_and_rollback_restores_them(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n in transaction.BASE}
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD"
    for name, source in transaction.DESTINATIONS.items():
        assert upgrade.target(root, name).read_bytes() == (ROOT / source).read_bytes()
    transaction.rollback(root, backup)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw


def test_drift_refuses_before_any_change(fixture):
    root, release, pin, backup = fixture
    policy = upgrade.target(root, "/etc/alfred-development/delegation.json")
    policy.write_bytes(policy.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_the_new_policy_changes_only_publication_approval():
    old = json.loads((ROOT / "development_handoff12/delegation.json").read_text())
    new = json.loads((ROOT / "development_handoff29/delegation.json").read_text())
    assert new == {**old, "publication_approval": "delegated"}


def test_both_intake_copies_get_the_same_code():
    sources = {transaction.DESTINATIONS[n] for n in (
        transaction.DEVELOPER + "trusted_intake_development.py",
        "/usr/local/lib/alfred-v1.1/trusted_intake.py")}
    assert sources == {"developer_v1/trusted_intake_development.py"}
