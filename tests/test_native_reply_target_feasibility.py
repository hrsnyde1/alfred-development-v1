"""Staging-only feasibility probes, not live Photon security acceptance."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLED = Path("/home/alfred/.hermes/hermes-agent")
REL = Path("plugins/platforms/photon/sidecar/node_modules/@spectrum-ts/imessage/dist")
NODE = Path("/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node")
PATCH = ROOT / "patches/spectrum-native-reply-provenance.proposed.patch"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def _patched_disposable_copy():
    assert NODE.exists(), "pinned Node runtime unavailable"
    sources = [INSTALLED / REL / name for name in ("index.js", "index.d.ts")]
    before = [_sha(path) for path in sources]
    with tempfile.TemporaryDirectory(prefix=".native-reply-test-", dir=ROOT) as temporary:
        disposable = Path(temporary)
        copied = disposable / REL
        copied.mkdir(parents=True)
        for source in sources:
            shutil.copy2(source, copied / source.name)
        # The host currently carries the proposed SDK patch. Reconstruct the
        # pristine package in this disposable copy, then reapply it for the
        # feasibility probe without modifying the installed dependency.
        subprocess.run(["git", "apply", "--reverse", "--check", str(PATCH)],
                       cwd=disposable, check=True)
        subprocess.run(["git", "apply", "--reverse", str(PATCH)],
                       cwd=disposable, check=True)
        pristine = disposable / "pristine-index.js"
        pristine.write_bytes((copied / "index.js").read_bytes())
        shutil.copy2(INSTALLED / REL.parent / "package.json", copied.parent / "package.json")

        # The patched package is copied; dependency links resolve to the exact
        # pinned installed packages, which remain read-only throughout.
        installed_modules = INSTALLED / "plugins/platforms/photon/sidecar/node_modules"
        modules = disposable / "plugins/platforms/photon/sidecar/node_modules"
        for name in ("@photon-ai/advanced-imessage", "@photon-ai/otel",
                     "@spectrum-ts/core", "zod", "marked", "lru-cache"):
            link = modules / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(installed_modules / name, target_is_directory=True)

        subprocess.run(["git", "apply", "--check", str(PATCH)], cwd=disposable, check=True)
        subprocess.run(["git", "apply", str(PATCH)], cwd=disposable, check=True)
        try:
            yield copied / "index.js", pristine, installed_modules
        finally:
            assert before == [_sha(path) for path in sources]


def test_full_patched_module_parses_and_imports() -> None:
    with _patched_disposable_copy() as (patched, _original, _modules):
        parsed = subprocess.run(
            [str(NODE), "--experimental-vm-modules",
             str(ROOT / "tests/native_reply_import_smoke.mjs"), str(patched)],
            text=True, capture_output=True,
        )
        assert parsed.returncode == 0, parsed.stderr
        assert parsed.stdout.count("PASS:") == 2


def test_proposed_patch_on_disposable_copy() -> None:
    with _patched_disposable_copy() as (patched, original, installed_modules):
        result = subprocess.run(
            [str(NODE), str(ROOT / "tests/native_reply_provenance.mjs"),
             str(original), str(patched),
             str(installed_modules / "@spectrum-ts/core/dist/index.js"),
             str(INSTALLED / "plugins/platforms/photon/sidecar/index.mjs")],
            text=True, capture_output=True, check=True,
        )
        assert result.stdout.count("PASS:") == 2


class ConfirmationProbe:
    """Synthetic policy model; no provider or Gateway capability."""

    def __init__(self, owner: str = "owner", account: str = "account", space: str = "dm"):
        self.owner, self.account, self.space = owner, account, space
        self.pending: dict[str, dict] = {}
        self.seen: set[str] = set()

    def preview(self, outbound_id: str, digest: str, expires: int = 100) -> None:
        assert outbound_id and outbound_id not in self.pending
        self.pending[outbound_id] = {"digest": digest, "expires": expires, "used": False}

    def accept(self, event: dict, now: int, digest: str) -> bool:
        target = event.get("nativeReplyTargetGuid")
        entry = self.pending.get(target) if isinstance(target, str) and target else None
        if not entry or entry["used"] or now >= entry["expires"]:
            return False
        if event.get("id") in self.seen or not event.get("id"):
            return False
        if event.get("sender") != self.owner or event.get("account") != self.account:
            return False
        if event.get("space") != self.space or event.get("direction") != "inbound":
            return False
        if event.get("nativeIsForward") is not False:
            return False
        if event.get("body", "").strip().lower() not in {"yes", "yes, go ahead"}:
            return False
        if entry["digest"] != digest:
            return False
        entry["used"] = True
        self.seen.add(event["id"])
        return True

    def snapshot(self) -> str:
        return json.dumps({"owner": self.owner, "account": self.account,
                           "space": self.space, "pending": self.pending,
                           "seen": sorted(self.seen)})

    def uncertain_reconnect(self) -> None:
        """Conservative V1 rule: discard outstanding challenges after a gap."""
        for entry in self.pending.values():
            entry["used"] = True

    @classmethod
    def restore(cls, raw: str) -> "ConfirmationProbe":
        state = json.loads(raw)
        obj = cls(state["owner"], state["account"], state["space"])
        obj.pending = state["pending"]
        obj.seen = set(state["seen"])
        return obj


def event(event_id="event-1", target="preview-1", **overrides) -> dict:
    data = {"id": event_id, "nativeReplyTargetGuid": target,
            "nativeThreadOriginatorGuid": "thread-origin", "targetMessageId": target,
            "sender": "owner", "account": "account", "space": "dm",
            "direction": "inbound", "nativeIsForward": False, "body": "Yes, go ahead"}
    data.update(overrides)
    return data


def test_direct_threaded_confirmation_and_replay() -> None:
    gate = ConfirmationProbe()
    gate.preview("preview-1", "digest-1")
    assert gate.accept(event(), 10, "digest-1")
    assert not gate.accept(event(), 11, "digest-1")


@pytest.mark.parametrize("change", [
    {"nativeReplyTargetGuid": None},
    {"nativeReplyTargetGuid": None, "targetMessageId": "preview-1"},
    {"nativeReplyTargetGuid": "wrong-preview"},
    {"sender": "someone-else"}, {"sender": None}, {"account": "other"},
    {"space": "other"}, {"direction": "outbound"},
    {"nativeIsForward": True}, {"nativeIsForward": None},
    {"body": "no"}, {"id": None},
])
def test_wrong_target_unthreaded_fallback_and_identity_denied(change: dict) -> None:
    gate = ConfirmationProbe()
    gate.preview("preview-1", "digest-1")
    assert not gate.accept(event(**change), 10, "digest-1")


def test_concurrent_previews_delayed_reply_and_restart() -> None:
    gate = ConfirmationProbe()
    gate.preview("preview-1", "digest-1", expires=50)
    gate.preview("preview-2", "digest-2", expires=200)
    restored = ConfirmationProbe.restore(gate.snapshot())
    assert restored.accept(event("event-2", "preview-2"), 120, "digest-2")
    assert not restored.accept(event("event-1", "preview-1"), 120, "digest-1")
    assert not restored.accept(event("event-3", "preview-2"), 121, "digest-2")


def test_two_active_previews_bind_separate_replies() -> None:
    gate = ConfirmationProbe()
    gate.preview("preview-1", "digest-1")
    gate.preview("preview-2", "digest-2")
    assert gate.accept(event("event-2", "preview-2"), 10, "digest-2")
    assert gate.accept(event("event-1", "preview-1"), 11, "digest-1")
    assert not gate.accept(event("event-3", "preview-1"), 12, "digest-1")


def test_changed_draft_and_conflicting_target_denied() -> None:
    gate = ConfirmationProbe()
    gate.preview("preview-1", "digest-1")
    gate.preview("preview-2", "digest-2")
    assert not gate.accept(event(target="preview-1"), 10, "digest-2")
    assert gate.accept(event("event-2", "preview-2"), 10, "digest-2")


def test_reconnect_requires_fresh_preview_confirmation() -> None:
    gate = ConfirmationProbe()
    gate.preview("preview-1", "digest-1")
    gate.uncertain_reconnect()
    resumed = ConfirmationProbe.restore(gate.snapshot())
    assert not resumed.accept(event("event-late", "preview-1"), 10, "digest-1")
    resumed.preview("preview-2", "digest-1")
    assert resumed.accept(event("event-fresh", "preview-2"), 11, "digest-1")


def test_installed_interface_exposes_raw_direct_target() -> None:
    spectrum = (INSTALLED / REL / "index.js").read_text()
    sidecar = (INSTALLED / "plugins/platforms/photon/sidecar/index.mjs").read_text()
    assert "nativeReplyTargetGuid: native.replyTargetGuid" in spectrum
    assert "nativeReplyTargetGuid: message.nativeReplyTargetGuid ?? null" in sidecar
