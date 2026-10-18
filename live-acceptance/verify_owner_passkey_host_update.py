"""Read-only post-install check for Alfred OS passkey approvals. Run as alfred (the
Intake's user) while the activation marker is absent.

Everything it approves or refuses happens in a private /tmp grant store with a throwaway
software passkey, removed before exit. It never reads or writes the real grant store's
contents, never sends a message and never calls a model or worker. It connects to the
live owner-approval.sock only as alfred, which must be refused.

Prints one PASS line and exits 0, or FAIL with the first failed check and exits 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

DEVELOPER_ROOT = Path("/opt/alfred-developer-v1")
INTAKE = Path("/usr/local/lib/alfred-v1.1/trusted_intake.py")
SOCKETS = Path("/run/alfred-development-intake")
GRANTS = Path("/var/lib/alfred-development-grants")
CTO = Path("/home/alfred/Git/alfred/.dev/bin/cto.py")
MANIFEST_SHA256 = "fb3ad9c57aff9a02ecdc3506cc676cf3a4fa4729f3ee1a5b66609aa8c2e20329"
GATEWAY_UNITS = ("alfred-development-gateway.service", "alfred-development-gateway.timer")
ACTIVE_UNITS = ("alfred-development-intake.service", "alfred-photon.service",
                "alfred-hermes.service")
ALFRED_OS_USER = "alfredos"


class AcceptanceFailed(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailed(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def store_listing(root: Path) -> str:
    """Names only: the real grant store's contents are never read."""
    return hashlib.sha256("\n".join(sorted(p.name for p in root.iterdir())).encode()).hexdigest()


def check_release(root: Path, manifest_sha256: str, intake: Path) -> None:
    manifest = root / "developer_v1" / "release.sha256"
    require(sha256(manifest) == manifest_sha256, "installed release manifest digest")
    for line in manifest.read_text().splitlines():
        digest, _, relative = line.partition("  ")
        target = root / relative
        require(target.is_file() and not target.is_symlink() and sha256(target) == digest,
                "installed file digest " + relative)
    require(sha256(intake) == sha256(root / "developer_v1" / "trusted_intake_development.py"),
            "installed Intake source differs from the released module")


class Synthetic:
    """A private grant store with a throwaway passkey pinned for it."""

    def __init__(self, private: Path):
        import owner_passkey_fixture as fixture
        from developer_v1 import owner_approval
        from developer_v1.owner_grants import DevelopmentGrantIssuer
        self.fixture, self.private = fixture, private
        self.root = private / "grants"
        self.root.mkdir(mode=0o700)
        self.key = fixture.Authenticator()
        self.pin = private / "owner-passkey.json"
        fixture.write_pin(self.pin, self.key.pin())
        self.channel = private / "approval-channel.json"
        self.channel.write_text(json.dumps({"schema": owner_approval.CHANNEL_SCHEMA,
                                            "default": "alfred_os"}))
        self.channel.chmod(0o644)
        self.sent = []
        self.issuer = DevelopmentGrantIssuer(
            self.root, owner_sender_id="owner", sidecar_uid=65533, admin_uid=0,
            environment="staging", channel_policy=self.channel, owner_passkey_pin=self.pin,
            preview_sender=lambda space, text: self.sent.append(text) or "native-message")
        self.service = owner_approval.OwnerApprovals(
            self.root, development_issuer=self.issuer, publication_issuer=None,
            development_request=lambda offer: (offer["request"], None), alfred_os_uid=65534,
            notice_sender=lambda space, text: self.sent.append(text) or "notice",
            pin_path=self.pin, pin_owner=os.geteuid())

    def request(self, task: str) -> dict:
        return {"schema": "alfred.development-approval-request/1", "project": "checker",
                "task_id": task, "spec_sha256": "1" * 64, "plan_sha256": "2" * 64,
                "repository": "/nonexistent/checker", "worktree_root": "/nonexistent/wt",
                "scope": ["app.py"], "specialists": ["backend"],
                "state": "pending_owner_decision"}

    def call(self, request: dict) -> dict:
        from developer_v1.owner_approval import handle
        return handle(self.service, request, 65534)

    def offer(self, task: str) -> tuple[str, dict]:
        request = self.request(task)
        staged = self.issuer.stage(request, space_id="dm", peer_uid=0)
        require(staged["state"] == "awaiting_alfred_os_owner_passkey", "offer not staged")
        return staged["challenge"], request

    def open(self, offer: str, action: str = "approve") -> dict:
        opened = self.call({"op": "open_owner_approval", "offer": offer, "action": action})
        require("reference" in opened, "open refused: " + str(opened.get("error")))
        return opened

    def answer(self, opened: dict, assertion: dict) -> dict:
        return self.call({"op": "answer_owner_approval", "reference": opened["reference"],
                          "assertion": assertion})

    def sign(self, opened: dict, **kwargs) -> dict:
        from developer_v1 import owner_passkey
        return self.key.assertion(owner_passkey.b64url_decode(opened["webauthn"]["challenge"]),
                                  **kwargs)

    def authority(self, environment: str = "staging"):
        from developer_v1.owner_grants import ProtectedDevelopmentAuthority
        return ProtectedDevelopmentAuthority(self.root, environment=environment,
                                             owner_passkey_pin=self.pin)

    def expected(self, request: dict) -> dict:
        return {"schema": "alfred.development-grant/1",
                **{k: v for k, v in request.items() if k not in ("schema", "state")}}


def check_imessage_unchanged(s: Synthetic) -> None:
    import datetime as dt
    from developer_v1 import owner_grants
    request = s.request("T-0001")
    staged = s.issuer.stage(request, space_id="dm", peer_uid=0, channel="imessage")
    require(staged["state"] == "awaiting_native_owner_reply" and s.sent, "iMessage text not sent")
    event = {"messageId": "owner-reply", "direction": "inbound", "sender": {"id": "owner"},
             "space": {"id": "dm", "type": "dm"}, "nativeReplyTargetGuid": "native-message",
             "nativeIsForward": False,
             "content": {"type": "text", "text": owner_grants._phrase(request)},
             "timestamp": dt.datetime.now(dt.timezone.utc).isoformat()}
    require(s.issuer.observe(event, peer_uid=65533)["state"] == "development_approved",
            "iMessage reply did not approve")
    grant = s.authority().verify(staged["challenge"], s.expected(request))
    require(grant["source"] == "photon_native_owner_reply", "iMessage grant source")


def check_passkey(s: Synthetic) -> None:
    from developer_v1.router import Denied
    import owner_passkey_fixture as fixture
    offer, request = s.offer("T-0002")
    opened = s.open(offer)
    require(s.sent[-1].startswith("Approval opened in Alfred OS: checker T-0002 "),
            "open notice text")
    forged = {"bad signature": {"signer": fixture.Authenticator()},
              "wrong rp_id": {"rp_id": "evil.example"},
              "user verification unset": {"flags": 0x01}}
    for name, kwargs in forged.items():
        require(s.answer(opened, s.sign(opened, **kwargs)) == {"error": "not_verified"},
                "forged assertion accepted: " + name)
    signed_approve = s.sign(opened)
    decline = s.open(offer, "decline")
    require(s.answer(decline, signed_approve) == {"error": "not_verified"},
            "an approve signature verified as a decline")
    approve = s.open(offer)
    assertion = s.sign(approve)
    require(not (s.root / f"grant-{offer}.json").exists()
            and not (s.root / f"owner-passkey-decided-{offer}.json").exists(),
            "a refused answer wrote evidence")
    require(s.answer(approve, assertion) == {"result": "approved"}, "valid passkey refused")
    require(s.answer(approve, assertion) == {"error": "already_decided"}, "reused signature")
    grant = s.authority().verify(offer, s.expected(request))
    require(grant["source"] == "alfred_os_owner_passkey", "passkey grant source")
    try:
        s.authority("host").verify(offer, s.expected(request))
    except Denied:
        pass
    else:
        raise AcceptanceFailed("a synthetic passkey grant verified as a host grant")
    offer, _ = s.offer("T-0003")
    declined = s.open(offer, "decline")
    require(s.answer(declined, s.sign(declined)) == {"result": "declined"}, "decline refused")
    require(not (s.root / f"grant-{offer}.json").exists(), "a decline wrote a grant")
    later = s.call({"op": "open_owner_approval", "offer": offer, "action": "approve"})
    require(later == {"error": "already_decided"}, "an approve after a decline was offered")


def check_live_socket(sockets: Path, uid: int) -> None:
    import struct
    path = sockets / "owner-approval.sock"
    require(path.is_socket(), "owner-approval.sock is not listening")
    require((sockets / "intake.sock").is_socket(), "intake.sock is not listening")
    acl = os.getxattr(path, "system.posix_acl_access")
    entries = [struct.unpack("<HHI", acl[4 + 8 * i:12 + 8 * i]) for i in range((len(acl) - 4) // 8)]
    require(entries == [(1, 6, 0xFFFFFFFF), (2, 6, uid), (4, 0, 0xFFFFFFFF),
                        (16, 6, 0xFFFFFFFF), (32, 0, 0xFFFFFFFF)],
            "owner-approval.sock ACL is not exactly its owner and alfredos")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(path))
        client.sendall(b'{"op":"list_owner_approvals"}\n')
        reply = client.recv(4096)
    require(json.loads(reply) == {"error": "invalid"}, "owner socket answered a non-Alfred-OS peer")


def check_host_state(args) -> None:
    require(not (args.developer_root / "active").exists(), "activation marker present")
    require(sha256(args.cto) == args.cto_sha256, "CTO source changed")
    result = subprocess.run([args.systemctl, "show", "-p", "ActiveState", "-p", "Result",
                             *GATEWAY_UNITS], capture_output=True, check=True, timeout=15)
    require(hashlib.sha256(result.stdout).hexdigest() == args.gateway_sha256,
            "Gateway unit state changed")
    for unit in ACTIVE_UNITS:
        state = subprocess.run([args.systemctl, "is-active", unit], capture_output=True,
                               text=True, timeout=15).stdout.strip()
        require(state == "active", unit + " is not active")
    require(store_listing(args.grants) == args.grant_store_sha256,
            "the real grant store changed during the update")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cto-sha256", required=True)
    parser.add_argument("--gateway-sha256", required=True)
    parser.add_argument("--grant-store-sha256", required=True)
    parser.add_argument("--developer-root", type=Path, default=DEVELOPER_ROOT)
    parser.add_argument("--intake", type=Path, default=INTAKE)
    parser.add_argument("--sockets", type=Path, default=SOCKETS)
    parser.add_argument("--grants", type=Path, default=GRANTS)
    parser.add_argument("--cto", type=Path, default=CTO)
    parser.add_argument("--manifest-sha256", default=MANIFEST_SHA256)
    parser.add_argument("--systemctl", default="/usr/bin/systemctl")
    parser.add_argument("--alfred-os-uid", type=int)
    args = parser.parse_args(argv)
    if args.alfred_os_uid is None:
        import pwd
        args.alfred_os_uid = pwd.getpwnam(ALFRED_OS_USER).pw_uid
    logging.getLogger("developer_v1").setLevel(logging.ERROR)
    private = Path(tempfile.mkdtemp(prefix="alfred-passkey-check-", dir="/tmp"))
    try:
        check_release(args.developer_root, args.manifest_sha256, args.intake)
        synthetic = Synthetic(private)
        check_imessage_unchanged(synthetic)
        check_passkey(synthetic)
        check_live_socket(args.sockets, args.alfred_os_uid)
        check_host_state(args)
    except Exception as exc:  # noqa: BLE001 - every failure is one FAIL line
        print(f"FAIL: {exc}" if isinstance(exc, AcceptanceFailed)
              else f"FAIL: {type(exc).__name__}: {exc}"[:300])
        return 1
    finally:
        shutil.rmtree(private, ignore_errors=True)
    print("PASS: passkey approvals verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
