from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import shutil
import subprocess
from pathlib import Path

import intake
import pytest
import taskspec
import yaml
from alfred.gateway.dispatcher import FilingError, GatewayConfig, run_once
from alfred.gateway.envelope import EnvelopeError, parse_envelope
from alfred.registry.loader import parse_registry

ROOT = Path(__file__).resolve().parents[1]
TODAY = "2026-10-07"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
    )


def _world(tmp_path: Path):
    repo = tmp_path / "home" / "Git" / "dev-001"
    shutil.copytree(ROOT / "fixture" / "dev-001", repo)
    _git(repo, "init", "-q", "-b", "main")
    doc = yaml.safe_load((ROOT / "fixture" / "registry.template.yaml").read_text())
    doc["projects"][0]["local_path"] = str(repo)
    registry = parse_registry(doc)
    intake_dir = tmp_path / "inbox-service"
    (intake_dir / "inbox").mkdir(parents=True)
    config = GatewayConfig(
        intake_dir=intake_dir,
        gateway_dir=tmp_path / "gateway",
        home=tmp_path / "home",
        today=TODAY,
    )
    envelope = json.loads((ROOT / "fixture" / "envelope.json").read_text())
    return repo / ".dev" / "tasks", registry, intake_dir, config, envelope


def _specs(tasks: Path) -> list[Path]:
    return sorted(tasks.glob("T-????-*.md"))


def _process_file(args: tuple[str, str, int]) -> str:
    tasks_name, raw_text, n = args
    raw = json.loads(raw_text)
    raw["request_id"] = f"{n:08x}-0000-4000-8000-000000000000"
    tasks = Path(tasks_name)
    doc = yaml.safe_load((ROOT / "fixture" / "registry.template.yaml").read_text())
    doc["projects"][0]["local_path"] = str(tasks.parent.parent)
    project = parse_registry(doc).projects[0]
    return intake.IntakeFiler().file_envelope(
        parse_envelope(raw), project, tasks, TODAY, source="hermes"
    )


def test_normal_gateway_filing_is_proposed_only(tmp_path: Path) -> None:
    tasks, registry, intake_dir, config, envelope = _world(tmp_path)
    (intake_dir / "inbox" / "request.json").write_text(json.dumps(envelope))
    report = run_once(registry, intake.IntakeFiler(), config)
    assert report.filed == ["T-0001"]
    (path,) = _specs(tasks)
    doc = taskspec.parse(path.read_text())
    assert taskspec.validate(doc, path.name, "alfred") == []
    assert (doc["request_id"], doc["project"], doc["source"], doc["status"]) == (
        envelope["request_id"],
        "dev-001",
        "hermes",
        "proposed",
    )
    assert doc["approved_by"] is None and doc["branch"] is None and doc["pr"] is None


def test_duplicate_delivery_and_crash_retry_create_one_spec(tmp_path: Path) -> None:
    tasks, registry, intake_dir, config, raw = _world(tmp_path)
    filer = intake.IntakeFiler()
    envelope = parse_envelope(raw)
    project = registry.projects[0]
    assert (
        filer.file_envelope(envelope, project, tasks, TODAY, source="hermes")
        == "T-0001"
    )
    assert (
        filer.file_envelope(envelope, project, tasks, TODAY, source="hermes")
        == "T-0001"
    )
    assert len(_specs(tasks)) == 1
    (intake_dir / "inbox" / "retry.json").write_text(json.dumps(raw))
    assert run_once(registry, filer, config).filed == ["T-0001"]
    assert len(_specs(tasks)) == 1


def test_concurrent_requests_and_retries_have_unique_ids(tmp_path: Path) -> None:
    tasks, registry, _, _, raw = _world(tmp_path)
    filer, project = intake.IntakeFiler(), registry.projects[0]

    def file(n: int) -> str:
        doc = raw | {"request_id": f"{n:08x}-0000-4000-8000-000000000000"}
        return filer.file_envelope(
            parse_envelope(doc), project, tasks, TODAY, source="hermes"
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(file, list(range(1, 13)) * 2))
    assert len(set(ids)) == 12
    assert len(_specs(tasks)) == 12
    assert {p.name[:6] for p in _specs(tasks)} == {f"T-{n:04d}" for n in range(1, 13)}


def test_concurrent_processes_share_task_directory_lock(tmp_path: Path) -> None:
    tasks, _, _, _, raw = _world(tmp_path)
    inputs = [(str(tasks), json.dumps(raw), n) for n in range(1, 9)]
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=4, mp_context=multiprocessing.get_context("fork")
    ) as pool:
        ids = list(pool.map(_process_file, inputs))
    assert len(set(ids)) == len(_specs(tasks)) == 8


def test_changed_duplicate_content_and_authority_fail_closed(tmp_path: Path) -> None:
    tasks, registry, _, _, raw = _world(tmp_path)
    filer, project = intake.IntakeFiler(), registry.projects[0]
    filer.file_envelope(parse_envelope(raw), project, tasks, TODAY, source="hermes")
    changed = json.loads(json.dumps(raw))
    changed["draft"]["objective"] = "Different work."
    with pytest.raises(FilingError, match="different content"):
        filer.file_envelope(
            parse_envelope(changed), project, tasks, TODAY, source="hermes"
        )
    with pytest.raises(FilingError, match="different content"):
        filer.file_envelope(
            parse_envelope(raw), project, tasks, TODAY, source="openclaw"
        )
    assert len(_specs(tasks)) == 1


def test_malformed_envelope_rejected_without_task(tmp_path: Path) -> None:
    tasks, registry, intake_dir, config, raw = _world(tmp_path)
    raw["status"] = "ready"
    with pytest.raises(EnvelopeError):
        parse_envelope(raw)
    (intake_dir / "inbox" / "bad.json").write_text(json.dumps(raw))
    report = run_once(registry, intake.IntakeFiler(), config)
    assert report.filed == [] and report.rejected
    assert _specs(tasks) == []


def test_existing_id_and_protected_reservation_are_skipped(tmp_path: Path) -> None:
    tasks, registry, _, _, raw = _world(tmp_path)
    (tasks / "T-0012-existing.md").write_text("not a task spec")
    # Historical malformed files are ignored for dedupe but their IDs remain occupied.
    assert (
        intake.IntakeFiler().file_envelope(
            parse_envelope(raw), registry.projects[0], tasks, TODAY, source="hermes"
        )
        == "T-0013"
    )
    (tasks / "T-0012-existing.md").unlink()
    _specs(tasks)[0].unlink()
    (tasks.parent / "task-id-reservations.txt").write_text("T-0009\nT-0013\n")
    assert taskspec.next_id(tasks) == "T-0014"
    assert (
        intake.IntakeFiler().file_envelope(
            parse_envelope(raw), registry.projects[0], tasks, TODAY, source="hermes"
        )
        == "T-0014"
    )


def test_other_branch_and_branch_name_ids_are_skipped(tmp_path: Path) -> None:
    tasks, _, _, _, _ = _world(tmp_path)
    repo = tasks.parent.parent
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "add", ".dev/tasks/.gitkeep")
    _git(repo, "commit", "-qm", "fixture")
    _git(repo, "switch", "-qc", "claude/T-0041-branch")
    (tasks / "T-0044-other-branch.md").write_text("fixture")
    _git(repo, "add", ".dev/tasks/T-0044-other-branch.md")
    _git(repo, "commit", "-qm", "branch task")
    _git(repo, "switch", "-q", "main")
    assert taskspec.next_id(tasks) == "T-0045"


def test_branch_name_reservation_without_spec_is_skipped(tmp_path: Path) -> None:
    tasks, _, _, _, _ = _world(tmp_path)
    repo = tasks.parent.parent
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "add", ".dev/tasks/.gitkeep")
    _git(repo, "commit", "-qm", "fixture")
    _git(repo, "branch", "claude/T-0041-planned")
    assert taskspec.next_id(tasks) == "T-0042"


def test_untracked_spec_in_another_worktree_reserves_id(tmp_path: Path) -> None:
    tasks, _, _, _, _ = _world(tmp_path)
    repo = tasks.parent.parent
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "add", ".dev/tasks/.gitkeep")
    _git(repo, "commit", "-qm", "fixture")
    other = tmp_path / "other-worktree"
    _git(repo, "worktree", "add", "-qb", "fixture-other", str(other))
    (other / ".dev" / "tasks" / "T-0050-untracked.md").write_text("fixture")
    assert taskspec.next_id(tasks) == "T-0051"


def test_conflicting_same_id_with_different_slug_is_not_reused(tmp_path: Path) -> None:
    tasks, _, _, _, _ = _world(tmp_path)
    (tasks / "T-0020-existing.md").write_text("fixture")
    assert taskspec.next_id(tasks) == "T-0021"


def test_publication_failure_after_link_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks, registry, _, _, raw = _world(tmp_path)
    original = intake.os.fsync
    calls = 0

    def fail_directory_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(5, "injected directory fsync failure")
        original(fd)

    monkeypatch.setattr(intake.os, "fsync", fail_directory_fsync)
    filer, envelope, project = (
        intake.IntakeFiler(),
        parse_envelope(raw),
        registry.projects[0],
    )
    with pytest.raises(FilingError, match="durably publish"):
        filer.file_envelope(envelope, project, tasks, TODAY, source="hermes")
    monkeypatch.setattr(intake.os, "fsync", original)
    assert (
        filer.file_envelope(envelope, project, tasks, TODAY, source="hermes")
        == "T-0001"
    )
    assert len(_specs(tasks)) == 1
    assert not list(tasks.glob(".gateway-*"))


def test_publication_failure_before_link_leaves_no_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks, registry, _, _, raw = _world(tmp_path)

    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError(5, "injected link failure")

    original = intake.os.link
    monkeypatch.setattr(intake.os, "link", fail_link)
    with pytest.raises(FilingError, match="durably publish"):
        intake.IntakeFiler().file_envelope(
            parse_envelope(raw), registry.projects[0], tasks, TODAY, source="hermes"
        )
    monkeypatch.setattr(intake.os, "link", original)
    assert _specs(tasks) == []
    assert not list(tasks.glob(".gateway-*"))


def test_overflow_fails_closed(tmp_path: Path) -> None:
    tasks, _, _, _, _ = _world(tmp_path)
    (tasks / "T-9999-last.md").write_text("fixture")
    with pytest.raises(taskspec.SpecError, match="exhausted"):
        taskspec.next_id(tasks)


def test_dangling_reservation_symlink_fails_closed(tmp_path: Path) -> None:
    tasks, _, _, _, _ = _world(tmp_path)
    (tasks.parent / "task-id-reservations.txt").symlink_to("missing")
    with pytest.raises(taskspec.SpecError, match="unsafe task ID reservations"):
        taskspec.next_id(tasks)
