"""Synthetic Hermes turn-context tests; no live Photon connection."""

import importlib.util
import asyncio
from contextvars import copy_context
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "staged_session_context", ROOT / "staging" / "hermes" / "gateway" / "session_context.py")
assert SPEC and SPEC.loader
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)


def source(message_id="one", sender="owner", platform="photon"):
    return SimpleNamespace(platform=SimpleNamespace(value=platform), profile="default",
                           user_id=sender, message_id=message_id)


def event(message_id="one", sender="owner", text="Please build it"):
    return SimpleNamespace(raw_message={"messageId": message_id,
                                        "direction": "inbound",
                                        "sender": {"id": sender},
                                        "content": {"type": "text", "text": text}},
                           text=text, internal=False)


def test_exact_event_is_task_local_and_cleared():
    a = context.admitted_development_origin(source(), event(), "session-a")
    b = context.admitted_development_origin(source("two"), event("two"), "session-a")
    assert a["event_id"] == "one" and b["event_id"] == "two"
    context.set_session_vars(development_origin=a)
    assert context.development_intake_origin()["event_id"] == "one"
    context.clear_session_vars([])
    assert context.development_intake_origin() is None
    context.set_session_vars(development_origin=b)
    assert context.development_intake_origin()["event_id"] == "two"
    context.reset_session_vars()
    assert context.development_intake_origin() is None


def test_fallback_identity_wrong_event_and_non_photon_rejected():
    assert context.admitted_development_origin(source(sender="fallback"), event(), "s") is None
    assert context.admitted_development_origin(source("two"), event(), "s") is None
    assert context.admitted_development_origin(source(platform="telegram"), event(), "s") is None
    invalid = event()
    invalid.raw_message["sender"] = {}
    assert context.admitted_development_origin(source(), invalid, "s") is None
    invalid = event()
    invalid.raw_message["direction"] = None
    assert context.admitted_development_origin(source(), invalid, "s") is None


def test_model_modified_text_is_not_authority():
    original = event()
    original.text = "Please file a different task"
    origin = context.admitted_development_origin(source(), original, "s")
    assert origin["text_digest"] == __import__("hashlib").sha256(b"Please build it").hexdigest()


def test_threaded_reply_binds_inner_message_text_not_target():
    original = event()
    original.raw_message["content"] = {"type": "reply", "targetMessageId": "unrelated",
                                       "content": {"type": "text", "text": "Please build it"}}
    origin = context.admitted_development_origin(source(), original, "s")
    assert origin["event_id"] == "one"
    assert origin["text_digest"] == __import__("hashlib").sha256(b"Please build it").hexdigest()


def test_queued_same_chat_turn_replaces_origin_and_revokes_delayed_copy():
    first = context.admitted_development_origin(source("weather"),
        event("weather", text="What's the weather?"), "same-chat")
    second = context.admitted_development_origin(source("development"),
        event("development", text="Please build a login fix"), "same-chat")
    context.set_session_vars(development_origin=first)
    delayed = copy_context()
    with context.bound_development_origin(second):
        assert context.development_intake_origin()["event_id"] == "development"
        assert delayed.run(context.development_intake_origin) is None
    assert context.development_intake_origin() is None
    context.clear_session_vars([])


def test_eventless_followup_cannot_inherit_earlier_owner_origin():
    first = context.admitted_development_origin(source(), event(), "same-chat")
    context.set_session_vars(development_origin=first)
    with context.bound_development_origin(None):
        assert context.development_intake_origin() is None
    assert context.development_intake_origin() is None
    context.clear_session_vars([])


def test_parallel_contexts_hold_distinct_owner_events():
    async def run(mid):
        claim = context.admitted_development_origin(source(mid), event(mid), "same-chat")
        context.set_session_vars(development_origin=claim)
        await asyncio.sleep(0)
        observed = context.development_intake_origin()["event_id"]
        context.clear_session_vars([])
        return observed

    async def both():
        return await asyncio.gather(run("a"), run("b"))

    assert asyncio.run(both()) == ["a", "b"]
