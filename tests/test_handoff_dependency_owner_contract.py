"""Reproduce the pinned installer's unchanged Photon dependency ownership gate."""

import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[1]
INSTALLER = (
    LAB
    / "dist/alfred-fresh-v1-1.0.1-development-handoff.1/development_challenge/install_patch.py"
)
PIN = "cee25c92548ae07bf3c68a25cb0fea00f2ff54ecbe94421e80368cfa4962629f"


@pytest.mark.parametrize("owner,accepted", [(1000, False), (0, True)])
def test_pinned_root_installer_rejects_alfred_owned_dependency_even_with_correct_hash(
    tmp_path, monkeypatch, owner, accepted
):
    assert hashlib.sha256(INSTALLER.read_bytes()).hexdigest() == PIN
    spec = importlib.util.spec_from_file_location(
        "pinned_handoff_owner_gate", INSTALLER
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    path = tmp_path / "index.mjs"
    path.write_bytes(b"unchanged disposable Photon dependency fixture\n")
    path.chmod(0o644)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    lstat = Path.lstat

    def metadata(p, *args, **kwargs):
        result = lstat(p, *args, **kwargs)
        if p == path:
            fields = list(result)
            fields[4] = owner
            return os.stat_result(fields)
        return result

    # Model only caller/owner metadata; no real chown, sudo or host mutation.
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "lstat", metadata)
    before = path.read_bytes()
    if accepted:
        assert installer.checked(path, expected)[1] == before
    else:
        with pytest.raises(ValueError, match="installed contract mismatch"):
            installer.checked(path, expected)
    assert path.read_bytes() == before
