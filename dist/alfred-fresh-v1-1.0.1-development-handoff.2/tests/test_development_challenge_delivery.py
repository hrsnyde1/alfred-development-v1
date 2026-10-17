"""Protected local fixtures and mocked Photon only; no live sends or workers."""

import datetime as dt
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from developer_v1 import owner_grants as grants
from developer_v1 import stage_approval
from developer_v1 import trusted_intake_development as intake
from developer_v1.approval_transition import approval_request
from developer_v1.router import Denied
from fresh_v1 import host
from fresh_v1.handoffs import write_once
from fresh_v1.protected import protected_json
from tests.test_fresh_v1 import OWNER, SIDE, save

pytest_plugins = ["tests.test_fresh_v1"]


@pytest.mark.parametrize("caller", ["automatic", "administrator_cli"])
def test_existing_root_callers_wait_for_a_slow_valid_ack_without_retry(caller, capsys):
    class Socket:
        def __init__(self):
            self.posts = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, seconds):
            self.timeout = seconds

        def connect(self, path):
            self.path = path

        def sendall(self, body):
            self.posts.append(json.loads(body))

        def recv(self, maximum):
            if self.timeout < 20:
                raise TimeoutError("mock ACK arrives at 20 seconds")
            return b'{"ok":true,"state":"awaiting_native_owner_reply","challenge":"mock-reference","message_id":"mock-native-id"}\n'

    client = Socket()
    if caller == "automatic":
        adapter = host.Host({"intake_socket": "/mock/intake.sock"})
        with (
            patch.object(adapter, "guard"),
            patch.object(host.socket, "socket", return_value=client),
        ):
            result = adapter.intake({"op": "stage_development_approval"})
    else:
        argv = [
            "stage_approval.py",
            "--socket",
            "/mock/intake.sock",
            "--project",
            "fixture",
            "--task",
            "T-0042",
            "--worktree-root",
            "/mock/worktree",
            "--scope",
            "calculator.py",
            "--space-id",
            "mock-dm",
        ]
        with (
            patch.object(stage_approval.os, "geteuid", return_value=0),
            patch("sys.argv", argv),
            patch.object(stage_approval.socket, "socket", return_value=client),
        ):
            stage_approval.main()
        result = json.loads(capsys.readouterr().out)
    assert result["message_id"] == "mock-native-id" and client.timeout == 40
    assert len(client.posts) == 1


def test_interrupted_ack_publication_exposes_no_partial_receipt_or_index(ready):
    world, request, _ = ready
    rename = grants._rename_noreplace

    def crash(directory, source, destination):
        if destination.startswith("challenge-"):
            raise Interrupted()
        return rename(directory, source, destination)

    with patch.object(grants, "_rename_noreplace", crash), pytest.raises(Interrupted):
        stage(ready)
    assert (world.grants / grants._send_slot(request)).exists()
    assert not list(world.grants.glob("challenge-*.json"))
    assert not list(world.grants.glob("pending-*.json"))
    restart(ready, lambda *_: pytest.fail("no second transmission"))
    with pytest.raises(Denied, match="already attempted"):
        stage(ready)


def test_ack_publication_never_overwrites_existing_evidence(ready):
    world, _, _ = ready
    p = world.grants / "challenge-atomic-fixture.json"
    grants._write_delivery_record(world.grants, p.name, {"original": True})
    original = p.read_bytes()
    with pytest.raises(FileExistsError):
        grants._write_delivery_record(world.grants, p.name, {"replacement": True})
    assert p.read_bytes() == original and p.stat().st_nlink == 1


@pytest.fixture
def ready(world):
    world.submit()
    context = world.plan(world.job)
    root = world.worktrees / "fixture-root"
    root.mkdir(mode=0o700)
    inputs = world.gate.development_inputs("dev-v1-accept", "T-0003")
    request = approval_request(
        inputs.spec_raw,
        inputs.plan_raw,
        project="dev-v1-accept",
        task_id="T-0003",
        repository=inputs.repository,
        worktree_root=root,
        scope=context["scope"],
        spec_decoder=inputs.spec_decoder,
    )
    return world, request, inputs.plan_raw


def stage(ready):
    world, request, plan = ready
    return world.development_issuer.stage(
        request, plan_raw=plan, space_id="mock-dm", peer_uid=0
    )


def restart(ready, send):
    world, _, _ = ready
    world.development_issuer = grants.DevelopmentGrantIssuer(
        world.grants,
        owner_sender_id="mock-owner",
        sidecar_uid=9201,
        environment="staging",
        preview_sender=send,
    )
    return world.development_issuer


def owner_reply(request, native_id, timestamp):
    return {
        "messageId": "genuine-mock-owner-event",
        "direction": "inbound",
        "sender": {"id": "mock-owner"},
        "space": {"id": "mock-dm", "type": "dm"},
        "nativeReplyTargetGuid": native_id,
        "nativeIsForward": False,
        "content": {"type": "text", "text": grants._phrase(request)},
        "timestamp": dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).isoformat(),
    }


def test_intent_is_durable_before_send_and_receipt_commits_real_native_id(ready):
    world, request, _ = ready
    native_id = "mock-native-ack"

    def send(space, text):
        intent = grants._read(world.grants, grants._send_slot(request))
        assert intent["request"] == request and intent["space_id"] == space
        assert intent["challenge_text_sha256"] == grants._digest(text.encode())
        assert (
            intent["delivery_state"] == "uncertain_until_ack"
            and "message_id" not in intent
        )
        assert not list(world.grants.glob("challenge-*.json"))
        return native_id

    world.development_issuer.send = send
    result = stage(ready)
    receipt = grants._read(world.grants, f"challenge-{result['challenge']}.json")
    assert receipt["message_id"] == native_id == result["message_id"]
    assert receipt["send_attempt_sha256"] == grants._digest(
        grants._read(world.grants, grants._send_slot(request))
    )
    assert not list(world.grants.glob("grant-*.json"))


@pytest.mark.parametrize(
    "state,reason",
    [
        ("not_attempted", "connect_failed"),
        ("not_attempted", "http_preflight_refused"),
        ("uncertain", "provider_refused"),
        ("uncertain", "ack_timeout"),
        ("uncertain", "ack_invalid"),
    ],
)
def test_classified_failure_is_append_only_and_no_restart_resends(ready, state, reason):
    world, request, _ = ready
    sends = []

    def fail(space, text):
        sends.append(text)
        raise grants.DevelopmentSendFailure(state, reason)

    world.development_issuer.send = fail
    with pytest.raises(grants.DevelopmentSendFailure):
        stage(ready)
    intent = grants._read(world.grants, grants._send_slot(request))
    outcome = grants._read(
        world.grants, f"development-send-outcome-{intent['reference']}.json"
    )
    assert outcome["delivery_state"] == state and outcome["reason_code"] == reason
    assert outcome["send_attempt_sha256"] == grants._digest(intent)
    before = {p.name: p.read_bytes() for p in world.grants.iterdir()}
    restart(ready, fail)
    with pytest.raises(Denied, match="already attempted"):
        stage(ready)
    assert len(sends) == 1 and before == {
        p.name: p.read_bytes() for p in world.grants.iterdir()
    }
    assert not list(world.grants.glob("challenge-*.json"))
    assert not list(world.grants.glob("grant-*.json"))


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize(
    "point", ["before_send", "after_transmission", "after_native_ack"]
)
def test_process_interruption_never_resends_or_fabricates_a_receipt(ready, point):
    world, request, _ = ready
    transmissions = []

    def send(space, text):
        if point == "before_send":
            raise Interrupted()
        transmissions.append(text)
        if point == "after_transmission":
            raise Interrupted()
        return "mock-native-ack"

    world.development_issuer.send = send
    write = grants._write_delivery_record

    def crash(root, name, record):
        if point == "after_native_ack" and name.startswith("challenge-"):
            raise Interrupted()
        return write(root, name, record)

    with (
        patch.object(grants, "_write_delivery_record", crash),
        pytest.raises(Interrupted),
    ):
        stage(ready)
    intent = grants._read(world.grants, grants._send_slot(request))
    assert intent["delivery_state"] == "uncertain_until_ack"
    assert not list(world.grants.glob("challenge-*.json"))
    restart(ready, lambda *_: pytest.fail("interrupted send must not replay"))
    with pytest.raises(Denied, match="already attempted"):
        stage(ready)
    assert len(transmissions) == (0 if point == "before_send" else 1)


def test_crash_after_durable_ack_allows_real_native_reply_without_resending(ready):
    world, request, _ = ready
    clock = [100000.0]
    issuer = world.development_issuer
    issuer.clock = lambda: clock[0]
    queued = []

    def send(space, text):
        clock[0] += 3  # Owner replies while SDK acknowledgement is still pending.
        queued.append(owner_reply(request, "mock-native-ack", clock[0]))
        clock[0] += 17  # Valid ACK arrives after the old 2s timeout.
        return "mock-native-ack"

    issuer.send = send
    write = grants._write_delivery_record

    def crash(root, name, record):
        if name.startswith("pending-"):
            raise Interrupted()
        return write(root, name, record)

    with (
        patch.object(grants, "_write_delivery_record", crash),
        pytest.raises(Interrupted),
    ):
        stage(ready)
    receipt_path = next(world.grants.glob("challenge-*.json"))
    original = receipt_path.read_bytes()
    receipt = json.loads(original)
    assert receipt["issued_at"] == 100000 and receipt["expires_at"] == 100300
    assert not list(world.grants.glob("pending-*.json"))
    issuer = restart(ready, lambda *_: pytest.fail("confirmed ACK must not resend"))
    issuer.clock = lambda: clock[0]
    result = issuer.observe(queued[0], peer_uid=9201)
    assert result["state"] == "development_approved"
    assert receipt_path.read_bytes() == original
    with pytest.raises(Denied, match="already consumed"):
        issuer.observe(queued[0], peer_uid=9201)
    with pytest.raises(Denied, match="already attempted"):
        stage(ready)
    authority = grants.ProtectedDevelopmentAuthority(
        world.grants, clock=lambda: clock[0], environment="staging"
    )
    expected = {k: v for k, v in request.items() if k not in {"schema", "state"}}
    expected["schema"] = "alfred.development-grant/1"
    authority.claim(result["reference"], expected, run_sha256="a" * 64)
    with pytest.raises(Denied, match="already consumed"):
        authority.claim(result["reference"], expected, run_sha256="a" * 64)


def test_unacknowledged_intent_cannot_verify_a_native_reply(ready):
    world, request, _ = ready
    world.development_issuer.send = lambda *_: (_ for _ in ()).throw(
        TimeoutError("mock timeout")
    )
    with pytest.raises(TimeoutError):
        stage(ready)
    issuer = restart(ready, lambda *_: pytest.fail("no resend"))
    assert (
        issuer.observe(owner_reply(request, "invented-id", 100000), peer_uid=9201)[
            "state"
        ]
        == "not_development_approval"
    )
    assert not list(world.grants.glob("grant-*.json"))


@pytest.mark.parametrize("change", ["scope", "plan_sha256", "space_id"])
def test_task_slot_cannot_be_bypassed_by_changing_bindings(ready, change):
    world, request, plan = ready
    stage(ready)
    altered = dict(request)
    space = "mock-dm"
    if change == "space_id":
        space = "another-company-dm"
    elif change == "scope":
        altered[change] = ["another.py"]
    else:
        altered[change] = "f" * 64
    with pytest.raises(Denied, match="already attempted"):
        world.development_issuer.stage(
            altered, plan_raw=plan, space_id=space, peer_uid=0
        )


def test_wrong_caller_cannot_persist_a_send_intent(ready):
    world, request, plan = ready
    with pytest.raises(Denied, match="administrator"):
        world.development_issuer.stage(
            request, plan_raw=plan, space_id="mock-dm", peer_uid=9202
        )
    assert not (world.grants / grants._send_slot(request)).exists()


def test_failed_intent_persistence_is_proven_pre_send(ready):
    world, _, _ = ready
    before = {p.name: p.read_bytes() for p in world.grants.iterdir()}
    world.development_issuer.send = lambda *_: pytest.fail("must persist before send")
    with (
        patch.object(grants, "_write_once", side_effect=PermissionError("DO_NOT_LOG")),
        pytest.raises(grants.DevelopmentSendFailure) as error,
    ):
        stage(ready)
    assert error.value.delivery_state == "not_attempted"
    assert error.value.reason_code == "intent_unavailable"
    assert {p.name: p.read_bytes() for p in world.grants.iterdir()} == before


class Timer:
    def __init__(self, seconds, callback):
        self.seconds, self.callback = seconds, callback
        self.started = self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


@pytest.mark.parametrize(
    "case,state,code",
    [
        ("success", None, None),
        ("connect", "not_attempted", "connect_failed"),
        ("local_refusal", "not_attempted", "http_preflight_refused"),
        ("provider_refusal", "uncertain", "provider_refused"),
        ("timeout", "uncertain", "ack_timeout"),
        ("deadline", "uncertain", "ack_timeout"),
        ("missing_id", "uncertain", "ack_invalid"),
        ("malformed", "uncertain", "ack_invalid"),
    ],
)
def test_development_http_contract_has_one_post_and_no_tokens_in_outcomes(
    case, state, code
):
    timers, posts, shutdowns = [], [], []

    def timer(seconds, callback):
        t = Timer(seconds, callback)
        timers.append(t)
        return t

    conn = SimpleNamespace(
        sock=SimpleNamespace(shutdown=lambda *_: shutdowns.append(True)),
        connect=lambda: None,
        close=lambda: None,
        request=lambda *args: posts.append(args),
    )
    if case == "connect":
        conn.connect = lambda: (_ for _ in ()).throw(
            ConnectionRefusedError("token=DO_NOT_LOG")
        )
    status = (
        401 if case == "local_refusal" else (500 if case == "provider_refusal" else 200)
    )
    body = b'{"ok":true,"messageId":"mock-native-ack"}'
    if case == "provider_refusal":
        body = b'{"ok":false,"error_class":"target_not_allowed","error":"DO_NOT_LOG","retryable":false}'
    if case == "missing_id":
        body = b'{"ok":true,"messageId":null}'
    if case == "malformed":
        body = b"[]"

    def response():
        if case == "timeout":
            raise TimeoutError("token=DO_NOT_LOG")
        if case == "deadline":
            timers[0].callback()
        return SimpleNamespace(status=status, read=lambda _: body)

    conn.getresponse = response
    with (
        patch.object(intake.threading, "Timer", timer),
        patch.object(intake.http.client, "HTTPConnection", return_value=conn) as create,
    ):
        sender = intake._sidecar_preview_sender(
            8789, "DO_NOT_LOG", timeout=intake.DEVELOPMENT_SEND_TIMEOUT
        )
        if state is None:
            assert sender("mock-dm", "mock-text") == "mock-native-ack"
        else:
            with pytest.raises(grants.DevelopmentSendFailure) as error:
                sender("mock-dm", "mock-text")
            assert (
                error.value.delivery_state == state and error.value.reason_code == code
            )
            assert "DO_NOT_LOG" not in str(error.value)
    assert create.call_args.kwargs["timeout"] == 30
    assert len(posts) == (0 if case == "connect" else 1)
    assert timers[0].seconds == 30 and timers[0].started and timers[0].cancelled
    assert bool(shutdowns) == (case == "deadline")


def test_future_fresh_timeout_stays_held_without_replaying_the_challenge(world):
    world.submit()
    sends = []

    def uncertain(space, text):
        sends.append(text)
        raise grants.DevelopmentSendFailure("uncertain", "ack_timeout")

    world.development_issuer.send = uncertain
    assert world.tick()["state"] == "held"
    root = world.jobdir(world.job)
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert world.tick()["state"] == "held"
    assert len(sends) == 1
    assert before == {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}


def test_legacy_uncertain_handoff_without_new_intent_is_never_adopted_or_replayed(
    world,
):
    world.submit()
    context = world.plan(world.job)
    root = world.jobdir(world.job)
    write_once(root / "plan.result.json", context)
    write_once(
        root / "development-challenge.attempt.json",
        {
            "stage": "development-challenge",
            "status": "uncertain_until_result",
        },
    )
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    world.development_issuer.send = lambda *_: pytest.fail(
        "legacy operation must stay held"
    )
    assert world.tick()["state"] == "held"
    assert before == {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert not list(world.grants.glob("development-send-*.json"))


def test_two_intake_objects_cannot_race_a_second_post(ready):
    world, request, plan = ready
    first = world.development_issuer
    sends = []
    send = lambda *_: sends.append(True) or "mock-native-id"
    first.send = send
    second = restart(ready, send)
    barrier = threading.Barrier(2)
    write = grants._write_once

    def simultaneous(root, name, record):
        if name == grants._send_slot(request):
            barrier.wait(timeout=5)
        return write(root, name, record)

    def run(issuer):
        try:
            return issuer.stage(request, plan_raw=plan, space_id="mock-dm", peer_uid=0)[
                "state"
            ]
        except Denied:
            return "held"

    with (
        patch.object(grants, "_write_once", simultaneous),
        ThreadPoolExecutor(2) as pool,
    ):
        results = list(pool.map(run, [first, second]))
    assert sorted(results) == ["awaiting_native_owner_reply", "held"]
    assert sends == [True]


@pytest.mark.parametrize(
    "bad",
    [
        "wrong_owner",
        "wrong_dm",
        "forwarded",
        "unthreaded",
        "wrong_text",
        "expired",
        "receipt_binding",
    ],
)
def test_ack_only_reply_path_preserves_all_native_approval_guards(ready, bad):
    world, request, _ = ready
    issuer = world.development_issuer
    issuer.clock = lambda: 100000
    result = stage(ready)
    # Disposable ACK-only fixture, representing interruption before indexing.
    (world.grants / f"pending-{result['challenge']}.json").unlink()
    reply = owner_reply(request, result["message_id"], 100001)
    issuer.clock = lambda: 100002
    if bad == "wrong_owner":
        reply["sender"] = {"id": "other-company-owner"}
    elif bad == "wrong_dm":
        reply["space"] = {"id": "other-company-dm", "type": "dm"}
    elif bad == "forwarded":
        reply["nativeIsForward"] = True
    elif bad == "unthreaded":
        reply["nativeReplyTargetGuid"] = None
    elif bad == "wrong_text":
        reply["content"]["text"] += " altered"
    elif bad == "expired":
        issuer.clock = lambda: 100301
    else:
        p = world.grants / f"challenge-{result['challenge']}.json"
        r = json.loads(p.read_bytes())
        r["request"]["scope"] = ["another-company.py"]
        p.write_bytes(grants._bytes(r))
    if bad == "unthreaded":
        assert (
            issuer.observe(reply, peer_uid=9201)["state"] == "not_development_approval"
        )
    else:
        with pytest.raises(Denied):
            issuer.observe(reply, peer_uid=9201)
    assert not list(world.grants.glob("grant-*.json"))


@pytest.mark.parametrize("new_request", [False, True])
def test_existing_poll_skips_only_the_uncertain_challenge_without_mutating_it(
    world, new_request
):
    world.submit()
    context = world.plan(world.job)
    old = world.jobdir(world.job)
    write_once(old / "plan.result.json", context)
    write_once(
        old / "development-challenge.attempt.json",
        {
            "stage": "development-challenge",
            "status": "uncertain_until_result",
        },
    )
    before = {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()}
    if new_request:
        assert world.submit(identifier="new-owner-request") == "T-0004"
    save(world.gateway.gateway_dir / "v1-1-intake.json", {"owner_sender_id": OWNER})
    with (
        patch.object(host, "require_root"),
        patch.object(host, "root_directory"),
        patch.object(
            host,
            "protected_json",
            lambda p: protected_json(
                p, trusted_uid=os.geteuid(), trusted_root=world.root
            ),
        ),
        patch.object(host, "Host", return_value=world),
        patch.object(host.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=SIDE)),
        patch.object(
            world, "development_challenge", wraps=world.development_challenge
        ) as challenge,
    ):
        result = host.poll(world.policy_path)
    if new_request:
        assert result["state"] == "awaiting_development_approval"
        assert (
            challenge.call_count == 1
            and challenge.call_args.args[0]["task_id"] == "T-0004"
        )
    else:
        assert result["state"] == "held"
        challenge.assert_not_called()
    assert before == {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()}
    for name in ("T-0001", "T-0002"):
        assert (
            world.repo / ".dev/tasks" / (name + "-historical.md")
        ).read_text() == "preserve " + name
