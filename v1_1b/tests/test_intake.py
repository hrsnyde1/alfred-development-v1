import hashlib
import errno
import importlib.util
import json
import os
import stat
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import intake
import pytest
import taskspec
import yaml
from alfred.gateway.dispatcher import GatewayConfig, run_once
from alfred.gateway.journal import Journal
from alfred.registry.loader import parse_registry
from trusted_intake import IntakeGate, IntakeRefused, _Handler

ROOT = Path(__file__).resolve().parents[2]
SIDE = 9201
HERMES = 9202
OWNER = "sdk-owner-id"


def world(tmp_path):
    repo = tmp_path / "home" / "Git" / "dev-001"
    shutil.copytree(ROOT / "v1_1a" / "fixture" / "dev-001", repo)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    data = yaml.safe_load((ROOT / "v1_1a" / "fixture" / "registry.template.yaml").read_text())
    data["projects"][0]["local_path"] = str(repo)
    registry = parse_registry(data)
    intake_dir = tmp_path / "home" / "Alfred" / "projects" / "hermes-requests"
    (intake_dir / "inbox").mkdir(parents=True)
    config = GatewayConfig(intake_dir, tmp_path / "gateway", tmp_path / "home", "2026-10-14")
    previews = []
    def send_preview(space, text):
        previews.append((space, text))
        return f"preview-{len(previews)}"
    gate = IntakeGate(owner_sender_id=OWNER, sidecar_uid=SIDE, hermes_uid=HERMES,
                      intake_dir=intake_dir, gateway_dir=config.gateway_dir,
                      preview_sender=send_preview)
    gate.test_previews = previews
    return gate, registry, config, repo


def event(message_id="sdk-001", sender=OWNER, text="Please build a small login fix", target=None):
    return {"messageId": message_id, "direction": "inbound", "sender": {"id": sender},
            "space": {"id": "sdk-dm", "type": "dm"},
            "content": {"type": "text", "text": text}, "timestamp": "2026-10-14T12:00:00Z",
            "nativeReplyTargetGuid": target, "nativeThreadOriginatorGuid": None,
            "nativeIsForward": False}


def draft():
    return {"title": "Build a small login fix", "task_type": "bugfix",
            "objective": "Fix the login path in dev-001.", "scope": "Only dev-001.",
            "requirements": "Keep existing behavior.", "constraints": "No production changes.",
            "acceptance_criteria": "- [ ] Login test passes",
            "security_considerations": "No credentials in output.",
            "testing_requirements": "Run focused unit tests."}


def prepare(gate, message, new_draft=None):
    return gate.dispatch({"op": "submit", "event_id": message["messageId"],
                          "text_digest": hashlib.sha256(message["content"]["text"].encode()).hexdigest(),
                          "draft": new_draft or draft()}, HERMES)


def confirm(gate, message, confirmation_id=None):
    response = event(confirmation_id or f"confirmation-{message['messageId']}",
                     text="Yes, go ahead", target=gate._active.preview_id)
    return gate.dispatch({"op": "observe", "event": response}, SIDE)


def submit(gate, message):
    result = prepare(gate, message)
    if result["state"] == "awaiting_confirmation":
        assert confirm(gate, message)["state"] == "submitted"
        return {"state": "submitted", "request_id": result["request_id"]}
    return result


def status(gate, message):
    return gate.dispatch({"op": "status", "event_id": message["messageId"],
                          "text_digest": hashlib.sha256(message["content"]["text"].encode()).hexdigest()}, HERMES)


def test_original_event_to_gateway_proposed_task(tmp_path):
    gate, registry, config, repo = world(tmp_path)
    message = event()
    assert gate.dispatch({"op": "observe", "event": message}, SIDE) == {"state": "observed"}
    result = submit(gate, message)
    assert result["state"] == "submitted"
    raw = json.loads((config.intake_dir / "inbox" / f"{result['request_id']}.json").read_text())
    assert stat.S_IMODE((config.intake_dir / "inbox" / f"{result['request_id']}.json").stat().st_mode) == 0o640
    assert raw["protocol"] == "alfred.devreq/1" and raw["project_hint"] == "dev-001"
    assert raw["utterance"] == message["content"]["text"]
    assert status(gate, message)["state"] == "submitted"
    report = run_once(registry, intake.IntakeFiler(), config)
    assert report.filed == ["T-0001"]
    assert status(gate, message)["task_id"] == "T-0001"
    assert status(gate, message)["task_id"] == "T-0001"
    (path,) = (repo / ".dev" / "tasks").glob("T-????-*.md")
    spec = taskspec.parse(path.read_text())
    assert (spec["status"], spec["project"], spec["source"]) == ("proposed", "dev-001", "hermes")
    assert spec["approved_by"] is None and spec["branch"] is None


def test_known_event_direct_ipc_can_only_request_preview(tmp_path):
    gate, registry, config, repo = world(tmp_path)
    message = event()
    gate.dispatch({"op": "observe", "event": message}, SIDE)
    result = prepare(gate, message)  # Exact ID, digest and Hermes UID, no tool turn proof.
    assert result["state"] == "awaiting_confirmation"
    assert gate.test_previews[0][0] == "sdk-dm"
    assert "Build a small login fix" in gate.test_previews[0][1]
    assert list((config.intake_dir / "inbox").iterdir()) == []
    assert run_once(registry, intake.IntakeFiler(), config).filed == []
    assert list((repo / ".dev" / "tasks").glob("T-????-*.md")) == []


@pytest.mark.parametrize("target,text,sender,space", [
    (None, "Yes, go ahead", OWNER, "sdk-dm"),
    ("wrong-preview", "Yes, go ahead", OWNER, "sdk-dm"),
    ("preview-1", "yes", OWNER, "sdk-dm"),
    ("preview-1", "Yes, go ahead", "other", "sdk-dm"),
    ("preview-1", "Yes, go ahead", OWNER, "other-dm"),
])
def test_unrelated_or_invalid_confirmation_never_files(tmp_path, target, text, sender, space):
    gate, _, config, _ = world(tmp_path)
    request = event()
    gate.dispatch({"op": "observe", "event": request}, SIDE)
    assert prepare(gate, request)["state"] == "awaiting_confirmation"
    reply = event("other-event", sender=sender, text=text, target=target)
    reply["space"]["id"] = space
    try:
        gate.dispatch({"op": "observe", "event": reply}, SIDE)
    except IntakeRefused as exc:
        assert exc.code == "confirmation_not_affirmative"
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_thread_fallback_and_model_claim_cannot_confirm(tmp_path):
    gate, _, config, _ = world(tmp_path)
    request = event()
    gate.dispatch({"op": "observe", "event": request}, SIDE)
    prepare(gate, request)
    reply = event("fallback", text="Yes, go ahead")
    reply["nativeThreadOriginatorGuid"] = gate._active.preview_id
    reply["content"]["targetMessageId"] = gate._active.preview_id
    assert gate.dispatch({"op": "observe", "event": reply}, SIDE)["state"] == "busy"
    replayed = event("fallback", text="Yes, go ahead", target=gate._active.preview_id)
    with pytest.raises(IntakeRefused, match="confirmation_reused"):
        gate.dispatch({"op": "observe", "event": replayed}, SIDE)
    with pytest.raises(IntakeRefused, match="wrong_peer"):
        gate.dispatch({"op": "observe", "event": event("forged", text="Yes, go ahead",
                                                         target=gate._active.preview_id)}, HERMES)
    with pytest.raises(IntakeRefused, match="unknown_operation"):
        gate.dispatch({"op": "confirm", "event_id": "sdk-001", "approved": True}, HERMES)
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_forwarded_or_unknown_native_forward_state_cannot_confirm(tmp_path):
    gate, _, config, _ = world(tmp_path)
    request = event()
    gate.dispatch({"op": "observe", "event": request}, SIDE)
    prepare(gate, request)
    for value in (True, None):
        reply = event(f"forward-{value}", text="Yes, go ahead", target=gate._active.preview_id)
        reply["nativeIsForward"] = value
        with pytest.raises(IntakeRefused, match="confirmation_unverified"):
            gate.dispatch({"op": "observe", "event": reply}, SIDE)
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_modified_draft_busy_slot_expiry_and_duplicate_confirmation(tmp_path):
    gate, registry, config, repo = world(tmp_path)
    now = [100.0]
    gate.clock = lambda: now[0]
    request = event()
    gate.dispatch({"op": "observe", "event": request}, SIDE)
    prepared = prepare(gate, request)
    with pytest.raises(IntakeRefused, match="request_conflict"):
        prepare(gate, request, draft() | {"objective": "Altered after preview"})
    other = event("overlap", text="Please fix another login issue")
    gate.dispatch({"op": "observe", "event": other}, SIDE)
    with pytest.raises(IntakeRefused, match="unverified_event"):
        prepare(gate, other)
    assert confirm(gate, request, "first-confirmation")["state"] == "submitted"
    assert gate.dispatch({"op": "observe", "event": event("first-confirmation", text="Yes, go ahead",
                                                       target="preview-1")}, SIDE)["state"] == "expired"
    assert gate.dispatch({"op": "observe", "event": event("second-confirmation", text="Yes, go ahead",
                                                       target="preview-1")}, SIDE)["state"] == "busy"
    assert run_once(registry, intake.IntakeFiler(), config).filed == ["T-0001"]
    assert status(gate, request)["task_id"] == "T-0001"
    assert len(list((repo / ".dev" / "tasks").glob("T-????-*.md"))) == 1
    assert prepared["request_id"]

    second = event("second", text="Please fix another login issue")
    gate.dispatch({"op": "observe", "event": second}, SIDE)
    prepare(gate, second)
    now[0] += 301
    with pytest.raises(IntakeRefused, match="confirmation_expired"):
        confirm(gate, second)
    assert len(list((config.intake_dir / "inbox").glob("*.json"))) <= 1


def test_preview_failure_fails_closed_and_late_reply_cannot_file(tmp_path):
    gate, _, config, _ = world(tmp_path)
    request = event()
    gate.dispatch({"op": "observe", "event": request}, SIDE)
    def failed_send(*_args):
        raise TimeoutError("uncertain send")
    gate.preview_sender = failed_send
    with pytest.raises(IntakeRefused, match="preview_unavailable"):
        prepare(gate, request)
    with pytest.raises(IntakeRefused, match="unverified_event"):
        prepare(gate, request)
    late = event("late", text="Yes, go ahead", target="unknown-preview")
    assert gate.dispatch({"op": "observe", "event": late}, SIDE)["state"] == "observed"
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_gate_restart_discards_unconfirmed_preview(tmp_path):
    gate, registry, config, _ = world(tmp_path)
    request = event()
    gate.dispatch({"op": "observe", "event": request}, SIDE)
    prepare(gate, request)
    preview_id = gate._active.preview_id
    restarted = IntakeGate(owner_sender_id=OWNER, sidecar_uid=SIDE, hermes_uid=HERMES,
                           intake_dir=config.intake_dir, gateway_dir=config.gateway_dir,
                           preview_sender=lambda *_: "fresh-preview")
    stale = event("stale-confirmation", text="Yes, go ahead", target=preview_id)
    assert restarted.dispatch({"op": "observe", "event": stale}, SIDE)["state"] == "observed"
    assert run_once(registry, intake.IntakeFiler(), config).filed == []
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_duplicate_delivery_and_conflicting_draft(tmp_path):
    gate, registry, config, repo = world(tmp_path)
    message = event()
    gate.dispatch({"op": "observe", "event": message}, SIDE)
    first = submit(gate, message)
    assert submit(gate, message) == first
    bad = draft() | {"objective": "Another objective"}
    with pytest.raises(IntakeRefused, match="request_conflict"):
        gate.dispatch({"op": "submit", "event_id": message["messageId"],
                       "text_digest": hashlib.sha256(message["content"]["text"].encode()).hexdigest(),
                       "draft": bad}, HERMES)
    assert run_once(registry, intake.IntakeFiler(), config).filed == ["T-0001"]
    assert gate.dispatch({"op": "observe", "event": message}, SIDE)["state"] == "submitted"
    assert len(list((repo / ".dev" / "tasks").glob("T-????-*.md"))) == 1


@pytest.mark.parametrize("bad", [event(sender="other"), event(sender=None),
                                 event(text="What is the weather?"), event(text="Please build this", message_id="")])
def test_non_owner_ordinary_and_incomplete_events_cannot_file(tmp_path, bad):
    gate, _, config, _ = world(tmp_path)
    result = None
    try:
        result = gate.dispatch({"op": "observe", "event": bad}, SIDE)
    except IntakeRefused:
        pass
    assert result is None or result["state"] in ("ignored", "observed")
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_peer_forgery_turn_substitution_and_malformed_draft(tmp_path):
    gate, _, config, _ = world(tmp_path)
    message = event()
    with pytest.raises(IntakeRefused, match="wrong_peer"):
        gate.dispatch({"op": "observe", "event": message}, HERMES)
    gate.dispatch({"op": "observe", "event": message}, SIDE)
    with pytest.raises(IntakeRefused, match="wrong_peer"):
        gate.dispatch({"op": "submit", "event_id": "sdk-001", "text_digest": "x", "draft": draft()}, SIDE)
    with pytest.raises(IntakeRefused, match="unverified_event"):
        gate.dispatch({"op": "submit", "event_id": "another", "text_digest": "x", "draft": draft()}, HERMES)
    with pytest.raises(IntakeRefused, match="invalid_draft"):
        gate.dispatch({"op": "submit", "event_id": "sdk-001",
                       "text_digest": hashlib.sha256(message["content"]["text"].encode()).hexdigest(),
                       "draft": draft() | {"status": "ready"}}, HERMES)
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_sender_fallback_and_group_event_never_authorize(tmp_path):
    gate, _, config, _ = world(tmp_path)
    fallback = event(sender=None)
    fallback["space"]["phone"] = OWNER
    group = event("group-msg")
    group["space"]["type"] = "group"
    outbound = event("outbound-msg")
    outbound["direction"] = "outbound"
    assert gate.dispatch({"op": "observe", "event": fallback}, SIDE)["state"] == "ignored"
    assert gate.dispatch({"op": "observe", "event": group}, SIDE)["state"] == "ignored"
    assert gate.dispatch({"op": "observe", "event": outbound}, SIDE)["state"] == "ignored"
    with pytest.raises(IntakeRefused, match="unverified_event"):
        submit(gate, fallback)
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_one_active_request(tmp_path):
    gate, _, _, _ = world(tmp_path)
    a, b = event("a"), event("b")
    assert gate.dispatch({"op": "observe", "event": a}, SIDE)["state"] == "observed"
    assert gate.dispatch({"op": "observe", "event": b}, SIDE)["state"] == "observed"
    assert prepare(gate, a)["state"] == "awaiting_confirmation"
    assert gate.dispatch({"op": "observe", "event": a}, SIDE)["state"] == "awaiting_confirmation"
    with pytest.raises(IntakeRefused, match="unverified_event"):
        prepare(gate, b)


def test_ordinary_owner_message_cannot_be_filed_by_a_tool_call(tmp_path):
    gate, registry, config, repo = world(tmp_path)
    ordinary = event("weather", text="What's the weather?")
    gate.dispatch({"op": "observe", "event": ordinary}, SIDE)
    with pytest.raises(IntakeRefused, match="not_development_request"):
        submit(gate, ordinary)
    assert run_once(registry, intake.IntakeFiler(), config).filed == []
    assert list((repo / ".dev" / "tasks").glob("T-????-*.md")) == []


def test_delayed_exact_owner_event_remains_eligible(tmp_path):
    gate, _, config, _ = world(tmp_path)
    first = event("first")
    later = event("later", text="Please fix the login page")
    gate.dispatch({"op": "observe", "event": first}, SIDE)
    gate.dispatch({"op": "observe", "event": later}, SIDE)
    assert prepare(gate, first)["state"] == "awaiting_confirmation"
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_observation_window_rejects_substitution_and_evicted_events(tmp_path):
    gate, _, config, _ = world(tmp_path)
    first = event("first")
    gate.dispatch({"op": "observe", "event": first}, SIDE)
    for index in range(15):
        gate.dispatch({"op": "observe", "event": event(f"later-{index}")}, SIDE)
    wrong_digest = hashlib.sha256(b"different text").hexdigest()
    with pytest.raises(IntakeRefused, match="unverified_event"):
        gate.dispatch({"op": "submit", "event_id": "first", "text_digest": wrong_digest,
                       "draft": draft()}, HERMES)
    with pytest.raises(IntakeRefused, match="event_conflict"):
        gate.dispatch({"op": "observe", "event": event("first", text="Please fix another app")}, SIDE)
    assert prepare(gate, first)["state"] == "awaiting_confirmation"
    assert list((config.intake_dir / "inbox").iterdir()) == []

    other_gate, _, _, _ = world(tmp_path / "other")
    other_gate.dispatch({"op": "observe", "event": first}, SIDE)
    for index in range(16):
        other_gate.dispatch({"op": "observe", "event": event(f"later-{index}")}, SIDE)
    with pytest.raises(IntakeRefused, match="unverified_event"):
        prepare(other_gate, first)
    assert other_gate.dispatch({"op": "observe", "event": first}, SIDE)["state"] == "expired"


def test_exact_nine_field_draft_matches_gateway_validator(tmp_path):
    gate, _, config, _ = world(tmp_path)
    message = event()
    gate.dispatch({"op": "observe", "event": message}, SIDE)
    valid = draft()
    assert len(valid) == 9
    for invalid in (dict(valid, extra="not allowed"),
                    {key: value for key, value in valid.items() if key != "scope"},
                    valid | {"task_type": "chore"},
                    valid | {"acceptance_criteria": "Login test passes"},
                    valid | {"title": "No"}):
        with pytest.raises(IntakeRefused, match="invalid_draft"):
            prepare(gate, message, invalid)
    assert prepare(gate, message, valid)["state"] == "awaiting_confirmation"
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_gateway_pickup_during_publication_keeps_single_link(monkeypatch, tmp_path):
    gate, registry, config, repo = world(tmp_path)
    message = event()
    gate.dispatch({"op": "observe", "event": message}, SIDE)
    from trusted_intake import _rename_noreplace
    import trusted_intake
    reports = []

    def interleave(directory, temporary, name):
        _rename_noreplace(directory, temporary, name)
        reports.append(run_once(registry, intake.IntakeFiler(), config))

    monkeypatch.setattr(trusted_intake, "_rename_noreplace", interleave)
    outcome = submit(gate, message)
    assert reports[0].filed == ["T-0001"]
    assert status(gate, message)["task_id"] == "T-0001"
    assert len(list((repo / ".dev" / "tasks").glob("T-????-*.md"))) == 1
    assert outcome["state"] == "submitted"


def test_scheduled_dispatcher_command_picks_up_once(tmp_path):
    gate, _, config, repo = world(tmp_path)
    message = event()
    gate.dispatch({"op": "observe", "event": message}, SIDE)
    submitted = submit(gate, message)
    registry_data = yaml.safe_load((ROOT / "v1_1a" / "fixture" /
                                    "registry.template.yaml").read_text())
    registry_data["projects"][0]["local_path"] = str(repo)
    registry_path = tmp_path / "projects.yaml"
    registry_path.write_text(yaml.safe_dump(registry_data))
    command = [sys.executable, str(Path("/home/alfred/Git/alfred/.dev/bin/gateway.py")),
               "run-once", "--intake-dir", str(config.intake_dir),
               "--gateway-dir", str(config.gateway_dir), "--registry", str(registry_path)]
    environment = os.environ | {"HOME": str(config.home), "PYTHONDONTWRITEBYTECODE": "1"}
    first = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert "filed          T-0001" in first.stdout
    assert status(gate, message)["task_id"] == "T-0001"
    second = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert "filed          " not in second.stdout
    assert len(list((repo / ".dev" / "tasks").glob("T-????-*.md"))) == 1
    assert submitted["request_id"]


def test_interruption_before_and_after_atomic_publication(monkeypatch, tmp_path):
    gate, registry, config, repo = world(tmp_path)
    message = event()
    gate.dispatch({"op": "observe", "event": message}, SIDE)
    import trusted_intake
    rename = trusted_intake._rename_noreplace

    def before(*_args):
        raise OSError(errno.EINTR, "interrupted before rename")

    monkeypatch.setattr(trusted_intake, "_rename_noreplace", before)
    with pytest.raises(OSError, match="interrupted"):
        submit(gate, message)
    assert list((config.intake_dir / "inbox").iterdir()) == []
    monkeypatch.setattr(trusted_intake, "_rename_noreplace", rename)
    fsync = os.fsync
    failed = False

    def after(fd):
        nonlocal failed
        if not failed and stat.S_ISDIR(os.fstat(fd).st_mode):
            failed = True
            raise OSError(errno.EINTR, "interrupted after rename")
        return fsync(fd)

    monkeypatch.setattr(trusted_intake.os, "fsync", after)
    with pytest.raises(OSError, match="interrupted"):
        submit(gate, message)
    assert len(list((config.intake_dir / "inbox").glob("*.json"))) == 1
    assert submit(gate, message)["state"] == "submitted"
    assert run_once(registry, intake.IntakeFiler(), config).filed == ["T-0001"]
    assert len(list((repo / ".dev" / "tasks").glob("T-????-*.md"))) == 1


def test_ordinary_chat_does_not_take_request_slot_and_expired_event_refused(tmp_path):
    gate, _, config, _ = world(tmp_path)
    now = [100.0]
    gate.clock = lambda: now[0]
    ordinary = event("chat-1", text="What is the weather?")
    request = event("dev-2", text="Could you look into the login problem?")
    assert gate.dispatch({"op": "observe", "event": ordinary}, SIDE)["state"] == "observed"
    assert gate.dispatch({"op": "observe", "event": request}, SIDE)["state"] == "observed"
    now[0] += 301
    with pytest.raises(IntakeRefused, match="expired_event"):
        submit(gate, request)
    assert list((config.intake_dir / "inbox").iterdir()) == []


def test_personal_alfred_tool_returns_real_gateway_id(monkeypatch, tmp_path):
    gate, registry, config, repo = world(tmp_path)
    message = event()
    gate.dispatch({"op": "observe", "event": message}, SIDE)
    path = ROOT / "v1_1b" / "plugin" / "__init__.py"
    spec = importlib.util.spec_from_file_location("staged_tool_e2e", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    origin = {"event_id": message["messageId"],
              "text_digest": hashlib.sha256(message["content"]["text"].encode()).hexdigest()}
    current = [origin]
    monkeypatch.setattr(tool, "_bound_origin", lambda: current[0])
    filed = False

    def call(request):
        nonlocal filed
        if request["op"] == "status" and not filed:
            assert run_once(registry, intake.IntakeFiler(), config).filed == ["T-0001"]
            filed = True
        return {"ok": True, **gate.dispatch(request, HERMES)}

    monkeypatch.setattr(tool, "_call", call)
    preview = json.loads(tool.development_gateway_submit(draft()))
    assert preview["state"] == "awaiting_confirmation"
    assert "original_request" in gate.test_previews[0][1]
    assert list((config.intake_dir / "inbox").iterdir()) == []
    confirmation = event("owner-confirmation", text="Yes, go ahead", target=gate._active.preview_id)
    assert gate.dispatch({"op": "observe", "event": confirmation}, SIDE)["state"] == "submitted"
    current[0] = {"event_id": confirmation["messageId"],
                  "text_digest": hashlib.sha256(confirmation["content"]["text"].encode()).hexdigest()}
    outcome = json.loads(tool.development_gateway_status({}))
    assert outcome["state"] == "filed" and outcome["task_id"] == "T-0001"
    assert len(list((repo / ".dev" / "tasks").glob("T-????-*.md"))) == 1


def test_later_owner_status_turn_gets_pending_then_real_id(tmp_path):
    gate, registry, config, _ = world(tmp_path)
    request = event()
    gate.dispatch({"op": "observe", "event": request}, SIDE)
    submit(gate, request)
    query = event("status-1", text="What is the filing status?")
    assert gate.dispatch({"op": "observe", "event": query}, SIDE)["state"] == "busy"
    assert status(gate, query)["state"] == "submitted"
    assert run_once(registry, intake.IntakeFiler(), config).filed == ["T-0001"]
    assert status(gate, query)["task_id"] == "T-0001"
    later = event("status-2", text="What happened with my request?")
    assert gate.dispatch({"op": "observe", "event": later}, SIDE)["state"] == "observed"
    assert status(gate, later)["task_id"] == "T-0001"


def test_gateway_rejection_releases_single_request_slot(tmp_path):
    gate, _, config, _ = world(tmp_path)
    first = event("first")
    gate.dispatch({"op": "observe", "event": first}, SIDE)
    submitted = submit(gate, first)
    config.gateway_dir.mkdir()
    Journal(config.gateway_dir / "journal.jsonl").record_outcome(
        request_id=submitted["request_id"], revision=1,
        outcome="rejected_invalid", reason="synthetic rejection")
    assert status(gate, first)["state"] == "rejected_invalid"
    second = event("second", text="Please investigate another login issue")
    assert gate.dispatch({"op": "observe", "event": second}, SIDE)["state"] == "observed"
    assert submit(gate, second)["state"] == "submitted"


def test_replayed_event_after_gate_restart_cannot_change_filed_draft(tmp_path):
    gate, registry, config, repo = world(tmp_path)
    message = event()
    gate.dispatch({"op": "observe", "event": message}, SIDE)
    submit(gate, message)
    assert run_once(registry, intake.IntakeFiler(), config).filed == ["T-0001"]
    restarted = IntakeGate(owner_sender_id=OWNER, sidecar_uid=SIDE, hermes_uid=HERMES,
                           intake_dir=config.intake_dir, gateway_dir=config.gateway_dir,
                           preview_sender=lambda *_: "new-preview")
    restarted.dispatch({"op": "observe", "event": message}, SIDE)
    with pytest.raises(IntakeRefused, match="previous_gateway_outcome"):
        submit(restarted, message)
    assert len(list((repo / ".dev" / "tasks").glob("T-????-*.md"))) == 1


def test_socket_ignores_claimed_peer_identity(tmp_path):
    gate, _, config, _ = world(tmp_path)
    gate.sidecar_uid = os.geteuid() + 1
    gate.hermes_uid = os.geteuid()
    path = tmp_path / "peer-test.sock"
    try:
        listener = socketserver.UnixStreamServer(str(path), _Handler)
    except OSError as exc:
        if exc.errno == errno.EPERM:
            pytest.skip("sandbox prevents Unix socket bind; OS peer test requires isolated acceptance")
        raise
    with listener as server:
        server.gate = gate
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(path))
            client.sendall((json.dumps({"op": "observe", "event": event(),
                                        "peer_uid": gate.sidecar_uid}) + "\n").encode())
            result = json.loads(client.recv(1024))
        thread.join(timeout=2)
    assert result == {"ok": False, "error": "wrong_peer"}
    assert list((config.intake_dir / "inbox").iterdir()) == []
