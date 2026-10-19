"""handoff.34: Repo Intelligence, only on disposable /tmp fixture roots."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from development_handoff34 import install_patch as transaction
from fresh_v1 import upgrade

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "/home/alfred/Alfred/gateway/PAUSE"
# main after handoff.33: exactly the installed bytes of every file below, checked
# against BASE and DEPENDENCIES (read from the live host before the build).
BASE_COMMIT = "027971b"
PACKAGES = ((transaction.LIBRARY, "fresh_v1/"), (transaction.DEVELOPER, "developer_v1/"),
            ("/usr/local/lib/alfred-fresh-v1/v1_cto/", "v1_cto/"))
NEW = [n for n, sha in transaction.BASE.items() if sha is None]


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def base_bytes(name):
    source = next(package + name.removeprefix(prefix) for prefix, package in PACKAGES
                  if name.startswith(prefix))
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{source}"],
                          capture_output=True, check=True).stdout


@pytest.fixture
def fixture(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    for name, sha in {**transaction.BASE, **transaction.DEPENDENCIES}.items():
        if sha is None:
            continue
        raw = base_bytes(name)
        assert upgrade.digest(raw) == sha, name
        write(upgrade.target(root, name), raw)
    for name in {**transaction.BASE, **transaction.DEPENDENCIES}:
        directory = upgrade.target(root, name).parent
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755)
    write(upgrade.target(root, PAUSE), b"")
    write(upgrade.target(root, upgrade.MARKER), b"ACTIVE\n")
    lines = []
    for source in sorted(set(transaction.DESTINATIONS.values())):
        write(release / source, (ROOT / source).read_bytes())
        lines.append(hashlib.sha256((ROOT / source).read_bytes()).hexdigest() + "  " + source)
    raw = ("\n".join(lines) + "\n").encode()
    write(release / "MANIFEST.sha256", raw)
    return root, release, upgrade.digest(raw), tmp_path / "backup"


def test_install_replaces_three_files_adds_five_and_rollback_restores_all(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n, sha in transaction.BASE.items() if sha}
    modes = {n: upgrade.target(root, n).stat().st_mode & 0o777 for n in before}
    result = transaction.install(release, pin, root, backup)
    assert result == {"status": "INSTALLED_HELD", "service_action": "systemctl daemon-reload",
                      "next": "systemctl enable --now alfred-repo-intelligence.timer",
                      "retry_authorized": False}
    for name, source in transaction.DESTINATIONS.items():
        target = upgrade.target(root, name)
        assert target.read_bytes() == (ROOT / source).read_bytes()
        assert target.stat().st_mode & 0o777 == modes.get(name, 0o644)
    transaction.rollback(root, backup)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw
    assert not any(upgrade.target(root, n).exists() for n in NEW)


def test_it_installs_only_on_the_live_handoff_33_bytes(fixture):
    root, release, pin, backup = fixture
    # role.py as installed before handoff.31's team snapshot.
    path = upgrade.target(root, transaction.LIBRARY + "role.py")
    path.write_bytes(path.read_bytes().replace(b"team_snapshot", b"team_snap"))
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_drift_in_a_dependency_refuses_before_any_change(fixture):
    root, release, pin, backup = fixture
    path = upgrade.target(root, transaction.DEVELOPER + "team_snapshot.py")
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="installed contract mismatch"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()
    assert not upgrade.target(root, transaction.CONFIG).exists()


def test_an_existing_new_file_or_missing_pause_refuses(fixture):
    root, release, pin, backup = fixture
    timer = upgrade.target(root, transaction.UNITS + "alfred-repo-intelligence.timer")
    timer.write_text("[Timer]\n")
    with pytest.raises(ValueError, match="new file already exists"):
        transaction.install(release, pin, root, backup)
    timer.unlink()
    upgrade.target(root, PAUSE).unlink()
    with pytest.raises(ValueError, match="PAUSE"):
        transaction.install(release, pin, root, backup)
    assert not backup.exists()


def test_a_fault_midway_restores_every_file(fixture):
    root, release, pin, backup = fixture
    before = {n: upgrade.target(root, n).read_bytes() for n, sha in transaction.BASE.items() if sha}
    with pytest.raises(OSError, match="disposable fixture fault"):
        transaction.install(release, pin, root, backup, fail_after=5)
    for name, raw in before.items():
        assert upgrade.target(root, name).read_bytes() == raw
    assert not any(upgrade.target(root, n).exists() for n in NEW)


def test_the_units_run_the_refresh_as_alfred_in_a_sandbox():
    service = (ROOT / "development_handoff34/alfred-repo-intelligence.service").read_text()
    assert "User=alfred\n" in service and "Type=oneshot\n" in service
    assert "ExecStart=/usr/bin/python3 -B -s -E -m developer_v1.repo_intelligence refresh\n" in service
    assert "WorkingDirectory=/opt/alfred-developer-v1\n" in service
    assert "StateDirectory=alfred-repo-intelligence\n" in service
    for line in ("NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=read-only", "PrivateTmp=yes"):
        assert line + "\n" in service
    timer = (ROOT / "development_handoff34/alfred-repo-intelligence.timer").read_text()
    assert "OnUnitInactiveSec=10min\n" in timer and "WantedBy=timers.target\n" in timer


def test_the_store_path_matches_the_service_state_directory():
    from developer_v1 import repo_intelligence
    assert repo_intelligence.STORE == Path("/var/lib/alfred-repo-intelligence")
    assert repo_intelligence.CONFIG == Path(transaction.CONFIG)


def test_installed_after_pins_are_the_release_files():
    lines = (ROOT / "development_handoff34/installed-after.sha256").read_text().splitlines()
    pins = dict(reversed(line.split("  ", 1)) for line in lines)
    assert set(pins) == set(transaction.DESTINATIONS)
    release = ROOT / "dist/alfred-fresh-v1-1.0.1-development-handoff.34"
    for name, source in transaction.DESTINATIONS.items():
        assert pins[name] == hashlib.sha256((release / source).read_bytes()).hexdigest()


def test_installed_before_pins_are_the_base():
    assert json.loads((ROOT / "development_handoff34/installed-sha256.json").read_text()) \
        == transaction.BASE
