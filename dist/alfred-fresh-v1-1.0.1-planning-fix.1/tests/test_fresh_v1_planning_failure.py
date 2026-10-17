"""Disposable policy/worker boundary and fail-closed diagnostic regressions."""

import contextlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import fresh_v1_planning_patch as transaction
from fresh_v1 import diagnostics, host, role
from fresh_v1.handoffs import Held, advance
from fresh_v1.protected import protected_json

ROOT = Path(__file__).resolve().parents[1]

JOB = {"project": "dev-v1-accept", "task_id": "T-0041"}


@pytest.fixture
def adapter(tmp_path):
    policy = {
        "schema": "alfred.fresh-v1-policy/1",
        "enabled": True,
        "project": JOB["project"],
        "jobs": str(tmp_path / "jobs"),
        "gateway_state": str(tmp_path / "gateway"),
    }
    canonical = tmp_path / "policy.json"
    canonical.write_text(json.dumps(policy))
    canonical.chmod(0o600)
    obj = host.Host(policy, canonical)
    root = obj.jobdir(JOB)
    root.mkdir(parents=True)
    for directory in (root, root.parent, root.parent.parent):
        directory.chmod(0o700)
    (root / "job.json").write_text(json.dumps(JOB))
    (root / "job.json").chmod(0o600)
    reader = lambda p: protected_json(
        p, trusted_uid=os.geteuid(), trusted_root=tmp_path
    )

    # Fixtures use one OS identity; only the privilege transition is substituted.
    def share(path, users):
        subprocess.run(
            ["setfacl", "-m", ",".join(f"u:{u}:r--" for u in users), str(path)],
            check=True,
        )

    with (
        patch.object(host, "protected_json", reader),
        patch.object(role, "protected_json", reader),
        patch.object(obj, "share", share),
    ):
        yield obj


def test_original_private_policy_failure_and_sealed_worker_input_succeeds(adapter):
    canonical = adapter.policy_path
    original = canonical.read_bytes()
    # Same OS denial as root:root 0600 -> alfred, using no privileged fixture setup.
    canonical.chmod(0)
    try:
        with pytest.raises(diagnostics.WorkerFailure) as caught:
            role.main(
                ["plan", "--job", str(adapter.jobdir(JOB)), "--policy", str(canonical)]
            )
        assert caught.value.evidence["phase"] == "policy_read"
        assert caught.value.evidence["category"] == "permission_denied"
        calls = []

        def run(args, **kw):
            calls.append(args)
            argv = args[args.index("--job") - 1 :]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                role.worker_main(argv)
            return subprocess.CompletedProcess(
                args, 0, stdout=output.getvalue().encode()
            )

        with (
            patch.object(adapter, "guard"),
            patch.object(host, "command", run),
            patch.object(role, "prepare_plan", return_value={"planned": True}),
        ):
            assert adapter.worker(JOB, "plan", "alfred") == {"planned": True}
        frozen = adapter.jobdir(JOB) / "worker-policy.json"
        assert (
            protected_json(
                frozen, trusted_uid=os.geteuid(), trusted_root=canonical.parent
            )[0]
            == adapter.p
        )
        assert calls[0][-1] == str(frozen) != str(canonical)
        assert canonical.stat().st_mode & 0o777 == 0
        acl = subprocess.check_output(["getfacl", "-cp", str(frozen)]).decode()
        for user in host.USERS:
            assert f"user:{user}:r--" in acl
        assert "other::---" in acl
    finally:
        canonical.chmod(0o600)
    assert canonical.read_bytes() == original


def test_policy_change_blocks_existing_snapshot_and_disabled_policy_blocks_dispatch(
    adapter,
):
    with patch.object(
        host, "command", return_value=subprocess.CompletedProcess([], 0, stdout=b"{}")
    ):
        adapter.worker(JOB, "plan", "alfred")
    snapshot = adapter.jobdir(JOB) / "worker-policy.json"
    original = snapshot.read_bytes()
    changed = dict(adapter.p, total_cost_limit=1)
    adapter.p = changed
    adapter.policy_path.write_text(json.dumps(changed))
    with patch.object(host, "command") as command, pytest.raises(Held, match="differs"):
        adapter.worker(JOB, "developer", "alfred")
    command.assert_not_called()
    assert snapshot.read_bytes() == original
    adapter.policy_path.write_text(json.dumps(dict(changed, enabled=False)))
    with (
        patch.object(host, "command") as command,
        pytest.raises(Held, match="activation"),
    ):
        adapter.worker(JOB, "plan", "alfred")
    command.assert_not_called()


@pytest.mark.parametrize(
    "phase,stderr,category",
    [
        ("github_main_lookup", b"HTTP 401 ghp_DO_NOT_LOG", "authentication_refused"),
        (
            "git_fetch",
            b"fatal: Permission denied Bearer DO_NOT_LOG",
            "permission_denied",
        ),
        ("git_fetch", b"Read-only file system DO_NOT_LOG", "read_only_filesystem"),
        (
            "git_fetch",
            b"detected dubious ownership DO_NOT_LOG",
            "unsafe_repository_ownership",
        ),
        ("git_ref_verify", b"fatal: bad object DO_NOT_LOG", "missing_object"),
        ("git_tree", b"unknown error DO_NOT_LOG", "process_failed"),
        ("git_blob", b"Could not resolve host DO_NOT_LOG", "network_unavailable"),
    ],
)
def test_planning_subprocess_reports_exact_phase_without_sensitive_output(
    phase, stderr, category, capsys
):
    exc = subprocess.CalledProcessError(
        128, ["secret-command", "DO_NOT_LOG"], output=b"DO_NOT_LOG", stderr=stderr
    )
    with (
        patch.object(diagnostics.subprocess, "check_output", side_effect=exc),
        pytest.raises(diagnostics.WorkerFailure) as caught,
    ):
        diagnostics.planning_output(phase, ["mock-only"], timeout=1)
    evidence = caught.value.evidence
    assert evidence["phase"] == phase and evidence["category"] == category
    assert evidence["operation_returncode"] == 128
    with (
        patch.object(role, "main", side_effect=caught.value),
        pytest.raises(SystemExit),
    ):
        role.worker_main(["plan"])
    captured = capsys.readouterr()
    assert not captured.out
    assert "DO_NOT_LOG" not in captured.err and "Traceback" not in captured.err
    assert json.loads(captured.err) == evidence


@pytest.mark.parametrize(
    "exc,category",
    [
        (subprocess.TimeoutExpired(["DO_NOT_LOG"], 1, stderr=b"DO_NOT_LOG"), "timeout"),
        (PermissionError(13, "DO_NOT_LOG"), "permission_denied"),
    ],
)
def test_timeouts_and_exec_permission_errors_are_redacted(exc, category):
    with (
        patch.object(diagnostics.subprocess, "check_output", side_effect=exc),
        pytest.raises(diagnostics.WorkerFailure) as caught,
    ):
        diagnostics.planning_output("github_main_lookup", [], timeout=1)
    assert caught.value.evidence["category"] == category
    assert "DO_NOT_LOG" not in json.dumps(caught.value.evidence)


def test_failure_is_durable_and_restart_never_replays_attempt(adapter):
    failure = diagnostics.failure(
        "plan", "policy_read", PermissionError(13, "DO_NOT_LOG")
    )
    exc = subprocess.CalledProcessError(
        1, ["DO_NOT_LOG"], stderr=json.dumps(failure).encode()
    )
    with patch.object(host, "command", side_effect=exc):
        result = advance(adapter.jobdir(JOB), JOB, adapter)
    assert result == {"state": "held", "reason": "plan: policy_read/permission_denied"}
    root = adapter.jobdir(JOB)
    original = {p.name: p.read_bytes() for p in root.iterdir()}
    assert (
        not (root / "context.json").exists()
        and not (root / "plan.result.json").exists()
    )
    assert json.loads(original["plan.failure.json"])["worker_returncode"] == 1
    assert "DO_NOT_LOG" not in original["plan.failure.json"].decode()
    # A new adapter models process restart, retaining attempt and original evidence.
    restarted = host.Host(adapter.p, adapter.policy_path)
    with patch.object(host, "command") as command:
        assert "requires reconciliation" in advance(root, JOB, restarted)["reason"]
    command.assert_not_called()
    assert {p.name: p.read_bytes() for p in root.iterdir()} == original


@pytest.mark.parametrize(
    "stderr",
    [
        b'{"secret":"DO_NOT_LOG"}',
        b"DO_NOT_LOG" * 1000,
        b'{"phase": ["DO_NOT_LOG"]}',
        b"runuser: cannot open session: DO_NOT_LOG",
    ],
)
def test_parent_filters_untrusted_diagnostics(stderr):
    exc = subprocess.CalledProcessError(1, ["DO_NOT_LOG"], stderr=stderr)
    result = diagnostics.worker_failure("plan", exc)
    assert result["phase"] == "worker_startup"
    assert "DO_NOT_LOG" not in json.dumps(result)


def test_plain_python_failure_never_exposes_exception_text(capsys):
    with (
        patch.object(role, "main", side_effect=ValueError("Bearer DO_NOT_LOG")),
        pytest.raises(SystemExit),
    ):
        role.worker_main(["plan"])
    captured = capsys.readouterr()
    assert json.loads(captured.err)["phase"] == "python"
    assert "DO_NOT_LOG" not in captured.err


@pytest.mark.parametrize("output", [b"", b"DO_NOT_LOG", b"[]", b"\xff"])
def test_invalid_worker_stdout_is_held_with_redacted_durable_evidence(adapter, output):
    with patch.object(
        host, "command", return_value=subprocess.CompletedProcess([], 0, stdout=output)
    ):
        result = advance(adapter.jobdir(JOB), JOB, adapter)
    assert result == {
        "state": "held",
        "reason": "plan: worker_output/invalid_worker_result",
    }
    raw = (adapter.jobdir(JOB) / "plan.failure.json").read_bytes()
    assert b"DO_NOT_LOG" not in raw
    assert not (adapter.jobdir(JOB) / "plan.result.json").exists()


@pytest.fixture
def patch_host(tmp_path):
    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    base = ROOT / "dist/alfred-fresh-v1-1.0.1/fresh_v1"
    for name in transaction.BASE:
        target = root / (transaction.PREFIX + name).lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base / name, target)
        target.chmod(0o644)
    for name in transaction.FILES:
        target = release / "fresh_v1" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "fresh_v1" / name, target)
    manifest = "".join(
        f"{transaction.upgrade.digest(p.read_bytes())}  {p.relative_to(release)}\n"
        for p in sorted(release.rglob("*"))
        if p.is_file()
    ).encode()
    (release / "MANIFEST.sha256").write_bytes(manifest)
    marker = root / transaction.upgrade.MARKER.lstrip("/")
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"preserve active\n")
    marker.chmod(0o644)
    for name in (
        "home/alfred/Alfred/gateway/PAUSE",
        "etc/alfred-fresh-v1/policy.json",
        "var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/plan.attempt.json",
        "var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/job.json",
        "home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json",
        "var/lib/alfred-development-grants/T-0001.json",
        "var/lib/alfred-qa-state/T-0002/qa-report.json",
        "var/lib/alfred-reviewer-state/T-0002/review-report.json",
        "var/lib/alfred-draft-pr-authorizations/T-0002.json",
        "var/lib/alfred-draft-pr-state/T-0002/publication-plan.json",
        "var/lib/alfred-draft-pr-private/github-token",
        "home/alfred/Alfred/completion-delivery/delivery.json",
    ):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"DO NOT ALTER " + name.encode())
        target.chmod(0o600)
    return root, release, transaction.upgrade.digest(manifest), tmp_path / "backup"


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode & 0o777)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_patch_install_and_rollback_only_touch_three_code_files(patch_host):
    root, release, pin, backup = patch_host
    before = snapshot(root)
    assert transaction.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    after = snapshot(root)
    assert {
        n for n in before.keys() | after.keys() if before.get(n) != after.get(n)
    } == {(transaction.PREFIX + n).lstrip("/") for n in transaction.FILES}
    assert transaction.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    assert snapshot(root) == before
    transaction.rollback(root, backup)
    assert snapshot(root) == before


@pytest.mark.parametrize("position", range(3))
def test_patch_partial_failure_restores_original_without_losing_marker(
    patch_host, position
):
    root, release, pin, backup = patch_host
    before = snapshot(root)
    with pytest.raises(OSError, match="fixture fault"):
        transaction.install(release, pin, root, backup, fail_after=position)
    assert snapshot(root) == before


def test_interrupted_patch_is_explicitly_recoverable_without_replaying_task(patch_host):
    root, release, pin, backup = patch_host
    before = snapshot(root)
    with (
        patch.object(
            transaction, "rollback", side_effect=OSError("interrupted recovery")
        ),
        pytest.raises(OSError),
    ):
        transaction.install(release, pin, root, backup, fail_after=2)
    assert snapshot(root) != before
    transaction.rollback(root, backup)
    assert snapshot(root) == before


@pytest.mark.parametrize("defect", ["pin", "base", "pause", "extra_file"])
def test_invalid_upgrade_is_rejected_before_mutation(patch_host, defect):
    root, release, pin, backup = patch_host
    if defect == "pin":
        pin = "0" * 64
    elif defect == "base":
        (root / (transaction.PREFIX + "host.py").lstrip("/")).write_text("unexpected")
    elif defect == "pause":
        (root / "home/alfred/Alfred/gateway/PAUSE").unlink()
    else:
        (release / "unexpected.py").touch()
    before = snapshot(root)
    with pytest.raises(ValueError):
        transaction.install(release, pin, root, backup)
    assert snapshot(root) == before and not backup.exists()
