"""The team-snapshot post-install checker, run against a simulated host in tmp_path.

Nothing here reads or changes the real /opt, /usr/local or /var/lib trees: every
root is passed explicitly and systemctl is a fake script."""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "live-acceptance" / "verify_team_snapshot_host_update.py"
GATEWAY_OUTPUT = "ActiveState=active\nResult=success\n"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def host(tmp_path):
    developer = tmp_path / "opt"
    shutil.copytree(ROOT / "developer_v1", developer / "developer_v1",
                    ignore=shutil.ignore_patterns("__pycache__", "HOST_ACCEPTANCE.md"))
    fresh = tmp_path / "fresh"
    for package in ("fresh_v1", "v1_cto"):
        shutil.copytree(ROOT / package, fresh / package,
                        ignore=shutil.ignore_patterns("__pycache__", "systemd", "tests"))
    cto = tmp_path / "cto.py"
    cto.write_text("# gateway cto\n")
    cto_sha256 = digest(cto.read_bytes())
    systemctl = tmp_path / "systemctl"
    systemctl.write_text("#!/bin/sh\n"
                         f"if [ \"$1\" = show ]; then printf '{GATEWAY_OUTPUT}'; exit 0; fi\n"
                         "echo active\n")
    systemctl.chmod(0o755)
    return {"developer": developer, "fresh": fresh, "cto": cto, "systemctl": systemctl,
            "team": tmp_path / "state" / "team", "cto_sha256": cto_sha256}


def run(host, *extra):
    args = [sys.executable, "-B", str(CHECKER),
            "--developer-root", str(host["developer"]), "--fresh-root", str(host["fresh"]),
            "--team-root", str(host["team"]), "--cto", str(host["cto"]),
            "--systemctl", str(host["systemctl"]),
            "--cto-sha256", host["cto_sha256"],
            "--installed-cto-sha256", digest((host["fresh"] / "v1_cto/cto.py").read_bytes()),
            "--gateway-sha256", digest(GATEWAY_OUTPUT.encode()), *extra]
    env = {"PATH": "/usr/bin:/bin",
           "PYTHONPATH": f"{host['developer']}:{host['fresh']}:/home/alfred/Git/alfred/src"}
    return subprocess.run(args, capture_output=True, text=True, env=env, timeout=60)


def test_pinned_manifest_is_the_released_one():
    source = CHECKER.read_text()
    assert digest((ROOT / "developer_v1/release.sha256").read_bytes()) in source


def test_updated_host_passes(host):
    result = run(host)
    assert result.stdout.strip() == "PASS: team snapshot update verified", result.stdout
    assert result.returncode == 0


@pytest.mark.parametrize("break_it,reason", [
    (lambda h: (h["developer"] / "developer_v1/team_snapshot.py").write_text("# old\n"),
     "installed file digest developer_v1/team_snapshot.py"),
    (lambda h: (h["developer"] / "developer_v1/stray.py").write_text(""),
     "unlisted installed files"),
    (lambda h: h["team"].mkdir(parents=True), "host team snapshot directory already exists"),
    (lambda h: (h["developer"] / "active").write_text("enabled\n"), "activation marker present"),
    (lambda h: h["cto"].write_text("# changed\n"), "CTO source changed"),
])
def test_any_mismatch_fails_closed(host, break_it, reason):
    break_it(host)
    result = run(host)
    assert result.returncode == 1 and result.stdout.strip() == "FAIL: " + reason


def test_wrong_manifest_pin_fails(host):
    result = run(host, "--manifest-sha256", "0" * 64)
    assert result.stdout.strip() == "FAIL: installed release manifest digest"


def test_a_service_down_fails(host):
    host["systemctl"].write_text("#!/bin/sh\n"
                                 f"if [ \"$1\" = show ]; then printf '{GATEWAY_OUTPUT}'; exit 0; fi\n"
                                 "echo inactive\n")
    assert run(host).stdout.strip() == "FAIL: alfred-development-intake.service is not active"


def test_update_pins_match_the_checkout():
    pins = ROOT / "live-acceptance" / "team-snapshot-update"
    staged = [line.split("  ") for line in (pins / "staged.sha256").read_text().splitlines()]
    for sha, relative in staged:
        assert digest((ROOT / relative).read_bytes()) == sha, relative
    after = [line.split("  ") for line in (pins / "installed-after.sha256").read_text().splitlines()]
    before = [line.split("  ") for line in (pins / "installed-before.sha256").read_text().splitlines()]
    # Exactly the files #25 changed, plus the new module; nothing else is replaced.
    assert {p for _, p in after} == {p for _, p in before} | {
        "opt/alfred-developer-v1/developer_v1/team_snapshot.py"}
    assert [sha for sha, _ in after] == [sha for sha, p in staged if not p.startswith("live-")]
    text = (ROOT / "developer_v1" / "HOST_ACCEPTANCE.md").read_text()
    for name in ("staged.sha256", "installed-before.sha256", "installed-after.sha256"):
        assert digest((pins / name).read_bytes()) in text, name
    assert digest(CHECKER.read_bytes()) in text
