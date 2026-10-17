"""The diagnostic runs only the Publisher's local Git preflight."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from publisher_git_diagnostic import diagnose


def _git(*args: str) -> str:
    result = subprocess.run(["/usr/bin/git", *args], check=True,
                            capture_output=True, text=True)
    return result.stdout.strip()


def test_disposable_local_init_fetch_and_redacted_report(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch):
    work = tmp_path / "work"
    source = tmp_path / "source.git"
    _git("init", "-q", str(work))
    (work / "file.txt").write_text("baseline\n")
    _git("-C", str(work), "add", "file.txt")
    _git("-C", str(work), "-c", "user.name=Fixture",
         "-c", "user.email=fixture@example.invalid", "commit", "-qm", "baseline")
    baseline = _git("-C", str(work), "rev-parse", "HEAD")
    (work / "file.txt").write_text("final\n")
    _git("-C", str(work), "-c", "user.name=Fixture",
         "-c", "user.email=fixture@example.invalid", "commit", "-qam", "final")
    final = _git("-C", str(work), "rev-parse", "HEAD")
    _git("clone", "--bare", "-q", str(work), str(source))

    report = diagnose(source, baseline, final)
    assert [step["step"] for step in report["steps"]] == ["git_init_bare", "git_fetch_local"]
    assert all(step["passed"] for step in report["steps"])
    assert report["temporary"]["owner_uid"] == report["identity_uid"]
    assert "push_environment" in report

    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    unsafe = diagnose(source, baseline, final)
    assert [step["step"] for step in unsafe["steps"]] == [
        "git_init_bare", "git_fetch_local", "git_fetch_with_ephemeral_safe_directory"]
    assert unsafe["steps"][1]["stderr_category"] == "unsafe_repository_ownership"
    assert unsafe["steps"][2]["passed"] is True
