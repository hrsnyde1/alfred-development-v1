"""Exercise the proposed Photon DM resolution fix in a disposable copy."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIDECAR = Path("/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/index.mjs")
NODE = Path("/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node")
OLD_SHA = "d504559deb8fdde24b1804d3ede8b390a6d3c8154867a4e5a2c145cd90ba6ea1"


def _exercise(source: Path, fixture: Path) -> dict:
    text = source.read_text()
    start = text.index("async function resolveSpace(spaceId) {")
    end = text.index("\n}\n", start) + 2
    function = text[start:end]
    fixture.write_text("""
const knownSpaces = new Map();
const calls = [];
const E164_RE = /^\\+\\d{6,}$/;
const DM_CHAT_GUID_RE = /^any;-;(\\+\\d{6,})$/;
function phoneTargetFromSpaceId(spaceId) {
  if (E164_RE.test(spaceId)) return spaceId;
  const match = spaceId.match(DM_CHAT_GUID_RE);
  return match ? match[1] : null;
}
function rememberKnownSpace(id, space) { if (id) knownSpaces.set(id, space); }
const app = {};
function imessage() {
  return {space: {
    create: async id => { calls.push('create'); return {id}; },
    get: async id => { calls.push('get'); return {id}; }
  }};
}
""" + function + """
const dm = await resolveSpace('any;-;+15551234567');
const bare = await resolveSpace('+15557654321');
console.log(JSON.stringify({dm: dm.id, bare: bare.id, calls}));
""")
    result = subprocess.run([str(NODE), str(fixture)], capture_output=True,
                            text=True, check=True)
    return json.loads(result.stdout)


def test_canonical_dm_guid_survives_resolution_without_a_send(tmp_path: Path):
    assert hashlib.sha256(SIDECAR.read_bytes()).hexdigest() == OLD_SHA
    original = _exercise(SIDECAR, tmp_path / "old-fixture.mjs")
    assert original == {"dm": "+15551234567", "bare": "+15557654321",
                        "calls": ["create", "create"]}

    staged = tmp_path / "index.mjs"
    shutil.copyfile(SIDECAR, staged)
    subprocess.run(["patch", "-p1", "--input", str(ROOT / "photon_dm_resolution.patch")],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run([str(NODE), "--check", str(staged)], check=True,
                   capture_output=True, text=True)
    corrected = _exercise(staged, tmp_path / "new-fixture.mjs")
    assert corrected == {"dm": "any;-;+15551234567", "bare": "+15557654321",
                         "calls": ["get", "create"]}
