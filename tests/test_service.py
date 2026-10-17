"""Disposable process-lifecycle checks; no SDK, account or systemd launch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from task_a.photon_front import FrontError
from task_a.service import ProtectedSidecarSupervisor, _credential


def test_protected_child_starts_once_and_stops_without_hermes_environment(tmp_path, monkeypatch):
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    child = tmp_path / "fake_sidecar.py"
    child.write_text('''
import json, os, pathlib, signal, time
out = pathlib.Path(os.environ["PHOTON_EVENT_SPOOL"]) / "started.json"
out.write_text(json.dumps({"project": bool(os.environ.get("PHOTON_PROJECT_ID")),
                           "secret": bool(os.environ.get("PHOTON_PROJECT_SECRET")),
                           "token": bool(os.environ.get("PHOTON_SIDECAR_TOKEN")),
                           "hermes_socket": "PHOTON_TASK_A_BROKER_SOCKET" in os.environ}))
signal.signal(signal.SIGTERM, lambda *_: exit(0))
while True: time.sleep(0.1)
''')
    monkeypatch.setenv("PHOTON_TASK_A_BROKER_SOCKET", "/tmp/should-not-leak")
    audit = []
    supervisor = ProtectedSidecarSupervisor(Path(sys.executable), child, tmp_path / "private.sock", spool,
                                           project_id="synthetic-project", project_secret="synthetic-secret",
                                           token="t" * 64, audit=audit.append)
    try:
        supervisor.start()
        with pytest.raises(FrontError, match="already running"):
            supervisor.start()
        deadline = time.monotonic() + 3
        while not (spool / "started.json").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert json.loads((spool / "started.json").read_text()) == {
            "project": True, "secret": True, "token": True, "hermes_socket": False}
        pid = supervisor.process.pid
    finally:
        supervisor.stop()
    assert supervisor.process is None
    assert audit == ["sidecar_started", "sidecar_stopped"]
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_credential_handoff_rejects_symlink_and_group_read(tmp_path):
    directory = tmp_path / "credentials"
    directory.mkdir(mode=0o700)
    path = directory / "project_id"
    path.write_text("synthetic-project\n")
    path.chmod(0o600)
    assert _credential(directory, "project_id") == "synthetic-project"
    path.chmod(0o640)
    with pytest.raises(FrontError):
        _credential(directory, "project_id")
    path.chmod(0o600)
    link = directory / "project_secret"
    link.symlink_to(path)
    with pytest.raises(OSError):
        _credential(directory, "project_secret")
