"""Focused source-backed contract probes; no live Photon or Gateway dispatch."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest

from task_a.broker import PhotonIngressPrototype
from task_a.photon_front import StagingPhotonFront


HERMES = Path("/home/alfred/.hermes/hermes-agent")
SDK = HERMES / "plugins/platforms/photon/sidecar/node_modules"
NOW = dt.datetime(2026, 10, 14, 9, 30, tzinfo=dt.timezone.utc)


def test_known_handle_substitution_is_currently_accepted_at_restricted_boundary():
    """A bearer handle is inadequate proof of which turn authored the text."""
    class Sidecar:
        sidecar_uid = 41011
        sends = []

        def send_text(self, space, text):
            self.sends.append((space, text))
            return "synthetic-outbound"

    sidecar = Sidecar()
    ingress = PhotonIngressPrototype(sidecar_uid=41011, hermes_uid=41012,
                                    allowed_sender="synthetic-authorized-id", transport=None,
                                    now=lambda: NOW)
    front = StagingPhotonFront(ingress, sidecar)

    def event(message, text):
        return {"messageId": message, "platform": "iMessage",
                "space": {"id": "same-space", "type": "dm"},
                "sender": {"id": "synthetic-authorized-id"},
                "content": {"type": "text", "text": text},
                "timestamp": "2026-10-14T09:29:59Z"}

    first = front.ingest_protected_event(event("m1", "first"), observed_uid=41011)
    second = front.ingest_protected_event(event("m2", "second"), observed_uid=41011)
    assert first != second
    assert [front.next_forwarded(timeout=0)["handle"] for _ in range(2)] == [first, second]
    # The caller submits a reply produced for m2 under the already-seen m1
    # handle. The protected boundary currently has no turn attestation.
    status, _ = front.restricted_call("POST", "/reply",
                                      {"handle": first, "text": "response to m2"},
                                      observed_uid=41012)
    assert status == 200
    assert sidecar.sends == [("same-space", "response to m2")]


def test_installed_high_level_stream_has_no_persistent_resume_cursor():
    core = (SDK / "@spectrum-ts/core/dist/authoring.js").read_text()
    imessage = (SDK / "@spectrum-ts/imessage/dist/index.js").read_text()
    sidecar = (HERMES / "plugins/platforms/photon/sidecar/index.mjs").read_text()
    assert "let lastCursor;" in core
    assert 'lastCursor = void 0;' in core
    assert "accepting event gap and resuming live" in core
    assert 'if (lastCursor) await catchUpThenConsumeLive(lastCursor)' in core
    assert "if (since === void 0) return;" in imessage
    assert "for await (const [space, message] of app.messages)" in sidecar
    assert "await deliver(JSON.stringify(event));" in sidecar


def test_lower_level_replay_and_history_exist_but_are_not_a_retention_proof():
    grpc_types = (SDK / "@photon-ai/advanced-imessage/dist/grpc.d.ts").read_text()
    grpc_impl = (SDK / "@photon-ai/advanced-imessage/dist/client-NRHONKWO.js").read_text()
    assert "catchUp(since?: number): TypedEventStream<CatchUpEvent>" in grpc_types
    assert "listRecent(options?: MessageListFilter)" in grpc_types
    assert "listInChat(chat: string, options?: MessageListFilter)" in grpc_types
    assert "Omit `since` to replay from the beginning of the retained log" in grpc_impl
    assert 'type: "catchup.complete"' in grpc_impl


def test_message_only_sequences_cannot_certify_gap_free_global_log():
    imessage = (SDK / "@spectrum-ts/imessage/dist/index.js").read_text()
    assert 'const isMessageEvent = (event) => event.type.startsWith("message.")' in imessage
    assert "if (isWanted(event)) yield event" in imessage
    # A chat-change event can occupy the sequence between two messages.
    full_log = [(41, "message.received"), (42, "chat.changed"), (43, "message.received")]
    message_sequences = [seq for seq, kind in full_log if kind.startswith("message.")]
    assert message_sequences == [41, 43]


def test_installed_sdk_in_process_reconnect_uses_volatile_catchup():
    """Run the installed SDK stream against fake events, never a provider."""
    node = shutil.which("node") or "/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node"
    if not Path(node).is_file():
        pytest.skip("Node runtime unavailable")
    module_url = (SDK / "@spectrum-ts/core/dist/authoring.js").as_uri()
    script = f'''
import {{resumableOrderedStream}} from {json.dumps(module_url)};
const calls = [];
let subscriptions = 0;
async function* first() {{
  yield {{id:"one", sequence:1}};
  throw new Error("synthetic disconnect");
}}
async function* second() {{
  yield {{id:"three", sequence:3}};
  await new Promise(resolve => setTimeout(resolve, 50));
}}
const stream = resumableOrderedStream({{
  initialRetryDelayMs:0,
  jitter:delay => delay,
  subscribeLive(cursor) {{
    calls.push(["live", cursor ?? null]);
    return subscriptions++ === 0 ? first() : second();
  }},
  async *fetchMissed(cursor) {{
    calls.push(["catchup", cursor]);
    yield {{id:"two", sequence:2}};
  }},
  processLive: async event => ({{cursor:String(event.sequence), id:event.id, values:[event.id]}}),
  processMissed: async event => ({{cursor:String(event.sequence), id:event.id, values:[event.id]}})
}});
const received = [];
for await (const value of stream) {{
  received.push(value);
  if (received.length === 3) {{ await stream.close(); break; }}
}}
console.log(JSON.stringify({{calls, received}}));
'''
    result = subprocess.run([node, "--input-type=module", "-e", script],
                            text=True, capture_output=True, timeout=10,
                            env={**os.environ, "NODE_NO_WARNINGS": "1"})
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.splitlines()[-1])
    assert observed["received"] == ["one", "two", "three"]
    assert observed["calls"] == [["live", None], ["live", "1"], ["catchup", "1"]]
