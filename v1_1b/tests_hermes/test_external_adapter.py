"""Run with the pinned Hermes test environment; no SDK login or socket bind."""

import importlib.util
import os
from pathlib import Path

import pytest
from gateway.config import PlatformConfig

STAGED = Path(__file__).resolve().parents[1] / "staging" / "adapter" / "adapter.py"
SPEC = importlib.util.spec_from_file_location("plugins.platforms.photon.staged_adapter", STAGED)
assert SPEC and SPEC.loader
adapter_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter_module)


def test_external_mode_never_loads_project_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("PHOTON_SIDECAR_EXTERNAL", "true")
    monkeypatch.setenv("PHOTON_SIDECAR_TOKEN", "restricted-test-token")
    monkeypatch.setenv("PHOTON_PROJECT_ID", "must-not-use")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "must-not-use")
    monkeypatch.setattr(adapter_module, "load_project_credentials",
                        lambda: pytest.fail("project credentials loaded"))
    monkeypatch.setattr(adapter_module, "find_node_executable",
                        lambda _: pytest.fail("external mode resolved Node"))
    adapter = adapter_module.PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))
    assert adapter._external_sidecar is True
    assert adapter._autostart_sidecar is False
    assert adapter._project_id == adapter._project_secret == ""
    assert adapter._sidecar_token == "restricted-test-token"


@pytest.mark.asyncio
async def test_external_mode_does_not_stop_protected_sidecar(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("PHOTON_SIDECAR_EXTERNAL", "true")
    monkeypatch.setenv("PHOTON_SIDECAR_TOKEN", "restricted-test-token")
    monkeypatch.setattr(adapter_module, "load_project_credentials", lambda: ("", ""))
    monkeypatch.setattr(adapter_module, "find_node_executable",
                        lambda _: pytest.fail("external mode resolved Node"))
    adapter = adapter_module.PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))
    async def forbidden():
        pytest.fail("Hermes attempted to stop the protected sidecar")
    monkeypatch.setattr(adapter, "_stop_sidecar", forbidden)
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_external_text_and_ordinary_media_share_existing_sidecar(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("PHOTON_SIDECAR_EXTERNAL", "true")
    monkeypatch.setenv("PHOTON_SIDECAR_TOKEN", "restricted-test-token")
    spool = tmp_path / "media-spool"
    spool.mkdir()
    monkeypatch.setenv("PHOTON_HERMES_MEDIA_SPOOL", str(spool))
    monkeypatch.setattr(adapter_module.PhotonAdapter, "validate_media_delivery_path",
                        staticmethod(lambda path: path if os.path.isfile(path) else None))
    # This sandbox cannot wake asyncio's loop from a worker thread (the pinned
    # unmodified Hermes media tests stall the same way). Exercise the copy and
    # route synchronously here; the host thread hop remains an activation test.
    async def immediate(func, *args):
        return func(*args)
    monkeypatch.setattr(adapter_module.asyncio, "to_thread", immediate)
    adapter = adapter_module.PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))
    sent = []

    async def capture(route, body, **_kwargs):
        sent.append((route, body.copy()))
        if route == "/send-media":
            assert "path" not in body
            assert (spool / body["attachmentId"]).read_bytes() in (b"photo", b"voice", b"document")
        return adapter_module.SendResult(success=True, message_id="sdk-outbound")

    monkeypatch.setattr(adapter, "_post_send", capture)
    assert (await adapter._sidecar_send("owner-dm", "hello", richlink=False, markdown=False)).success
    for label, send in (
        ("photo", lambda path: adapter.send_image_file("owner-dm", str(path))),
        ("voice", lambda path: adapter.send_voice("owner-dm", str(path))),
        ("document", lambda path: adapter.send_document("owner-dm", str(path))),
    ):
        path = tmp_path / f"{label}.bin"
        path.write_bytes(label.encode())
        assert (await send(path)).success
        assert list(spool.iterdir()) == []
    assert [route for route, _ in sent] == ["/send", "/send-media", "/send-media", "/send-media"]
    assert all(body["spaceId"] == "owner-dm" for _, body in sent)


@pytest.mark.asyncio
async def test_external_media_never_falls_back_to_arbitrary_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("PHOTON_SIDECAR_EXTERNAL", "true")
    monkeypatch.setenv("PHOTON_SIDECAR_TOKEN", "restricted-test-token")
    monkeypatch.delenv("PHOTON_HERMES_MEDIA_SPOOL", raising=False)
    async def immediate(func, *args):
        return func(*args)
    monkeypatch.setattr(adapter_module.asyncio, "to_thread", immediate)
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"photo")
    monkeypatch.setattr(adapter_module.PhotonAdapter, "validate_media_delivery_path",
                        staticmethod(lambda value: value))
    adapter = adapter_module.PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))

    async def forbidden(*_args, **_kwargs):
        pytest.fail("restricted Hermes tried to call a protected media path route")

    monkeypatch.setattr(adapter, "_post_send", forbidden)
    assert (await adapter.send_image_file("owner-dm", str(path))).success is False


@pytest.mark.asyncio
async def test_external_standalone_text_and_media_use_restricted_route(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("PHOTON_SIDECAR_EXTERNAL", "true")
    monkeypatch.setenv("PHOTON_SIDECAR_TOKEN", "restricted-test-token")
    spool = tmp_path / "media-spool"
    spool.mkdir()
    monkeypatch.setenv("PHOTON_HERMES_MEDIA_SPOOL", str(spool))
    path = tmp_path / "document.txt"
    path.write_bytes(b"document")
    monkeypatch.setattr(adapter_module.BasePlatformAdapter, "validate_media_delivery_path",
                        staticmethod(lambda value: value if os.path.isfile(value) else None))
    async def immediate(func, *args):
        return func(*args)
    async def no_record(*_args):
        return None
    monkeypatch.setattr(adapter_module.asyncio, "to_thread", immediate)
    monkeypatch.setattr(adapter_module, "_record_sent_text_async", no_record)
    routes = []

    class Response:
        status_code = 200
        def json(self):
            return {"ok": True, "messageId": "outbound-id"}

    class Client:
        def __init__(self, **_kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False
        async def post(self, url, json, headers):
            routes.append(url.rsplit("/", 1)[-1])
            if routes[-1] == "send-media":
                assert "path" not in json
                assert (spool / json["attachmentId"]).read_bytes() == b"document"
            return Response()

    monkeypatch.setattr(adapter_module.httpx, "AsyncClient", Client)
    result = await adapter_module._standalone_send(
        PlatformConfig(enabled=True, token="", extra={}), "owner-dm", "hello",
        media_files=[(str(path), False)])
    assert result["success"] is True
    assert routes == ["send", "send-media"]
    assert list(spool.iterdir()) == []
