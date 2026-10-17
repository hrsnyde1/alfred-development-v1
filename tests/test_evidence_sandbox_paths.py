"""The Evidence poll runs every V1 stage under ProtectSystem=strict and a read-only
/home. Each directory the stages write must be listed in the drop-in, or the first
live write fails with EROFS (T-0004: the Developer's grant claim)."""

import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
DROP_IN = LAB / "fresh_v1/systemd/alfred-development-evidence.conf"
POLICY = LAB / "fresh_v1/config.example.json"
# Policy keys naming state that a stage creates or appends to.
WRITTEN = (
    "jobs",
    "grant_root",
    "developer_state",
    "worktree_root",
    "gateway_state",
    "completion_state",
)


def writable():
    paths = []
    for line in DROP_IN.read_text().splitlines():
        if line.startswith("ReadWritePaths="):
            paths += [p.lstrip("-") for p in line.split("=", 1)[1].split()]
    return [Path(p) for p in paths]


def covered(path):
    return any(path == root or root in path.parents for root in writable())


def test_every_policy_write_root_is_writable_in_the_sandbox():
    policy = json.loads(POLICY.read_text())
    missing = [key for key in WRITTEN if not covered(Path(policy[key]))]
    assert not missing, missing


def test_grant_store_is_writable_for_the_developer_claim():
    assert covered(Path("/var/lib/alfred-development-grants/execution-ref.json"))


def test_repository_is_writable_for_git_metadata_and_qa_acls():
    # git worktree metadata, and setfacl -R on every checkout file before QA.
    repo = Path(json.loads(POLICY.read_text())["repository"])
    assert covered(repo / ".git" / "worktrees")
    assert covered(repo / "calculator.py")
    assert not covered(repo.parent / "projects.proposed.yaml")


def test_every_host_share_target_is_writable():
    # Each setfacl target in fresh_v1/host.py, by the policy key it derives from.
    policy = json.loads(POLICY.read_text())
    source = (LAB / "fresh_v1/host.py").read_text()
    assert 'self.share(Path(job["repository"])' in source
    for key in ("repository", "worktree_root", "jobs"):
        assert covered(Path(policy[key]) / "x"), key


def test_sandbox_stays_strict():
    text = DROP_IN.read_text()
    assert "ProtectHome=read-only" in text
    assert not any(p in {Path("/"), Path("/home"), Path("/var"), Path("/etc")}
                   for p in writable())
