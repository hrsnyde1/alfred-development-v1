"""Execute the proposed adapter's exact binding methods without installing it."""

from __future__ import annotations

import ast
import asyncio
import contextvars
import logging
from pathlib import Path
from types import SimpleNamespace

import make_photon_patch


def _isolated_adapter_methods():
    original = (make_photon_patch.UPSTREAM / "plugins/platforms/photon/adapter.py").read_text()
    revised = make_photon_patch.adapter(original)
    assert "_task_a_handles" not in revised
    tree = ast.parse(revised)
    adapter = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PhotonAdapter")
    methods = [node for node in adapter.body if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
               and node.name in {"_on_inbound_line", "_sidecar_call", "_task_a_job_binding", "_process_message_background"}]
    assert len(methods) == 4
    base_source = Path("/home/alfred/.hermes/hermes-agent/gateway/platforms/base.py").read_text()
    base_tree = ast.parse(base_source)
    base_adapter = next(node for node in base_tree.body if isinstance(node, ast.ClassDef)
                        and node.name == "BasePlatformAdapter")
    drain_methods = [node for node in base_adapter.body if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                     and node.name in {"_spawn_drain_task", "_drain_after"}]
    assert len(drain_methods) == 2
    base = ast.ClassDef(name="BaseStub", bases=[], keywords=[], body=drain_methods, decorator_list=[])
    miniature = ast.ClassDef(name="MiniAdapter", bases=[ast.Name(id="BaseStub", ctx=ast.Load())],
                             keywords=[], body=methods, decorator_list=[])
    source = "from __future__ import annotations\n" + ast.unparse(base) + "\n" + ast.unparse(miniature)
    posts = []

    class Response:
        status_code = 200
        text = ""
        def json(self):
            return {"ok": True, "messageId": "stub"}

    class Client:
        def __init__(self, **_kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False
        async def post(self, url, *, json, headers):
            posts.append((url, json, headers))
            return Response()

    namespace = {"contextvars": contextvars, "asyncio": asyncio, "logging": logging,
                 "json": __import__("json"), "logger": logging.getLogger("task-a-test"),
                 "_task_a_reply_binding": contextvars.ContextVar("review_photon_binding", default=None),
                 "httpx": SimpleNamespace(AsyncHTTPTransport=lambda **_kw: object(), AsyncClient=Client)}
    exec(compile(source, "<reviewed patched adapter methods>", "exec"), namespace)
    async def base_process(self, event, _session_key):
        self.processed.append((event, namespace["_task_a_reply_binding"].get()))
    namespace["BaseStub"]._process_message_background = base_process
    instance = namespace["MiniAdapter"]()
    instance._task_a_socket = "/tmp/synthetic-only.sock"
    instance._http_client = object()
    instance._dedup = SimpleNamespace(is_duplicate=lambda _message: False)
    instance._note_upstream_activity = lambda: None
    instance._sidecar_url = lambda path: "http://task-a" + path
    instance._sidecar_headers = lambda: {}
    instance._active_sessions = {"same-space": asyncio.Event()}
    instance._pending_messages = {}
    instance._clear_session_guard = lambda _key: None
    instance._track_session_task = lambda _key, task: setattr(instance, "drain_task", task)
    instance._finish_session_task = lambda _key, _guard: None
    instance.processed = []
    return instance, posts


def test_overlapping_same_chat_turns_keep_original_handles():
    async def scenario():
        adapter, posts = _isolated_adapter_methods()
        gates = {"m1": asyncio.Event(), "m2": asyncio.Event()}
        tasks = []
        async def dispatch(event):
            async def delayed():
                await gates[event["messageId"]].wait()
                await adapter._sidecar_call("/send", {"spaceId": "same-space", "text": event["messageId"]})
            tasks.append(asyncio.create_task(delayed()))
        adapter._dispatch_inbound = dispatch
        for message, handle in (("m1", "handle-one"), ("m2", "handle-two")):
            await adapter._on_inbound_line(__import__("json").dumps(
                {"messageId": message, "handle": handle, "space": {"id": "same-space"}}))
        gates["m2"].set()
        await asyncio.sleep(0)
        gates["m1"].set()
        await asyncio.gather(*tasks)
        assert [(body["handle"], body["text"]) for _url, body, _headers in posts] == [
            ("handle-two", "m2"), ("handle-one", "m1")]
    asyncio.run(scenario())


def test_missing_or_mismatched_turn_context_is_denied():
    async def scenario():
        adapter, posts = _isolated_adapter_methods()
        try:
            await adapter._sidecar_call("/send", {"spaceId": "same-space", "text": "no context"})
        except RuntimeError as exc:
            assert "missing or mismatched" in str(exc)
        else:
            raise AssertionError("missing handle accepted")
        async def dispatch(_event):
            try:
                await adapter._sidecar_call("/send", {"spaceId": "other-space", "text": "mismatch"})
            except RuntimeError as exc:
                assert "missing or mismatched" in str(exc)
            else:
                raise AssertionError("destination substitution accepted")
        adapter._dispatch_inbound = dispatch
        await adapter._on_inbound_line('{"messageId":"m1","handle":"bound","space":{"id":"same-space"}}')
        assert posts == []
    asyncio.run(scenario())


def test_durable_retry_is_not_swallowed_by_legacy_message_dedup():
    async def scenario():
        adapter, posts = _isolated_adapter_methods()
        adapter._dedup = SimpleNamespace(is_duplicate=lambda _message: True)
        async def dispatch(event):
            await adapter._sidecar_call("/send", {"spaceId": "same-space", "text": event["messageId"]})
        adapter._dispatch_inbound = dispatch
        await adapter._on_inbound_line('{"messageId":"retry","handle":"exact","space":{"id":"same-space"}}')
        assert posts[0][1] == {"handle": "exact", "text": "retry"}
    asyncio.run(scenario())


def test_installed_gateway_drain_rebinds_queued_job_to_its_own_event():
    async def scenario():
        adapter, _ = _isolated_adapter_methods()
        second = SimpleNamespace(raw_message={"handle": "handle-two", "messageId": "m2",
                                                "space": {"id": "same-space"},
                                                "content": {"type": "text", "text": "second"}},
                                 source=SimpleNamespace(chat_id="same-space"),
                                 message_id="m2", text="second")
        first_context = adapter._task_a_job_binding(SimpleNamespace(
            raw_message={"handle": "handle-one", "messageId": "m1",
                         "space": {"id": "same-space"}, "content": {"type": "text", "text": "first"}},
            source=SimpleNamespace(chat_id="same-space"), message_id="m1", text="first"))
        assert first_context == ("handle-one", "same-space", "m1")
        binding = adapter._process_message_background.__globals__["_task_a_reply_binding"]
        token = binding.set(first_context)
        adapter._spawn_drain_task(second, "same-space")
        binding.reset(token)
        await adapter.drain_task
        assert adapter.processed == [(second, ("handle-two", "same-space", "m2"))]

        merged = SimpleNamespace(**{**vars(second), "text": "first\nsecond"})
        assert adapter._task_a_job_binding(merged) is None
        await adapter._process_message_background(merged, "same-space")
        assert len(adapter.processed) == 1
    asyncio.run(scenario())


def test_installed_in_band_followup_inherits_first_turn_binding():
    """Evidence of the remaining gap, not a passing authorization guarantee."""
    runner = Path("/home/alfred/.hermes/hermes-agent/gateway/run_turn.py").read_text()
    tree = ast.parse(runner)
    mixin = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "GatewayTurnMixin")
    followup = next(node for node in mixin.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "_run_agent_queued_followup")
    calls = [node for node in ast.walk(followup) if isinstance(node, ast.Call)]
    assert any(isinstance(call.func, ast.Attribute) and call.func.attr == "_run_agent" for call in calls)
    assert not any(isinstance(call.func, ast.Attribute) and call.func.attr == "set"
                   and isinstance(call.func.value, ast.Name)
                   and call.func.value.id == "_task_a_reply_binding" for call in calls)

    async def scenario():
        adapter, posts = _isolated_adapter_methods()
        binding = adapter._process_message_background.__globals__["_task_a_reply_binding"]
        token = binding.set(("handle-first", "same-space", "m1"))
        try:
            # This models the in-band await self._run_agent(...) call above:
            # there is no new adapter processing task that can rebind context.
            await adapter._sidecar_call("/send", {"spaceId": "same-space", "text": "response to m2"})
        finally:
            binding.reset(token)
        assert posts[0][1] == {"handle": "handle-first", "text": "response to m2"}
    asyncio.run(scenario())
