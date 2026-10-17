from __future__ import annotations

import os
from pathlib import Path

import pytest

from task_a.front_runner import _bound_inbox, _private_file
from task_a.photon_front import FrontError


def test_private_token_file_rejects_world_readable_and_symlink(lab_root: Path):
    secret = lab_root / "token"
    secret.write_bytes(b"synthetic-token")
    secret.chmod(0o644)
    with pytest.raises(FrontError):
        _private_file(lab_root, secret)
    secret.chmod(0o600)
    assert _private_file(lab_root, secret) == b"synthetic-token"
    link = lab_root / "token-link"
    link.symlink_to(secret)
    with pytest.raises(FrontError):
        _private_file(lab_root, link)


def test_private_token_file_cannot_escape_staging_root(lab_root: Path):
    with pytest.raises(FrontError):
        _private_file(lab_root, Path("/etc/passwd"))


def test_runner_accepts_only_static_lab_inbox(lab_root: Path):
    expected = lab_root / "home/Alfred/projects/hermes-requests/inbox"
    expected.mkdir(parents=True)
    assert _bound_inbox(lab_root, expected) == expected
    alternate = lab_root / "other-company/inbox"
    alternate.mkdir(parents=True)
    with pytest.raises(FrontError):
        _bound_inbox(lab_root, alternate)
