"""Linux Publisher contract, protected inputs and mocked existing Photon transport."""

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from jsonschema import ValidationError

from completion_integration import runtime
from completion_integration.delivery import DeliveryTracker, DeliveryTrackingError
from draft_pr_publisher.worker import canonical, result_record

FINAL = "89ba188f8a2f801d433a30c9c21363efb3e1043d"
URL = "https://github.com/hrsnyde1/alfred-dev-v1-acceptance/pull/1"


@pytest.fixture
def world(tmp_path):
    protected = tmp_path / "protected"
    protected.mkdir(mode=0o700)
    state = tmp_path / "delivery"
    state.mkdir(mode=0o700)
    DeliveryTracker(state).initialize()
    binding = {
        "project": "dev-v1-accept",
        "task_id": "T-0002",
        "destination": "hrsnyde1/alfred-dev-v1-acceptance",
        "base_branch": "main",
        "publication_branch": "alfred/dev-v1-accept/T-0002-89ba188f8a2f",
        "final_revision": FINAL,
    }
    plan = {
        "schema": "alfred.draft-pr-plan/1",
        **binding,
        "status": "READY_FOR_OWNER_AUTHORIZATION",
        "qa_report_sha256": "a" * 64,
        "review_report_sha256": "b" * 64,
    }
    plan_digest = hashlib.sha256(canonical(plan)).hexdigest()
    result = result_record(plan, plan_digest, "PUBLISHED_DRAFT", url=URL)
    authorization = {
        "schema": "alfred.github-draft-pr-authorization/1",
        **binding,
        "publication_plan_sha256": plan_digest,
        "decision": "approved",
        "purpose": "one_github_draft_pr",
        "owner_event_id": "mock-test-event-not-live-authority",
    }
    config = {
        "schema": "alfred.completion-config/1",
        "enabled": True,
        "binding": binding,
        "owner_sender_id": "mock-owner",
        "owner_space_id": "mock-owner-dm",
        "owner_github_login": "hrsnyde1",
        "owner_merge_attested": True,
        "state_directory": str(state),
    }
    objects = {
        "publication-plan": plan,
        "publication-result": result,
        "owner-authorization": authorization,
    }

    def save():
        for name, obj in objects.items():
            raw = canonical(obj)
            (protected / (name + ".json")).write_bytes(raw)
            (protected / (name + ".json")).chmod(0o640)
            config[name + "-sha256"] = hashlib.sha256(raw).hexdigest()
        (protected / "config.json").write_bytes(canonical(config))
        (protected / "config.json").chmod(0o640)

    save()
    pr = {
        "number": 1,
        "html_url": URL,
        "state": "closed",
        "draft": False,
        "merged": True,
        "merged_at": "2026-10-16T08:19:24Z",
        "merge_commit_sha": "596d91daf3311ad3aa0ee42e7220f699f58daf59",
        "merged_by": {"login": "hrsnyde1"},
        "head": {
            "sha": FINAL,
            "ref": binding["publication_branch"],
            "repo": {"full_name": binding["destination"]},
        },
        "base": {"ref": "main", "repo": {"full_name": binding["destination"]}},
    }
    get_pr = Mock(return_value=pr)
    send = Mock(return_value="mock-photon-message-id")
    factory = Mock(return_value=send)

    def run(**kwargs):
        return runtime.run(
            protected / "config.json",
            get_pr=get_pr,
            sender_factory=factory,
            paused_check=kwargs.pop("paused_check", lambda: True),
            trusted_uid=os.geteuid(),
            trusted_root=protected,
            **kwargs,
        )

    return locals()


def test_actual_publisher_schema_matches_bundled_schema():
    root = Path(__file__).resolve().parents[1]
    assert (
        root / "completion_integration/publication-result.schema.json"
    ).read_bytes() == (
        root / "draft_pr_publisher/schemas/publication-result.schema.json"
    ).read_bytes()


def test_merged_owner_wording_requires_both_readback_and_attestation(world):
    text = world["run"]()["text"]
    assert "You merged it on GitHub" in text
    assert "draft for your review" not in text
    assert "isn't live until it's deployed" in text
    world["factory"].assert_not_called()
    world["config"]["owner_merge_attested"] = False
    world["save"]()
    text = world["run"]()["text"]
    assert "You merged it" not in text and "merged by hrsnyde1" in text
    world["config"]["owner_merge_attested"] = True
    world["pr"]["merged_by"]["login"] = "another-owner"
    world["save"]()
    text = world["run"]()["text"]
    assert "You merged it" not in text and "merged by another-owner" in text


@pytest.mark.parametrize(
    "state,draft,expected",
    [
        ("open", True, "as a draft for your review. Nothing is live yet"),
        ("open", False, "ready for your review. Nothing is live yet"),
        ("closed", False, "closed without merging"),
    ],
)
def test_current_pr_status_controls_wording(world, state, draft, expected):
    world["pr"].update(state=state, draft=draft, merged=False, merged_at=None)
    assert expected in world["run"]()["text"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("status", "ERROR"),
        ("schema", "requester-outbox/1"),
        ("next_stage", "publication_investigation"),
        ("detail", "push failed"),
        ("commit", "c" * 40),
        ("destination", "attacker/repository"),
        ("draft_pr_url", URL + "?query=1"),
        ("qa_report_sha256", "c" * 64),
        ("publication_plan_sha256", "d" * 64),
    ],
)
def test_non_success_or_mismatched_result_cannot_notify_even_if_repinned(
    world, key, value
):
    world["result"][key] = value
    world["save"]()
    with pytest.raises((ValueError, ValidationError)):
        world["run"](send=True)
    world["get_pr"].assert_not_called()
    world["send"].assert_not_called()


def test_separate_authorization_cannot_be_replaced_by_development_grant(world):
    world["authorization"]["purpose"] = "development"
    world["save"]()
    with pytest.raises(ValueError, match="authorization"):
        world["run"](send=True)
    world["send"].assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("head", None),
        ("base", {}),
        ("number", 2),
        ("html_url", "https://github.com/attacker/repo/pull/1"),
        ("merged_by", None),
        ("state", "open"),
        ("draft", True),
        ("merge_commit_sha", None),
    ],
)
def test_invalid_github_readback_never_sends(world, field, value):
    world["pr"][field] = value
    with pytest.raises(ValueError):
        world["run"](send=True)
    world["send"].assert_not_called()


def test_receipt_persists_and_restart_does_not_resend(world):
    assert world["run"](send=True)["status"] == "sent"
    assert world["run"](send=True)["status"] == "already_sent"
    world["send"].assert_called_once()
    record = next(
        iter(
            json.loads((world["state"] / "delivery.json").read_text())[
                "records"
            ].values()
        )
    )
    assert record["receipt_id"] == "mock-photon-message-id"


def test_timeout_and_restart_preserve_uncertainty(world):
    world["send"].side_effect = TimeoutError("mock possible send")
    with pytest.raises(TimeoutError):
        world["run"](send=True)
    assert world["run"](send=True)["status"] == "uncertain"
    world["send"].assert_called_once()


def test_changed_pr_status_cannot_generate_second_publication_notice(world):
    world["pr"].update(merged=False, merged_at=None, state="open", draft=True)
    assert world["run"](send=True)["status"] == "sent"
    world["pr"].update(
        merged=True, merged_at="2026-10-16T08:19:24Z", state="closed", draft=False
    )
    with pytest.raises(DeliveryTrackingError, match="content changed"):
        world["run"](send=True)
    world["send"].assert_called_once()


def test_disabled_and_paused_flows_cannot_send(world):
    world["config"]["enabled"] = False
    world["save"]()
    assert world["run"]()["status"] == "PREVIEW"
    with pytest.raises(ValueError, match="disabled"):
        world["run"](send=True)
    with pytest.raises(ValueError, match="PAUSE"):
        world["run"](paused_check=lambda: False)
    world["send"].assert_not_called()


def test_pause_arriving_before_callback_leaves_conservative_uncertainty(world):
    with pytest.raises(ValueError, match="PAUSE"):
        world["run"](send=True, paused_check=Mock(side_effect=[True, False]))
    assert world["run"](send=True)["status"] == "uncertain"
    world["send"].assert_not_called()


def test_github_failure_is_retryable_before_any_delivery_attempt(world):
    world["get_pr"].side_effect = TimeoutError
    with pytest.raises(TimeoutError):
        world["run"](send=True)
    assert json.loads((world["state"] / "delivery.json").read_text())["records"] == {}
    world["get_pr"].side_effect = None
    assert world["run"](send=True)["status"] == "sent"


@pytest.mark.parametrize("attack", ["hash", "symlink", "permissions", "duplicate-key"])
def test_untrusted_input_is_rejected(world, attack):
    path = world["protected"] / "publication-result.json"
    if attack == "hash":
        path.write_text("{}")
    elif attack == "symlink":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    elif attack == "permissions":
        path.chmod(0o666)
    else:
        path.write_text('{"status":"ERROR","status":"PUBLISHED_DRAFT"}')
    with pytest.raises((ValueError, OSError)):
        world["run"](send=True)
    world["send"].assert_not_called()


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"ok": True, "messageId": "mock-receipt"}, 200),
        ({"ok": True, "messageId": None}, 200),
        ({"ok": False, "messageId": "mock-receipt"}, 200),
        ({"ok": True, "messageId": "mock-receipt"}, 500),
    ],
)
def test_existing_photon_contract_with_mock_http(world, payload, status):
    notification = Mock(text="mock completion text")
    response = Mock(status=status)
    response.read.return_value = json.dumps(payload).encode()
    connection = Mock()
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    sender = runtime.PhotonSender(
        port=8789, token="mock-token", space_id="mock-owner-dm", connection=factory
    )
    if status == 200 and payload["ok"] is True and payload["messageId"]:
        assert sender(notification) == "mock-receipt"
    else:
        with pytest.raises(ValueError):
            sender(notification)
    args = connection.request.call_args.args
    assert args[:2] == ("POST", "/send")
    assert json.loads(args[2]) == {
        "spaceId": "mock-owner-dm",
        "text": notification.text,
        "format": "text",
    }
    assert args[3]["x-hermes-sidecar-token"] == "mock-token"
    connection.close.assert_called_once()


def test_github_adapter_has_only_exact_read_endpoint():
    result = Mock(returncode=0, stdout=b'{"number":1}')
    with patch.object(runtime.subprocess, "run", return_value=result) as run:
        assert runtime.github_pr("hrsnyde1/alfred-dev-v1-acceptance", 1) == {
            "number": 1
        }
    args = run.call_args.args[0]
    assert args == [
        "/usr/bin/gh",
        "api",
        "--hostname",
        "github.com",
        "--method",
        "GET",
        "repos/hrsnyde1/alfred-dev-v1-acceptance/pulls/1",
    ]


def test_transport_reuses_private_intake_config_and_checks_owner(world):
    private = world["tmp_path"] / "intake.json"
    private.write_text(
        json.dumps(
            {
                "owner_sender_id": "mock-owner",
                "sidecar_port": 8789,
                "sidecar_token": "mock-transport-token",
            }
        )
    )
    private.chmod(0o600)
    with patch.object(runtime, "INTAKE_CONFIG", private):
        sender = runtime.photon_sender(world["config"])
        assert sender.space_id == "mock-owner-dm"
        world["config"]["owner_sender_id"] = "different-owner"
        with pytest.raises(ValueError, match="routing mismatch"):
            runtime.photon_sender(world["config"])


def test_original_mac_state_remains_valid_and_suppresses_delivery(world):
    assert world["run"](send=True)["status"] == "sent"
    path = world["state"] / "delivery.json"
    state = json.loads(path.read_bytes())
    for record in state["records"].values():
        record.pop("receipt_id")
    path.write_text(json.dumps(state))
    assert world["run"](send=True)["status"] == "already_sent"
    world["send"].assert_called_once()
