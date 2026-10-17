"""handoff.13 team-skills overlay: installation/rollback, only on disposable /tmp fixture roots."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from development_handoff13 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
# main after handoff.12; every BASE and DEPENDENCIES pin is a file of this commit.
BASE_COMMIT = "8e634d6"
SOURCES = {
    **transaction.DESTINATIONS,
    transaction.DROP_IN: "fresh_v1/systemd/alfred-development-evidence.conf",
    transaction.OPS: "ops/alfred_dev_ops.py",
    transaction.GATEWAY_BIN + "cto.py": "v1_cto/cto.py",
}
PRESERVED = (
    "/home/alfred/Alfred/gateway/PAUSE",
    "/etc/alfred-fresh-v1/policy.json",
    "/var/lib/alfred-development-grants/grant-ref.json",
    "/home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0009.json",
)


def source(name):
    if name in SOURCES:
        return SOURCES[name]
    for prefix, folder in ((transaction.DEVELOPER, "developer_v1/"),
                           (transaction.LIBRARY, "")):
        if name.startswith(prefix):
            return folder + name[len(prefix):]
    raise AssertionError(name)


def original(name, expected):
    raw = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{source(name)}"],
                         capture_output=True, check=False).stdout
    assert upgrade.digest(raw) == expected, "pinned baseline differs: " + name
    return raw


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name, sha in {**transaction.BASE, **transaction.DEPENDENCIES}.items():
        if sha is not None:
            write(upgrade.target(root, name), original(name, sha))
    for name in transaction.DESTINATIONS.values():
        write(release / name, (ROOT / name).read_bytes())
    raw = "".join(
        hashlib.sha256((release / n).read_bytes()).hexdigest() + "  " + n + "\n"
        for n in sorted(set(transaction.DESTINATIONS.values()))
    ).encode()
    write(release / "MANIFEST.sha256", raw)
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    # Installed library directories are root-owned 0755 on the host.
    upgrade.target(root, transaction.DEVELOPER).chmod(0o755)
    for name in PRESERVED:
        write(upgrade.target(root, name), b"PRESERVE: " + name.encode(), mode=0o600)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode)
            for p in root.rglob("*") if p.is_file()}


def test_install_writes_only_the_six_files(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    result = transaction.install(release, pin, root, backup)
    assert result["status"] == "INSTALLED_HELD" and result["service_action"] == "none"
    after = snapshot(root)
    changed = {k for k in set(after) | set(before) if before.get(k) != after.get(k)}
    assert changed == {name.lstrip("/") for name in transaction.DESTINATIONS}
    for name, relative in transaction.DESTINATIONS.items():
        assert upgrade.target(root, name).read_bytes() == (ROOT / relative).read_bytes()
        if transaction.BASE[name] is not None:
            assert after[name.lstrip("/")][1] == before[name.lstrip("/")][1]
    new = upgrade.target(root, transaction.DEVELOPER + "team_skills.py")
    assert new.stat().st_mode & 0o777 == 0o644
    index = json.loads((backup / "index.json").read_bytes())
    assert [e["sha256"] for e in index["files"]] == list(transaction.BASE.values())


def test_rollback_restores_the_handoff12_host_and_removes_the_new_file(fixture):
    root, release, pin, backup = fixture
    before = snapshot(root)
    transaction.install(release, pin, root, backup)
    assert transaction.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    assert snapshot(root) == before


@pytest.mark.parametrize("fault", [0, 2, 3, 5])
def test_fault_mid_install_rolls_back(fixture, fault):
    root, release, pin, backup = fixture
    before = snapshot(root)
    with pytest.raises(OSError):
        transaction.install(release, pin, root, backup, fail_after=fault)
    assert snapshot(root) == before


def test_drifted_host_is_refused(fixture):
    root, release, pin, backup = fixture
    router = upgrade.target(root, transaction.DEVELOPER + "router.py")
    router.write_bytes(router.read_bytes() + b"# drift\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_existing_team_skills_file_is_refused(fixture):
    root, release, pin, backup = fixture
    write(upgrade.target(root, transaction.DEVELOPER + "team_skills.py"), b"unexpected")
    with pytest.raises(ValueError, match="new file already exists"):
        transaction.install(release, pin, root, backup)


def test_requires_pause(fixture):
    root, release, pin, backup = fixture
    upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE").unlink()
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)


def test_release_pins_match_the_staged_files():
    pins = json.loads((ROOT / "development_handoff13/release.json").read_bytes())
    release = ROOT / "dist" / pins["name"]
    assert pins["restart"] == [] and pins["installer"] == "development_handoff13/install_patch.py"
    assert upgrade.digest((release / "MANIFEST.sha256").read_bytes()) == pins["manifest_sha256"]
    assert upgrade.verify(release, pins["manifest_sha256"])
    for name, relative in transaction.DESTINATIONS.items():
        assert (release / relative).read_bytes() == (ROOT / relative).read_bytes(), relative
    after = dict(line.split("  ")[::-1] for line in
                 (ROOT / "development_handoff13/installed-after.sha256").read_text().splitlines())
    assert after == {name: upgrade.digest((ROOT / relative).read_bytes())
                     for name, relative in transaction.DESTINATIONS.items()}
    archive = ROOT / "dist" / (pins["name"] + ".tar.gz")
    assert upgrade.digest(archive.read_bytes()) == pins["archive_sha256"]
    assert os.access(ROOT / pins["preflight"], os.R_OK)
