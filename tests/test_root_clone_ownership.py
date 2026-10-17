"""handoff.7: root clones the alfred-owned final worktree for the Reviewer and the
Publisher. git checks ownership of the worktree's own git directory (T-0008:
"detected dubious ownership"), reproduced here with GIT_TEST_ASSUME_DIFFERENT_OWNER."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fresh_v1 import host
from fresh_v1.handoffs import Held

UID = os.geteuid()


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
                        "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "f",
                        "GIT_AUTHOR_EMAIL": "f@x", "GIT_COMMITTER_NAME": "f",
                        "GIT_COMMITTER_EMAIL": "f@x"})


@pytest.fixture
def layout(tmp_path):
    # As on the host (the Developer's worktree .git file is 0640): no group write.
    previous = os.umask(0o027)
    try:
        yield from _layout(tmp_path)
    finally:
        os.umask(previous)


def _layout(tmp_path):
    repo, final = tmp_path / "repo", tmp_path / "worktrees/dev-v1-accept-T-0009-final"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "baseline")
    final.parent.mkdir()
    git(repo, "worktree", "add", "-q", "-b", "final", str(final))
    yield repo, final, tmp_path


def as_other_owner(args, **kwargs):
    # Root's view: every repository path is owned by someone else (alfred).
    env = {**kwargs.pop("env"), "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}
    return subprocess.run(args, check=True, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=30, env=env, **kwargs)


@pytest.mark.parametrize("bare", [False, True])
def test_root_clone_of_linked_worktree_succeeds(layout, bare):
    repo, final, tmp_path = layout
    target = tmp_path / ("source.git" if bare else "snapshot")
    with patch.object(host, "command", as_other_owner):
        host.clone_snapshot(final, target, repo, UID, bare=bare)
    head = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    expected = subprocess.run(["git", "-C", str(final), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    assert head == expected


@pytest.mark.parametrize("bare", [False, True])
def test_worktree_only_trust_reproduces_the_t0008_failure(layout, bare):
    repo, final, tmp_path = layout
    with (
        patch.object(host, "command", as_other_owner),
        patch.object(host, "worktree_git_dirs", lambda s, r, u: [s.resolve()]),
        pytest.raises(subprocess.CalledProcessError) as caught,
    ):
        host.clone_snapshot(final, tmp_path / "out", repo, UID, bare=bare)
    assert b"dubious ownership" in caught.value.stderr


def test_trusted_directories_are_exactly_worktree_gitdir_and_common(layout):
    repo, final, _ = layout
    assert host.worktree_git_dirs(final, repo, UID) == [
        final.resolve(),
        (repo / ".git/worktrees" / final.name).resolve(),
        (repo / ".git").resolve(),
    ]


def test_worktree_of_another_repository_is_refused(layout):
    _repo, final, tmp_path = layout
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    with pytest.raises(Held, match="registered repository"):
        host.worktree_git_dirs(final, other, UID)


def test_redirected_gitdir_is_refused(layout):
    repo, final, tmp_path = layout
    marker = final / ".git"
    marker.write_text(f"gitdir: {tmp_path}/elsewhere/.git/worktrees/x\n")
    with pytest.raises(Held, match="registered repository"):
        host.worktree_git_dirs(final, repo, UID)


def test_plain_repository_is_not_a_trusted_snapshot_source(layout):
    repo, _, _ = layout
    with pytest.raises((Held, ValueError, OSError)):
        host.worktree_git_dirs(repo, repo, UID)


def test_marker_owned_by_another_identity_is_refused(layout):
    repo, final, _ = layout
    with pytest.raises(ValueError, match="unsafe worker evidence"):
        host.worktree_git_dirs(final, repo, UID + 1)


def test_reviewer_and_publication_clone_pass_the_registered_repository():
    source = Path(host.__file__).read_text()
    assert source.count('Path(manifest["repository"]),') == 2
