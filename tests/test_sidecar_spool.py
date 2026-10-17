"""Durable sidecar spool checks with a local Node stub, never Photon SDK."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node") or "/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node"
SPOOL_CODE = (ROOT / "patches/photon-durable-spool.mjs.txt").read_text()
PRELUDE = '''
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
const lines = [];
async function deliver(line) { lines.push(JSON.parse(line)); }
async function acknowledgeInboundRead(message) { message.reads += 1; }
function ok(_res, data) { return {ok:true, ...data}; }
function badRequest(_res, error) { return {ok:false, error}; }
'''


def run_node(spool: Path, suffix: str) -> dict:
    if not Path(NODE).is_file():
        pytest.skip("Node binary unavailable")
    result = subprocess.run([NODE, "--input-type=module"], input=PRELUDE + SPOOL_CODE + suffix,
                            text=True, capture_output=True, timeout=10,
                            env={**os.environ, "PHOTON_EVENT_SPOOL": str(spool)})
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("decision,reads", [("accepted", 1), ("rejected", 0), ("held", 0)])
def test_spool_commit_ack_then_read_receipt(tmp_path, decision, reads):
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    suffix = f'''
const message = {{reads:0}};
const record = persistDelivery({{messageId:"m1",sender:{{id:"synthetic"}},content:{{type:"text",text:"lab"}}}}, message);
const committed = fs.existsSync(spoolPath(record.deliveryId));
const waiter = deliverUntilAck(record);
await new Promise((resolve) => setImmediate(resolve));
const before = message.reads;
const answer = await acknowledgeDelivery({{deliveryId:record.deliveryId,decision:"{decision}"}}, {{}});
await waiter;
console.log(JSON.stringify({{committed,before,after:message.reads,answer,lines:lines.length,remaining:pendingDeliveries.size}}));
'''
    data = run_node(spool, suffix)
    assert data["committed"] is True and data["before"] == 0 and data["after"] == reads
    assert data["answer"]["ok"] is True and data["lines"] == 1 and data["remaining"] == 0
    assert not list(spool.glob("*.json"))


def test_crash_replay_uses_same_delivery_id_without_read_receipt(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    first = run_node(spool, '''
const record = persistDelivery({messageId:"m2",sender:{id:"synthetic"},content:{type:"text",text:"lab"}}, null);
console.log(JSON.stringify({id:record.deliveryId,files:fs.readdirSync(eventSpool).length}));
''')
    assert first["files"] == 1
    second = run_node(spool, '''
const first = [...pendingDeliveries.values()][0];
const replay = replayPendingDeliveries();
await new Promise((resolve) => setImmediate(resolve));
await acknowledgeDelivery({deliveryId:first.deliveryId,decision:"accepted"}, {});
await replay;
console.log(JSON.stringify({id:first.deliveryId,lines:lines.length,remaining:pendingDeliveries.size}));
''')
    assert second == {"id": first["id"], "lines": 1, "remaining": 0}


def test_crash_before_first_spool_fsync_leaves_no_replayable_event(tmp_path):
    """Local failure only: the provider's behavior after this point is unknown."""
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    first = run_node(spool, '''
fs.fsyncSync = () => { throw new Error("injected pre-commit crash"); };
let failed = false;
try { persistDelivery({messageId:"not-durable",content:{type:"text",text:"lab"}}, null); }
catch (error) { failed = error.message === "injected pre-commit crash"; }
console.log(JSON.stringify({failed,finalFiles:fs.readdirSync(eventSpool).filter((name) => name.endsWith(".json")).length}));
''')
    assert first == {"failed": True, "finalFiles": 0}
    recovered = run_node(spool, '''
console.log(JSON.stringify({pending:pendingDeliveries.size,ignoredTemporary:fs.readdirSync(eventSpool).length}));
''')
    assert recovered == {"pending": 0, "ignoredTemporary": 1}


def test_oversized_event_gets_durable_explicit_rejection(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    data = run_node(spool, '''
const record = persistDelivery({messageId:"m3",content:{type:"text",text:"x".repeat(70000)}}, null);
const committed = fs.existsSync(spoolPath(record.deliveryId));
const decision = await acknowledgeDelivery({deliveryId:record.deliveryId,decision:"rejected"}, {});
console.log(JSON.stringify({error:record.event.deliveryError,committed,remaining:fs.readdirSync(eventSpool).length,ok:decision.ok}));
''')
    assert data == {"error": "oversized", "committed": True, "remaining": 0, "ok": True}
