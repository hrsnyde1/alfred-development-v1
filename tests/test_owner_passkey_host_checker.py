"""The passkey post-install checker, against a simulated host in tmp_path.

Every root is passed explicitly; systemctl is a fake script; the owner socket is a
real listener in this process with an ACL naming a stand-in Alfred OS UID."""

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "live-acceptance" / "verify_owner_passkey_host_update.py"
PINS = ROOT / "live-acceptance" / "passkey-approval-update"
GATEWAY_OUTPUT = "ActiveState=active\nResult=success\n"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def host(tmp_path):
    from developer_v1 import owner_approval
    from developer_v1 import trusted_intake_development as intake
    developer = tmp_path / "opt"
    shutil.copytree(ROOT / "developer_v1", developer / "developer_v1",
                    ignore=shutil.ignore_patterns("__pycache__", "HOST_ACCEPTANCE.md"))
    sockets = tmp_path / "run"
    sockets.mkdir(mode=0o700)
    (sockets / "intake.sock").touch()
    grants = tmp_path / "grants"
    grants.mkdir(mode=0o700)
    (grants / "grant-x.json").write_text("{}")
    service = owner_approval.OwnerApprovals(
        grants, development_issuer=None, publication_issuer=None,
        development_request=None, alfred_os_uid=os.geteuid() + 1, notice_sender=None,
        pin_path=None)
    intake.serve_owner_approvals(sockets / "owner-approval.sock", service, os.geteuid() + 1)
    if not (sockets / "owner-approval.sock").exists():
        pytest.skip("POSIX ACLs unavailable here")
    # The fixture's intake.sock is a plain file; the checker wants a socket.
    os.remove(sockets / "intake.sock")
    import socket as socketlib
    stand_in = socketlib.socket(socketlib.AF_UNIX)
    stand_in.bind(str(sockets / "intake.sock"))
    cto = tmp_path / "cto.py"
    cto.write_text("# cto\n")
    systemctl = tmp_path / "systemctl"
    systemctl.write_text("#!/bin/sh\n"
                         f"if [ \"$1\" = show ]; then printf '{GATEWAY_OUTPUT}'; exit 0; fi\n"
                         "echo active\n")
    systemctl.chmod(0o755)
    yield {"developer": developer, "sockets": sockets, "grants": grants, "cto": cto,
           "systemctl": systemctl, "cto_sha256": digest(cto.read_bytes()),
           "listing": digest("grant-x.json".encode())}
    stand_in.close()


def run(host, *extra):
    args = [sys.executable, "-B", str(CHECKER),
            "--developer-root", str(host["developer"]),
            "--intake", str(host["developer"] / "developer_v1/trusted_intake_development.py"),
            "--sockets", str(host["sockets"]), "--grants", str(host["grants"]),
            "--cto", str(host["cto"]), "--systemctl", str(host["systemctl"]),
            "--alfred-os-uid", str(os.geteuid() + 1),
            "--cto-sha256", host["cto_sha256"], "--grant-store-sha256", host["listing"],
            "--gateway-sha256", digest(GATEWAY_OUTPUT.encode()), *extra]
    env = {"PATH": "/usr/bin:/bin",
           "PYTHONPATH": f"{host['developer']}:/home/alfred/Git/alfred/src"}
    return subprocess.run(args, capture_output=True, text=True, env=env, timeout=120)


def test_updated_host_passes(host):
    result = run(host)
    assert result.stdout.strip() == "PASS: passkey approvals verified", result.stdout + result.stderr


@pytest.mark.parametrize("break_it,reason", [
    (lambda h: (h["developer"] / "developer_v1/owner_passkey.py").write_text("# old\n"),
     "installed file digest developer_v1/owner_passkey.py"),
    (lambda h: (h["grants"] / "grant-y.json").write_text("{}"),
     "the real grant store changed during the update"),
    (lambda h: (h["developer"] / "active").write_text("enabled\n"), "activation marker present"),
    (lambda h: h["cto"].write_text("# changed\n"), "CTO source changed"),
    (lambda h: os.remove(h["sockets"] / "owner-approval.sock"),
     "owner-approval.sock is not listening"),
])
def test_any_mismatch_fails_closed(host, break_it, reason):
    break_it(host)
    result = run(host)
    assert result.returncode == 1 and result.stdout.strip() == "FAIL: " + reason


def test_wrong_alfred_os_uid_in_the_acl_fails(host):
    result = run(host, "--alfred-os-uid", str(os.geteuid() + 2))
    assert result.stdout.strip() == "FAIL: owner-approval.sock ACL is not exactly its owner and alfredos"


def test_pinned_manifest_is_the_released_one():
    assert digest((ROOT / "developer_v1/release.sha256").read_bytes()) in CHECKER.read_text()


def test_update_pins_match_the_checkout_and_the_procedure():
    staged = [line.split("  ") for line in (PINS / "staged.sha256").read_text().splitlines()]
    for sha, relative in staged:
        assert digest((ROOT / relative).read_bytes()) == sha, relative
    text = (ROOT / "developer_v1" / "HOST_ACCEPTANCE.md").read_text()
    for name in ("staged.sha256", "installed-before.sha256", "installed-after.sha256"):
        assert digest((PINS / name).read_bytes()) in text, name
    assert digest(CHECKER.read_bytes()) in text
