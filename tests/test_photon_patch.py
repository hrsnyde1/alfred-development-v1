"""Static checks for the review-only upstream Photon patch."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

import make_photon_patch as patch


def test_pinned_upstream_patch_is_reproducible():
    for relative, expected in patch.TARGETS.items():
        assert hashlib.sha256((patch.UPSTREAM / relative).read_bytes()).hexdigest() == expected
    pieces = []
    import difflib
    for relative in patch.TARGETS:
        original = (patch.UPSTREAM / relative).read_text()
        revised = patch.sidecar(original) if relative.endswith("index.mjs") else patch.adapter(original)
        pieces.extend(difflib.unified_diff(original.splitlines(keepends=True), revised.splitlines(keepends=True),
                                           fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    assert (patch.ROOT / "patches/photon-secure-front.proposed.patch").read_text() == "".join(pieces)


def test_patched_sidecar_has_one_sdk_connection_and_no_path_attachment_route():
    original = (patch.UPSTREAM / "plugins/platforms/photon/sidecar/index.mjs").read_text()
    revised = patch.sidecar(original)
    assert revised.count("await Spectrum({") == 1
    assert 'if (req.url === "/send-attachment")' not in revised
    assert 'return { deliveryError: "normalization" };' in revised
    assert 'durable event acceptance unavailable' in revised
    assert "server.listen(privateSocket" in revised
    assert "fs.chmodSync(privateSocket, 0o600)" in revised
    node = shutil.which("node") or "/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node"
    if not Path(node).is_file():
        pytest.skip("Node binary unavailable for syntax check")
    result = subprocess.run([node, "--check", "--input-type=module"], input=revised, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_patched_adapter_keeps_credentials_and_token_out_of_task_a_mode():
    original = (patch.UPSTREAM / "plugins/platforms/photon/adapter.py").read_text()
    revised = patch.adapter(original)
    ast.parse(revised)
    assert 'self._project_secret: str = "" if self._task_a_socket' in revised
    assert 'self._sidecar_token = "" if self._task_a_socket' in revised
    assert 'return SendResult(success=False, error="Task A attachments disabled pending review")' in revised
    assert 'path, body = "/reply", {"handle": binding[0], "text": body.get("text")}' in revised
    assert '_task_a_handles' not in revised
    assert 'standalone_sender_fn=None if _get_scoped_secret("PHOTON_TASK_A_BROKER_SOCKET")' in revised
