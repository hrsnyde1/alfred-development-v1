"""No live issuer or transport: isolated refusal phases and ambiguous-send guards."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from developer_v1 import trusted_intake_development as intake
from developer_v1.gateway_adapter import GatewayInputs
from developer_v1.router import Denied

pytest_plugins = ["tests.test_fresh_v1"]
ROOT = Path(__file__).resolve().parents[1]


def original_module():
    path = (
        ROOT / "dist/alfred-fresh-v1-1.0.1/developer_v1/trusted_intake_development.py"
    )
    spec = importlib.util.spec_from_file_location(
        "original_intake_failure_fixture", path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failure", ["timeout", "missing_id", "http_refusal"])
def test_original_refusal_cannot_disprove_delivery(world, failure):
    old = original_module()
    world.submit()
    context = world.plan(world.job)
    root = world.worktrees / "fixture-development-root"
    root.mkdir(mode=0o700)
    gate = old.IntakeGate.__new__(old.IntakeGate)
    gate.development_inputs = world.gate.development_inputs
    gate.development_issuer = world.development_issuer
    delivered = []

    def ambiguous(space, text):
        delivered.append(text)  # A mock owner received it before the ack failed.
        if failure == "timeout":
            raise TimeoutError("mock timeout")
        if failure == "http_refusal":
            raise OSError("protected preview send failed")

    gate.development_issuer.send = ambiguous
    with pytest.raises(old.IntakeRefused) as caught:
        gate.dispatch(
            {
                "op": "stage_development_approval",
                **world.job,
                "scope": context["scope"],
                "worktree_root": str(root),
            },
            0,
        )
    assert caught.value.code == "development_request_unavailable"
    assert len(delivered) == 1
    assert not list(world.grants.glob("challenge-*.json"))
    assert not list(world.grants.glob("grant-*.json"))


@pytest.mark.parametrize(
    "failure,kind,reason",
    [
        (TimeoutError("Bearer DO_NOT_LOG"), "TimeoutError", "unclassified"),
        (OSError("missing protected preview ID"), "OSError", "photon_receipt_missing"),
        (OSError("protected preview send failed"), "OSError", "photon_http_refused"),
    ],
)
def test_staged_issuer_failure_is_uncertain_redacted_and_never_retried(
    world, capsys, failure, kind, reason
):
    world.submit()
    calls = []

    def send(space, text):
        calls.append(text)
        raise failure

    world.development_issuer.send = send
    result = world.tick()
    assert result["state"] == "held"
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["phase"] == "issuer"
    assert diagnostic["delivery_state"] == "uncertain"
    assert diagnostic["exception_kind"] == kind and diagnostic["reason_code"] == reason
    assert (
        diagnostic["project"] == "dev-v1-accept" and diagnostic["task_id"] == "T-0003"
    )
    assert "DO_NOT_LOG" not in json.dumps(diagnostic)
    root = world.jobdir(world.job)
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert "development-challenge.attempt.json" in before
    assert "development-challenge.result.json" not in before
    assert world.tick()["state"] == "held"
    assert len(calls) == 1
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before
    assert not list(world.grants.glob("challenge-*.json"))


def test_gateway_refusal_is_precisely_before_issuer(world, capsys):
    world.submit()
    world.gate.development_inputs = lambda *_: (_ for _ in ()).throw(
        Denied("CTO plan failed schema validation")
    )
    with patch.object(world.development_issuer, "stage") as issuer:
        assert world.tick()["state"] == "held"
    issuer.assert_not_called()
    row = json.loads(capsys.readouterr().err)
    assert (
        row["phase"] == "gateway_inputs" and row["reason_code"] == "plan_schema_invalid"
    )
    assert row["delivery_state"] == "not_attempted"


def test_canonical_mismatch_is_before_issuer_without_changing_frozen_plan(
    world, capsys
):
    world.submit()
    load = world.gate.development_inputs

    def mismatch(*args):
        inputs = load(*args)
        plan = json.loads(inputs.plan_raw)
        plan["spec_sha256"] = "0" * 64
        return GatewayInputs(
            inputs.repository,
            inputs.spec_raw,
            json.dumps(plan).encode(),
            inputs.spec_decoder,
        )

    world.gate.development_inputs = mismatch
    with patch.object(world.development_issuer, "stage") as issuer:
        assert world.tick()["state"] == "held"
    issuer.assert_not_called()
    row = json.loads(capsys.readouterr().err)
    assert (
        row["phase"] == "approval_binding"
        and row["reason_code"] == "plan_spec_binding_mismatch"
    )
    assert row["delivery_state"] == "not_attempted"


@pytest.mark.parametrize("where", ["response_timeout", "null_receipt", "http_error"])
def test_real_sender_contract_preserves_timeout_and_does_not_retry(where):
    calls = []
    conn = SimpleNamespace(request=lambda *a: calls.append(a), close=lambda: None)
    response = SimpleNamespace(
        status=503 if where == "http_error" else 200,
        read=lambda _: b'{"ok":true,"messageId":null}',
    )
    conn.getresponse = lambda: response
    if where == "response_timeout":
        conn.getresponse = lambda: (_ for _ in ()).throw(TimeoutError("DO_NOT_LOG"))
    with (
        patch.object(
            intake.http.client, "HTTPConnection", return_value=conn
        ) as connection,
        pytest.raises(OSError),
    ):
        intake._sidecar_preview_sender(1234, "mock-token")("mock-space", "mock-text")
    assert connection.call_args.kwargs["timeout"] == 2
    assert len(calls) == 1


def test_logging_failure_does_not_remove_refusal_or_authorize_retry(world):
    world.submit()
    world.gate.development_inputs = lambda *_: (_ for _ in ()).throw(
        Denied("unknown DO_NOT_LOG")
    )
    with patch.object(
        intake.sys,
        "stderr",
        SimpleNamespace(write=lambda *_: (_ for _ in ()).throw(OSError())),
    ):
        assert world.tick()["state"] == "held"
    assert world.tick()["state"] == "held"
    assert not world.calls[1:]


def test_unknown_error_text_and_invalid_identity_are_never_logged():
    row = intake._development_failure(
        "issuer",
        {"project": "DO_NOT_LOG\n", "task_id": "DO_NOT_LOG"},
        ValueError("token=DO_NOT_LOG"),
    )
    assert "DO_NOT_LOG" not in json.dumps(row)
    assert row["reason_code"] == "unclassified" and row["delivery_state"] == "uncertain"
