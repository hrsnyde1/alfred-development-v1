"""handoff.38: a refused plan step reaches the owner as one plain text, never silence.

The refusal travels as a fixed category, never exception text, so the worker boundary
still redacts everything else (tests/test_fresh_v1_planning_failure.py)."""

import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from developer_v1.trusted_intake_development import PLAN_REFUSAL_TEXT, IntakeRefused
from fresh_v1 import diagnostics, host, role
from fresh_v1.protected import protected_json
from tests import test_fresh_v1 as fresh
from tests.test_fresh_v1 import world  # noqa: F401 (pytest fixture)

REFUSALS = [
    ("scope or specialist requires clarification", "clarification_required"),
    ("project outside activated low-risk policy", "project_outside_policy"),
    ("registered main unavailable", "registered_main_unavailable"),
    ("main moved during planning", "main_moved"),
    ("unsupported planning tree", "planning_tree_unavailable"),
    ("planning tree too large", "planning_tree_unavailable"),
]


@pytest.mark.parametrize("message,category", REFUSALS)
def test_each_plan_refusal_is_a_fixed_category_without_its_text(message, category):
    evidence = diagnostics.failure("plan", "python", ValueError(message))
    assert evidence["phase"] == "plan_refusal" and evidence["category"] == category
    assert message not in json.dumps(evidence)


def test_every_refusal_message_is_one_prepare_plan_raises():
    source = Path(role.__file__).read_text()
    for (message,) in diagnostics.PLAN_REFUSALS:
        assert f'raise ValueError("{message}")' in source


def test_the_owner_texts_cover_exactly_the_categories():
    assert set(PLAN_REFUSAL_TEXT) == set(diagnostics.PLAN_REFUSALS.values())


@pytest.mark.parametrize(
    "stage,exc",
    [
        ("plan", ValueError("scope or specialist requires clarification: DO_NOT_LOG")),
        ("plan", ValueError("DO_NOT_LOG")),
        ("plan", ValueError("registered main unavailable", "DO_NOT_LOG")),
        ("plan", ValueError(["DO_NOT_LOG"])),
        ("plan", type("Sub", (ValueError,), {})("registered main unavailable")),
        ("plan", RuntimeError("registered main unavailable")),
        ("developer", ValueError("registered main unavailable")),
    ],
)
def test_anything_else_stays_a_redacted_python_failure(stage, exc):
    evidence = diagnostics.failure(stage, "python", exc)
    assert (evidence["phase"], evidence["category"]) == ("python", "python_failed")
    assert "DO_NOT_LOG" not in json.dumps(evidence)


def test_worker_boundary_carries_the_category_and_the_host_accepts_it(capsys):
    with (
        patch.object(role, "main", side_effect=ValueError("main moved during planning")),
        pytest.raises(SystemExit),
    ):
        role.worker_main(["plan"])
    stderr = capsys.readouterr().err
    assert "during planning" not in stderr
    exc = subprocess.CalledProcessError(1, ["DO_NOT_LOG"], stderr=stderr.encode())
    result = diagnostics.worker_failure("plan", exc)
    assert (result["phase"], result["category"]) == ("plan_refusal", "main_moved")


@pytest.mark.parametrize(
    "stage,phase,category",
    [
        ("plan", "python", "clarification_required"),
        ("plan", "plan_refusal", "python_failed"),
        ("qa", "plan_refusal", "clarification_required"),
    ],
)
def test_host_refuses_a_mismatched_refusal_row(stage, phase, category):
    row = dict(diagnostics.failure(stage, "python", ValueError()), phase=phase,
               category=category)
    exc = subprocess.CalledProcessError(1, [], stderr=json.dumps(row).encode())
    assert diagnostics.worker_failure(stage, exc)["phase"] == "worker_startup"


def refuse_planning(world):
    """A real prepare_plan refusal: nothing the request names is in the allowed scope."""
    world.p["allowed_scope"] = ["not-in-the-repository.py"]
    fresh.save(world.policy_path, world.p)


def plan_through_the_worker_boundary(world):
    """Host.worker, with the role process run in-process behind the same redaction."""
    original = role.prepare_plan

    def reader(path):
        return protected_json(path, trusted_uid=os.geteuid(), trusted_root=world.root)

    def run(args, **kw):
        stderr = io.StringIO()
        with (
            patch.object(role, "protected_json", reader),
            patch.object(role, "prepare_plan", lambda job, policy: original(
                job, policy, remote_main=world.main, fetch=False)),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(stderr),
        ):
            try:
                role.worker_main(args[args.index("--job") - 1:])
            except SystemExit:
                raise subprocess.CalledProcessError(
                    1, args, stderr=stderr.getvalue().encode()) from None
        raise AssertionError("planning was expected to refuse")

    with (
        patch.object(host, "command", run),
        patch.object(host, "protected_json", reader),
        pytest.raises(diagnostics.WorkerFailure),
    ):
        host.Host.worker(world, world.job, "plan", "alfred")


def refusal_texts(world):
    return [m for _, m in world.messages if "Nothing was started." in m]


def test_a_refused_plan_texts_the_owner_once(world):
    task = world.submit()
    refuse_planning(world)
    plan_through_the_worker_boundary(world)
    directory = world.jobdir(world.job)
    evidence = json.loads((directory / "plan.failure.json").read_bytes())
    assert (evidence["phase"], evidence["category"]) == ("plan_refusal",
                                                         "clarification_required")
    assert host.plan_refusal(directory, world.job, world)["state"] == "sent"
    # Every later poll of the held task finds the recorded notice and sends nothing.
    host.plan_refusal(directory, world.job, world)
    host.plan_refusal(directory, world.job, world)
    [text] = refusal_texts(world)
    assert text.startswith(task + " (") and "needs a clearer request" in text
    for leaked in ("specialist", "Traceback", "ValueError", "not-in-the-repository"):
        assert leaked not in text
    assert world.messages[-1][0] == "mock-dm"


def test_a_notice_that_did_not_answer_is_never_resent(world):
    world.submit()
    refuse_planning(world)
    plan_through_the_worker_boundary(world)
    directory = world.jobdir(world.job)
    with patch.object(world.gate, "preview_sender", side_effect=TimeoutError("DO_NOT_LOG")):
        assert host.plan_refusal(directory, world.job, world) is None
    assert host.plan_refusal(directory, world.job, world) is None
    assert not refusal_texts(world)
    assert (directory / "plan-refusal-notice.attempt.json").exists()
    assert not (directory / "plan-refusal-notice.result.json").exists()


def test_a_paused_host_sends_nothing_and_keeps_the_notice_for_later(world):
    world.submit()
    refuse_planning(world)
    plan_through_the_worker_boundary(world)
    directory = world.jobdir(world.job)
    pause = Path(world.p["gateway_state"]) / "PAUSE"
    pause.write_bytes(b"")
    assert host.plan_refusal(directory, world.job, world) is None
    assert not (directory / "plan-refusal-notice.attempt.json").exists()
    pause.unlink()
    assert host.plan_refusal(directory, world.job, world)["state"] == "sent"
    assert len(refusal_texts(world)) == 1


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        "not json",
        {"stage": "plan", "phase": "python", "category": "python_failed"},
        {"stage": "plan", "phase": "git_fetch", "category": "network_unavailable"},
        {"stage": "plan", "phase": "plan_refusal", "category": "DO_NOT_LOG"},
        {"stage": "qa", "phase": "plan_refusal", "category": "clarification_required"},
    ],
)
def test_other_failures_send_nothing(world, evidence):
    world.submit()
    directory = world.jobdir(world.job)
    if evidence is not None:
        (directory / "plan.failure.json").write_text(
            evidence if type(evidence) is str else json.dumps(evidence))
    before = list(world.messages)
    assert host.plan_refusal(directory, world.job, world) is None
    assert world.messages == before
    assert not (directory / "plan-refusal-notice.attempt.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"reason": "DO_NOT_LOG"},
        {"reason": ["clarification_required"]},
        {"task_id": "T-0008; DO_NOT_LOG"},
        {"space_id": ""},
        {"project": None},
    ],
)
def test_intake_accepts_only_a_known_reason_for_a_task(world, change):
    request = {"op": "notify_owner_plan_refused", "project": fresh.PROJECT,
               "task_id": "T-0008", "space_id": "mock-dm",
               "reason": "clarification_required", **change}
    with pytest.raises(IntakeRefused):
        world.gate.dispatch(request, 0)
    assert not world.messages


def test_intake_sends_plan_refusals_for_root_only(world):
    request = {"op": "notify_owner_plan_refused", "project": fresh.PROJECT,
               "task_id": "T-0008", "space_id": "mock-dm", "reason": "main_moved"}
    with pytest.raises(IntakeRefused):
        world.gate.dispatch(request, fresh.HERMES)
    assert not world.messages
    assert world.gate.dispatch(request, 0)["state"] == "sent"
    assert world.messages[-1][1].startswith("T-0008 (")


def test_poll_checks_both_a_new_hold_and_recorded_failure_evidence():
    source = Path(host.__file__).read_text()
    body = source[source.index("def poll("):]
    assert body.count("plan_refusal(directory, job, host)") == 2
