"""Generate the review-only Photon source patch against exact installed bytes.

This reads installed source but writes only inside this Task A staging tree.
It does not apply the patch or change a running service.
"""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
UPSTREAM = Path("/home/alfred/.hermes/hermes-agent")
TARGETS = {
    "plugins/platforms/photon/sidecar/index.mjs": "bf9cae8ff7bdd1c9e00cbcb0a4a3b56f4f9c10bfd0ab14f20a71055a4f049284",
    "plugins/platforms/photon/adapter.py": "5c5a22ba2a6227514f0b6268d82cb1f6903cd76315d8a0e3d2376ced48c3999e",
}


def change(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"expected exactly one upstream anchor: {old[:80]!r}")
    return source.replace(old, new, 1)


def sidecar(source: str) -> str:
    # The protected unit's journal must not contain SDK error text, stack
    # traces, principals, credentials or message bodies.
    source = change(source,
                    '"photon-sidecar: failed to mark inbound message read: " +\n        (error?.message || String(error))',
                    '"photon-sidecar: read receipt failed"')
    source = change(source,
                    '    await message.read();',
                    '    await Promise.race([message.read(), new Promise((_, reject) =>\n      setTimeout(() => reject(new Error("read receipt deadline")), 3000))]);')
    source = change(source,
                    '  if (!readReceiptsEnabled) return;\n  if (message?.content?.type === "read") return;\n  if (typeof message?.read !== "function") return;',
                    '  if (!readReceiptsEnabled) return true;\n  if (message?.content?.type === "read") return true;\n  if (typeof message?.read !== "function") return true;')
    source = change(source,
                    '      setTimeout(() => reject(new Error("read receipt deadline")), 3000))]);\n  } catch (error) {',
                    '      setTimeout(() => reject(new Error("read receipt deadline")), 3000))]);\n    return true;\n  } catch (error) {')
    source = change(source,
                    '"photon-sidecar: read receipt failed"\n    );\n  }',
                    '"photon-sidecar: read receipt failed"\n    );\n    return false;\n  }')
    source = change(source,
                    '"photon-sidecar: failed to normalize inbound message: " + String(e)',
                    '"photon-sidecar: inbound normalization failed"')
    source = change(source,
                    '"photon-sidecar: inbound normalization failed"\n    );\n    return null;',
                    '"photon-sidecar: inbound normalization failed"\n    );\n    return { deliveryError: "normalization" };')
    source = change(source,
                    'console.error(inboundStreamErrorMessage(e));',
                    'console.error("photon-sidecar: inbound stream failed; recovery scheduled");')
    source = change(source,
                    '"photon-sidecar: handler error: " +\n        (e && e.stack ? e.stack : String(e))',
                    '"photon-sidecar: private handler failed"')
    source = change(source,
                    '"photon-sidecar: app.stop() failed: " + String(e)',
                    '"photon-sidecar: SDK shutdown failed"')
    source = change(source,
                    '"photon-sidecar: unhandledRejection: " +\n      (reason && reason.stack ? reason.stack : String(reason))',
                    '"photon-sidecar: unhandled rejection"')
    source = change(source,
                    '  if (typeof content.read === "function") {',
                    '  if (typeof content.read === "function" && !process.env.PHOTON_EVENT_SPOOL) {')
    source = change(source,
                    '// Spawned by `plugins/platforms/photon/adapter.py` to bridge BOTH directions',
                    '// Launched by the protected Photon service to bridge BOTH directions')
    source = change(source,
                    '//   loopback `GET /inbound` (NDJSON). We pause pulling from the stream while',
                    '//   private Unix `GET /inbound` (NDJSON). We pause pulling while')
    source = change(source,
                    '// Protocol (all requests require `X-Hermes-Sidecar-Token: ${TOKEN}`):',
                    '// Protected-only protocol (Unix socket plus private bearer token):')
    source = change(source,
                    '//   PHOTON_SIDECAR_PORT\n//   PHOTON_SIDECAR_TOKEN\n// Optional:\n//   PHOTON_SIDECAR_BIND    (default 127.0.0.1)',
                    '//   PHOTON_PRIVATE_SOCKET  (/run/alfred-photon-intake/private.sock)\n//   PHOTON_SIDECAR_TOKEN\n// Optional:')
    source = change(source, 'import http from "node:http";', 'import http from "node:http";\nimport fs from "node:fs";\nimport path from "node:path";')
    spool_code = (ROOT / "patches/photon-durable-spool.mjs.txt").read_text().rstrip()
    source = change(source,
                    '// ---------------------------------------------------------------------------\n// Inbound: forward `app.messages` (gRPC stream) to the Python consumer.',
                    spool_code + '\n\n// ---------------------------------------------------------------------------\n// Inbound: forward `app.messages` (gRPC stream) to the Python consumer.')
    source = change(source,
                    '    try {\n      for await (const [space, message] of app.messages) {',
                    '    try {\n      await replayPendingDeliveries();\n      for await (const [space, message] of app.messages) {')
    source = change(source,
                    '        await deliver(JSON.stringify(event));\n        await acknowledgeInboundRead(message);',
                    '        let record;\n        try { record = persistDelivery(event, message); }\n        catch { console.error("photon-sidecar: durable event acceptance unavailable"); process.exit(70); }\n        await deliverUntilAck(record);')
    source = change(source,
                    '    const body = await readBody(req);\n    if (req.url === "/send") {',
                    '    const body = await readBody(req);\n    if (req.url === "/ack") return acknowledgeDelivery(body, res);\n    if (req.url === "/send") {')
    source = change(source,
                    'const port = parseInt(process.env.PHOTON_SIDECAR_PORT || "8789", 10);\nconst bind = process.env.PHOTON_SIDECAR_BIND || "127.0.0.1";',
                    'const privateSocket = process.env.PHOTON_PRIVATE_SOCKET;\nif (!privateSocket || !path.isAbsolute(privateSocket)) {\n  throw new Error("absolute protected Photon socket path required");\n}\nconst privateParent = fs.lstatSync(path.dirname(privateSocket));\nif (!privateParent.isDirectory() || privateParent.uid !== process.getuid() || (privateParent.mode & 0o022) !== 0) {\n  throw new Error("unsafe protected Photon socket directory");\n}')
    start = source.index('    if (req.url === "/send-attachment") {')
    end = source.index('    if (req.url === "/react") {', start)
    source = source[:start] + source[end:]
    source = change(source,
                    'server.listen(port, bind, () => {\n  console.error(`photon-sidecar: listening on ${bind}:${port}`);\n});',
                    'process.umask(0o077); // socket is private from bind, before chmod callback\nserver.listen(privateSocket, () => {\n  fs.chmodSync(privateSocket, 0o600);\n  console.error("photon-sidecar: protected Unix socket ready");\n});')
    source = change(source,
                    '  server.close(() => process.exit(0));',
                    '  server.close(() => {\n    try { fs.unlinkSync(privateSocket); } catch { /* protected runtime cleanup */ }\n    fs.closeSync(spoolFd);\n    process.exit(0);\n  });')
    source = change(source,
                    '//   - POST /send-attachment -> {"ok": true, "messageId": "..."}\n//       body: {"spaceId": "...", "path": "...", "name": "..." | null,\n//              "mimeType": "..." | null, "caption": "..." | null,\n//              "kind": "attachment" | "voice"}\n',
                    '//   - /send-attachment is removed in the protected Task A candidate.\n')
    return source


def adapter(source: str) -> str:
    source = change(source, 'import asyncio\nimport base64', 'import asyncio\nimport contextvars\nimport base64')
    source = change(source, 'logger = logging.getLogger(__name__)',
                    'logger = logging.getLogger(__name__)\n_task_a_reply_binding = contextvars.ContextVar("photon_task_a_reply_binding", default=None)')
    source = change(source,
                    '    can_prepare = lazy_installs_allowed()\n    if not HTTPX_AVAILABLE:',
                    '    if _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET"):\n        return HTTPX_AVAILABLE\n    can_prepare = lazy_installs_allowed()\n    if not HTTPX_AVAILABLE:')
    source = change(source,
                    'def validate_config(cfg: PlatformConfig) -> bool:\n    extra = cfg.extra or {}',
                    'def validate_config(cfg: PlatformConfig) -> bool:\n    if _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET"):\n        return True\n    extra = cfg.extra or {}')
    source = change(source,
                    '    project_id, project_secret = load_project_credentials()\n    if not (project_id and project_secret):',
                    '    if _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET"):\n        return {"task_a_broker_socket": _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET")}\n    project_id, project_secret = load_project_credentials()\n    if not (project_id and project_secret):')
    source = change(source,
                    '        # Project credentials: env wins, then config.extra, then auth.json.\n        stored_id, stored_sec = load_project_credentials()',
                    '        # Secure Task A mode never loads Photon credentials into Hermes.\n        self._task_a_socket = _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET") or None\n        stored_id, stored_sec = ("", "") if self._task_a_socket else load_project_credentials()')
    source = change(source,
                    '        self._project_id: str = _get_scoped_secret("PHOTON_PROJECT_ID") or extra.get("project_id") or stored_id or ""\n        self._project_secret: str = (\n            _get_scoped_secret("PHOTON_PROJECT_SECRET") or extra.get("project_secret") or stored_sec or "")',
                    '        self._project_id: str = "" if self._task_a_socket else (_get_scoped_secret("PHOTON_PROJECT_ID") or extra.get("project_id") or stored_id or "")\n        self._project_secret: str = "" if self._task_a_socket else (\n            _get_scoped_secret("PHOTON_PROJECT_SECRET") or extra.get("project_secret") or stored_sec or "")')
    source = change(source,
                    '        self._sidecar_token = _get_scoped_secret("PHOTON_SIDECAR_TOKEN") or secrets.token_hex(16)',
                    '        self._sidecar_token = "" if self._task_a_socket else (_get_scoped_secret("PHOTON_SIDECAR_TOKEN") or secrets.token_hex(16))')
    source = change(source,
                    '        self._autostart_sidecar = autostart not in ("0", "false", "no")',
                    '        self._autostart_sidecar = not self._task_a_socket and autostart not in ("0", "false", "no")')
    source = change(source,
                    '        self._probe_enabled = self._probe_interval > 0',
                    '        self._probe_enabled = not self._task_a_socket and self._probe_interval > 0')
    source = change(source,
                    '        return f"http://{self._sidecar_bind}:{self._sidecar_port}{path}"',
                    '        return f"http://task-a{path}" if self._task_a_socket else f"http://{self._sidecar_bind}:{self._sidecar_port}{path}"')
    source = change(source,
                    '        return {"X-Hermes-Sidecar-Token": self._sidecar_token}',
                    '        return {} if self._task_a_socket else {"X-Hermes-Sidecar-Token": self._sidecar_token}')
    source = change(source,
                    '        if not self._project_id or not self._project_secret:\n            self._set_fatal_error(',
                    '        if not self._task_a_socket and (not self._project_id or not self._project_secret):\n            self._set_fatal_error(')
    source = change(source,
                    '        client = httpx.AsyncClient(timeout=30.0, trust_env=False)\n        self._http_client = client',
                    '        transport = httpx.AsyncHTTPTransport(uds=self._task_a_socket) if self._task_a_socket else None\n        client = httpx.AsyncClient(transport=transport, timeout=30.0, trust_env=False)\n        self._http_client = client\n        if self._task_a_socket:\n            try:\n                await self._sidecar_call("/healthz", {})\n            except Exception as exc:\n                self._set_fatal_error("TASK_A_BROKER_FAILED", f"restricted broker unavailable: {exc}", retryable=True)\n                await client.aclose()\n                self._http_client = None\n                return False')
    source = change(source,
                    '        if self._autostart_sidecar:  # the sidecar holds the gRPC stream for BOTH directions: required now',
                    '        if self._autostart_sidecar:  # legacy mode only; Task A owns the single protected stream')
    source = change(source,
                    '        else:\n            logger.warning("[photon] sidecar autostart disabled — inbound + outbound will fail")',
                    '        elif not self._task_a_socket:\n            logger.warning("[photon] sidecar autostart disabled — inbound + outbound will fail")')
    source = change(source,
                    '        await self._stop_sidecar()\n        if self._http_client is not None:',
                    '        if not self._task_a_socket:\n            await self._stop_sidecar()\n        if self._http_client is not None:')
    source = change(source,
                    '        msg_id = event.get("messageId")\n        if msg_id and self._dedup.is_duplicate(msg_id):\n            return\n        try:',
                    '        msg_id = event.get("messageId")\n        if msg_id and not self._task_a_socket and self._dedup.is_duplicate(msg_id):\n            return\n        binding_token = None\n        if self._task_a_socket:\n            handle = event.get("handle")\n            space_id = (event.get("space") or {}).get("id")\n            if not isinstance(handle, str) or not handle or not isinstance(space_id, str) or not space_id or not isinstance(msg_id, str):\n                return\n            binding_token = _task_a_reply_binding.set((handle, space_id, msg_id))\n        try:')
    source = change(source,
                    '        except Exception:\n            logger.exception("[photon] inbound dispatch failed")\n\n    async def _fffc_timeout_handler',
                    '        except Exception:\n            logger.exception("[photon] inbound dispatch failed")\n        finally:\n            if binding_token is not None:\n                _task_a_reply_binding.reset(binding_token)\n\n    async def _fffc_timeout_handler')
    source = change(source,
                    '    async def _dispatch_inbound(self, event: dict[str, Any]) -> None:',
                    '''    def _task_a_job_binding(self, event: MessageEvent) -> tuple[str, str, str] | None:
        """Recover the exact broker event from the queued job, not its creator task."""
        raw = getattr(event, "raw_message", None)
        if not isinstance(raw, dict):
            return None
        handle, message_id = raw.get("handle"), raw.get("messageId")
        space = raw.get("space")
        content = raw.get("content")
        space_id = space.get("id") if isinstance(space, dict) else None
        original_text = content.get("text") if isinstance(content, dict) else None
        source = getattr(event, "source", None)
        if (not isinstance(handle, str) or not handle or not isinstance(message_id, str)
                or not isinstance(space_id, str) or not isinstance(original_text, str)
                or getattr(source, "chat_id", None) != space_id
                or getattr(event, "message_id", None) != message_id
                or getattr(event, "text", None) != original_text):
            return None
        return handle, space_id, message_id

    async def _process_message_background(self, event: MessageEvent, session_key: str) -> None:
        if not self._task_a_socket:
            return await super()._process_message_background(event, session_key)
        binding = self._task_a_job_binding(event)
        if binding is None:
            logger.error("[photon] queued Task A event lost exact broker binding")
            self._finish_session_task(session_key, self._active_sessions.get(session_key) or asyncio.Event())
            return
        token = _task_a_reply_binding.set(binding)
        try:
            return await super()._process_message_background(event, session_key)
        finally:
            _task_a_reply_binding.reset(token)

    async def _dispatch_inbound(self, event: dict[str, Any]) -> None:''')
    source = change(source,
                    '        safe_path = self.validate_media_delivery_path(str(path))  # send_*_file / cron may pass arbitrary strings',
                    '        if self._task_a_socket:\n            return SendResult(success=False, error="Task A attachments disabled pending review")\n        safe_path = self.validate_media_delivery_path(str(path))  # send_*_file / cron may pass arbitrary strings')
    source = change(source,
                    '        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:\n            resp = await client.post(self._sidecar_url(path), json=body, headers=self._sidecar_headers())',
                    '        if self._task_a_socket:\n            if path == "/send":\n                binding = _task_a_reply_binding.get()\n                if not binding or body.get("spaceId") != binding[1]:\n                    raise RuntimeError("missing or mismatched authenticated Photon event handle")\n                path, body = "/reply", {"handle": binding[0], "text": body.get("text")}\n            elif path != "/healthz":\n                raise RuntimeError("Task A restricted interface forbids this operation")\n        transport = httpx.AsyncHTTPTransport(uds=self._task_a_socket) if self._task_a_socket else None\n        async with httpx.AsyncClient(transport=transport, timeout=30.0, trust_env=False) as client:\n            resp = await client.post(self._sidecar_url(path), json=body, headers=self._sidecar_headers())')
    source = change(source,
                    '        required_env=["PHOTON_PROJECT_ID", "PHOTON_PROJECT_SECRET"],',
                    '        required_env=[] if _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET") else ["PHOTON_PROJECT_ID", "PHOTON_PROJECT_SECRET"],')
    source = change(source,
                    '        setup_fn=_cli.gateway_setup,  # surfaces Photon in the unified `hermes gateway setup` wizard',
                    '        setup_fn=None if _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET") else _cli.gateway_setup,')
    source = change(source,
                    '        standalone_sender_fn=_standalone_send, allowed_users_env="PHOTON_ALLOWED_USERS",',
                    '        standalone_sender_fn=None if _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET") else _standalone_send, allowed_users_env="PHOTON_ALLOWED_USERS",')
    source = change(source,
                    '        allow_update_command=True,',
                    '        allow_update_command=not bool(_get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET")),')
    source = change(source,
                    '"sends as a rich preview card. You can send files natively: write MEDIA:/absolute/path/to/file "\n            "in your response (images and video appear inline, audio as voice notes, other files as "\n            "attachments). Recipient identifiers are E.164 phone numbers; never expose them in responses "',
                    '"sends as a rich preview card. "\n            + ("Attachments are disabled in Task A staging. " if _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET") else\n               "You can send files natively using MEDIA:/absolute/path/to/file. ")\n            + "Recipient identifiers are E.164 phone numbers; never expose them in responses "')
    source = change(source,
                    '    ctx.register_cli_command(\n        name="photon", help="Set up and manage the Photon iMessage integration",\n        setup_fn=_cli.register_cli, handler_fn=_cli.dispatch)',
                    '    if not _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET"):\n        ctx.register_cli_command(\n            name="photon", help="Set up and manage the Photon iMessage integration",\n            setup_fn=_cli.register_cli, handler_fn=_cli.dispatch)')
    return source


def main() -> None:
    chunks: list[str] = []
    for relative, expected in TARGETS.items():
        original_bytes = (UPSTREAM / relative).read_bytes()
        if hashlib.sha256(original_bytes).hexdigest() != expected:
            raise RuntimeError(f"upstream source hash changed: {relative}")
        original = original_bytes.decode()
        revised = sidecar(original) if relative.endswith("index.mjs") else adapter(original)
        chunks.extend(difflib.unified_diff(original.splitlines(keepends=True), revised.splitlines(keepends=True),
                                           fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    destination = ROOT / "patches/photon-secure-front.proposed.patch"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text("".join(chunks))
    print(f"{destination.relative_to(ROOT)}: {hashlib.sha256(destination.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
