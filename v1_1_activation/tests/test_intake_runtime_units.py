"""Offline checks for the staged Intake ACL and existing Gateway timer."""

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

UNITS = Path(__file__).resolve().parents[1] / "units"


def test_runtime_directory_acl_has_effective_traverse_after_each_start(tmp_path):
    unit = (UNITS / "alfred-development-intake.service").read_text()
    assert "RuntimeDirectoryMode=0700" in unit
    command = next(line.removeprefix("ExecStartPre=") for line in unit.splitlines()
                   if "setfacl -m u:alfredmsg" in line)
    assert "m::--x" in command
    for _ in range(2):
        directory = tmp_path / "alfred-development-intake"
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        argv = shlex.split(command)
        argv[-1] = str(directory)
        result = subprocess.run(
            argv,
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            pytest.skip(f"ACL unavailable in this test filesystem: {result.stderr.strip()}")
        acl = subprocess.run(["getfacl", "-cp", str(directory)],
                             capture_output=True, text=True, check=True).stdout
        assert re.search(r"^user:alfredmsg:--x(?:\s|$)", acl, re.MULTILINE)
        assert re.search(r"^user:alfredphoton:--x(?:\s|$)", acl, re.MULTILINE)
        assert re.search(r"^mask::--x$", acl, re.MULTILINE)
        assert "#effective:---" not in acl


def test_existing_gateway_dispatcher_is_scheduled():
    service = (UNITS / "alfred-development-gateway.service").read_text()
    timer = (UNITS / "alfred-development-gateway.timer").read_text()
    assert "gateway.py run-once --intake-dir /home/alfred/Alfred/projects/hermes-requests" in service
    assert "User=alfred\n" in service
    assert "OnUnitInactiveSec=5s" in timer
    assert "Unit=alfred-development-gateway.service" in timer
    assert "OnBootSec=10s" in timer
