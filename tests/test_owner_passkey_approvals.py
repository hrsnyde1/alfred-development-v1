"""Owner approvals in Alfred OS with the owner's pinned passkey (owner_approval.py).

Synthetic only: throwaway software passkeys, temporary grant stores, no host files."""

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "live-acceptance"))

import owner_passkey_fixture as fixture  # noqa: E402
import test_developer_execution_v1 as dx  # noqa: E402
from developer_v1 import owner_approval, owner_grants, owner_passkey as passkey  # noqa: E402
from developer_v1 import publication_approval as pub  # noqa: E402
from developer_v1.owner_approval import OwnerApprovals, handle  # noqa: E402
from developer_v1.owner_grants import DevelopmentGrantIssuer, ProtectedDevelopmentAuthority  # noqa: E402
from developer_v1.router import Denied  # noqa: E402

ALFRED_OS = 4242
VECTOR = {
    "public_key": "pQECAyYgASFYIM6x6qKq6w7EBhrst4Caxb07EeMMRT2mWWduxZo0p2zIIlggHpVJRbVv_J7XRibBzeTBYAz_5Llo_5s2mOSnwO6Mc-4",
    "credential_id": "dmVjdG9yLWNyZWRlbnRpYWw",
    "challenge": "o75yTNrCF4ppzWxY6VBb7Q-6F83TpJqdbDc6HZtNRrk",
    "clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4uZ2V0IiwiY2hhbGxlbmdlIjoibzc1eVROckNGNHBweld4WTZWQmI3US02RjgzVHBKcWRiRGM2SFp0TlJyayIsIm9yaWdpbiI6Imh0dHA6Ly9sb2NhbGhvc3Q6MzEwMCIsImNyb3NzT3JpZ2luIjpmYWxzZX0",
    "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_krrmihjLHmVzzuoMdl2MFAAAAAA",
    "signature": "MEYCIQCXovQEXvEqpnhP3kXgreDT0OAd4OZRELyKu1k0UPCD0AIhAO8-YXYQYRndIo4Ermd7Av1GBoFgjR1Ns4LxVrBSU23Q",
}


# --- the verifier ---------------------------------------------------------------------

def vector_pin(**changes):
    return {"schema": passkey.PIN_SCHEMA, "credential_id": VECTOR["credential_id"],
            "public_key": VECTOR["public_key"], "alg": -7, "rp_id": "localhost",
            "origins": ["http://localhost:3100"], "allow_zero_sign_count": True,
            "sign_count": 0, "enrolled_at": 1.0, **changes}


def vector_raw(**changes):
    return {"credential_id": VECTOR["credential_id"], "client_data_json": VECTOR["clientDataJSON"],
            "authenticator_data": VECTOR["authenticatorData"], "signature": VECTOR["signature"],
            "user_handle": None, **changes}


def test_pinned_webauthn_vector_from_another_implementation_verifies():
    challenge = passkey.b64url_decode(VECTOR["challenge"])
    result = passkey.verify_raw(passkey.validate_pin(vector_pin()), vector_raw(), challenge,
                                last_sign_count=0)
    assert result["sign_count"] == 0 and all(result["checks"].values())
    with pytest.raises(passkey.NotVerified):
        passkey.verify_raw(vector_pin(), vector_raw(), challenge[:-1] + b"x", last_sign_count=0)


def test_matches_the_cryptography_package_when_installed(tmp_path):
    probe = subprocess.run(["/usr/bin/python3", "-I", "-c", "import cryptography"],
                           capture_output=True)
    if probe.returncode:
        pytest.skip("cryptography is not installed for /usr/bin/python3")
    script = tmp_path / "cross.py"
    script.write_text(
        "import json, sys\nsys.path.insert(0, %r)\n" % str(ROOT) +
        "from cryptography.hazmat.primitives.asymmetric import ec\n"
        "from cryptography.hazmat.primitives import hashes\n"
        "from developer_v1 import owner_passkey as o\n"
        "for i in range(8):\n"
        "    k = ec.generate_private_key(ec.SECP256R1()); n = k.public_key().public_numbers()\n"
        "    sig = k.sign(b'm%d' % i, ec.ECDSA(hashes.SHA256()))\n"
        "    assert o.es256_verify((n.x, n.y), b'm%d' % i, sig)\n"
        "    assert not o.es256_verify((n.x, n.y), b'other', sig)\n"
        "print('ok')\n")
    result = subprocess.run(["/usr/bin/python3", "-I", str(script)], capture_output=True, text=True)
    assert result.stdout.strip() == "ok", result.stderr


@pytest.mark.parametrize("signature", [
    "MEYCIQCXovQEXvEqpnhP3kXgreDT0OAd4OZRELyKu1k0UPCD0AIhAO8-YXYQYRndIo4Ermd7Av1GBoFgjR1Ns4LxVrBSU23QAA",
    base64.urlsafe_b64encode(b"\x30\x06\x02\x01\x00\x02\x01\x01").rstrip(b"=").decode(),
    base64.urlsafe_b64encode(b"\x30\x08\x02\x02\x00\x01\x02\x02\x00\x01").rstrip(b"=").decode(),
])
def test_signature_encoding_is_strict_der(signature):
    with pytest.raises(passkey.NotVerified):
        passkey.verify_raw(vector_pin(), vector_raw(signature=signature),
                           passkey.b64url_decode(VECTOR["challenge"]), last_sign_count=0)


@pytest.mark.parametrize("change", [
    {"alg": -257}, {"rp_id": "Example.com"}, {"origins": []}, {"origins": ["ftp://x"]},
    {"public_key": passkey.b64url(bytes.fromhex("a5010203390100200121582000") + b"\0" * 32)},
    {"public_key": passkey.b64url(bytes.fromhex("a5010203262001215820") + b"\1" * 32
                                  + b"\x22\x58\x20" + b"\1" * 32)},
    {"extra": True},
])
def test_pin_must_be_es256_p256_with_pinned_relying_party(change):
    with pytest.raises(passkey.NotPinned):
        passkey.validate_pin(vector_pin(**change))


def test_pin_file_checks(tmp_path):
    path = tmp_path / "owner-passkey.json"
    fixture.write_pin(path, vector_pin())
    assert passkey.load_pin(path, owner_uid=os.geteuid())["credential_id"]
    for owner in (os.geteuid() + 1,):
        with pytest.raises(passkey.NotPinned):
            passkey.load_pin(path, owner_uid=owner)        # not root-owned
    path.chmod(0o666)
    with pytest.raises(passkey.NotPinned):
        passkey.load_pin(path, owner_uid=os.geteuid())     # writable by others
    path.chmod(0o644)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(passkey.NotPinned):
        passkey.load_pin(link, owner_uid=os.geteuid())     # symlink
    big = tmp_path / "big.json"
    big.write_text(json.dumps({**vector_pin(), "pad": "x" * 5000}))
    big.chmod(0o644)
    with pytest.raises(passkey.NotPinned):
        passkey.load_pin(big, owner_uid=os.geteuid())      # oversized
    with pytest.raises(passkey.NotPinned):
        passkey.load_pin(tmp_path / "absent.json", owner_uid=os.geteuid())


def test_approve_and_decline_statements_have_different_digests():
    statement = {"schema": passkey.STATEMENT_SCHEMA, "kind": "development", "action": "approve"}
    assert (passkey.statement_digest(statement)
            != passkey.statement_digest({**statement, "action": "decline"})
            != passkey.statement_digest({**statement, "kind": "publication"}))


# --- the development flow ---------------------------------------------------------------

class World:
    def __init__(self, tmp_path):
        self.fx = dx.ExecutionFixture("test_grant_requires_native_owner_target_and_exact_binding")
        self.fx.setUp()
        self.now = time.time()
        self.key = fixture.Authenticator()
        self.pin_path = tmp_path / "owner-passkey.json"
        fixture.write_pin(self.pin_path, self.key.pin())
        self.channel = tmp_path / "approval-channel.json"
        self.channel.write_text(json.dumps({"schema": owner_approval.CHANNEL_SCHEMA,
                                            "default": "alfred_os"}))
        self.channel.chmod(0o644)
        self.notices, self.texts = [], []
        self.issuer = DevelopmentGrantIssuer(
            self.fx.grants, owner_sender_id="owner", sidecar_uid=1234, admin_uid=0,
            environment="staging", clock=lambda: self.now, channel_policy=self.channel,
            owner_passkey_pin=self.pin_path,
            preview_sender=lambda space, text: self.texts.append(text) or "photon-plan-message")
        self.publication = pub.PublicationApprovalIssuer(
            self.fx.grants, owner_sender_id="owner", sidecar_uid=1234, admin_uid=0,
            clock=lambda: self.now, preview_sender=lambda s, t: self.texts.append(t) or "pm",
            channel_policy=self.channel, owner_passkey_pin=self.pin_path,
            policy_owner=os.geteuid(), alfred_os_uid=ALFRED_OS)
        self.request_now = lambda offer: (self.fx.request, None)
        self.notice_fails = False
        self.service = OwnerApprovals(
            self.fx.grants, development_issuer=self.issuer, publication_issuer=self.publication,
            development_request=lambda offer: self.request_now(offer),
            alfred_os_uid=ALFRED_OS, notice_sender=self.notice, pin_path=self.pin_path,
            pin_owner=os.geteuid(), clock=lambda: self.now)

    def notice(self, space, text):
        if self.notice_fails:
            raise OSError("sidecar down")
        self.notices.append((space, text))
        return "notice-id"

    def call(self, request, peer=ALFRED_OS):
        return handle(self.service, request, peer)

    def stage(self, **kwargs):
        return self.issuer.stage(self.fx.request, space_id="dm-owner", peer_uid=0, **kwargs)

    def open(self, offer, action="approve"):
        return self.call({"op": "open_owner_approval", "offer": offer, "action": action})

    def sign(self, opened, **kwargs):
        return self.key.assertion(passkey.b64url_decode(opened["webauthn"]["challenge"]), **kwargs)

    def answer(self, opened, assertion=None, **kwargs):
        return self.call({"op": "answer_owner_approval", "reference": opened["reference"],
                          "assertion": assertion or self.sign(opened, **kwargs)})

    def authority(self):
        return ProtectedDevelopmentAuthority(self.fx.grants, environment="staging",
                                             clock=lambda: self.now,
                                             owner_passkey_pin=self.pin_path)

    def files(self, pattern):
        return sorted(p.name for p in self.fx.grants.glob(pattern))


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.fx.doCleanups()


def test_offer_open_approve_grants_and_verify_rechecks_the_signature(world):
    staged = world.stage()
    offer = staged["challenge"]
    assert staged["state"] == "awaiting_alfred_os_owner_passkey" and not world.texts
    listed = world.call({"op": "list_owner_approvals"})["approvals"]
    assert listed == [{"offer": offer, "kind": "development", "project": "dev-999",
                       "task_id": "T-0099", "title": "dev-999 T-0099",
                       "expires_at": world.now + owner_approval.OFFER_MAX_AGE}]
    opened = world.open(offer)
    assert set(opened) == {"reference", "kind", "action", "statement", "human_text",
                           "challenge_text_sha256", "expires_at", "webauthn"}
    assert opened["webauthn"] == {
        "challenge": passkey.b64url(passkey.statement_digest(opened["statement"])),
        "rpId": "localhost", "userVerification": "required", "timeout": 120000,
        "allowCredentials": [{"id": world.key.credential_id, "type": "public-key"}]}
    assert opened["expires_at"] == world.now + 300
    assert opened["statement"]["request"] == world.fx.request
    assert opened["human_text"] == owner_grants._challenge_text(world.fx.request)
    assert world.notices == [("dm-owner", "Approval opened in Alfred OS: dev-999 T-0099 "
                              + world.fx.request["plan_sha256"][:12])]
    assert world.answer(opened) == {"result": "approved"}
    grant = world.authority().verify(offer, world.fx.expected())
    assert grant["source"] == "alfred_os_owner_passkey"
    assert world.call({"op": "list_owner_approvals"}) == {"approvals": []}


def test_the_approved_grant_runs_the_developer_pipeline(world):
    offer = world.stage()["challenge"]
    assert world.answer(world.open(offer)) == {"result": "approved"}
    reports, _ = dx.execute_approved(
        world.fx.inputs, project="dev-999", task_id="T-0099",
        worktree_root=world.fx.worktrees, scope=["calculator.py"], grant_reference=offer,
        grant_root=world.fx.grants, items=world.fx.items, models=world.fx.models,
        state_root=world.fx.root / "state", total_cost_limit=3,
        broker=dx.FixtureBroker(), grant_environment="staging",
        owner_passkey_pin=world.pin_path)
    assert reports[0]["status"] == "completed"


@pytest.mark.parametrize("name,kwargs", [
    ("wrong origin", {"origin": "http://localhost:3101"}),
    ("wrong rp_id", {"rp_id": "evil.example"}),
    ("cross origin", {"cross_origin": True}),
    ("user presence unset", {"flags": 0x04}),
    ("user verification unset", {"flags": 0x01}),
    ("registration type", {"client_type": "webauthn.create"}),
    ("wrong credential", {"credential_id": passkey.b64url(b"other-credential")}),
    ("forged signature", {"signer": fixture.Authenticator()}),
])
def test_forged_or_weak_assertions_are_refused(world, name, kwargs):
    offer = world.stage()["challenge"]
    opened = world.open(offer)
    assert world.answer(opened, **kwargs) == {"error": "not_verified"}, name
    assert not world.files("grant-*") and not world.files("owner-passkey-decided-*")


def test_wrong_challenge_is_refused(world):
    opened = world.open(world.stage()["challenge"])
    assertion = world.key.assertion(hashlib.sha256(b"Alfred OS login challenge").digest())
    assert world.answer(opened, assertion) == {"error": "not_verified"}


def test_approve_and_decline_signatures_cannot_be_swapped(world):
    offer = world.stage()["challenge"]
    approve = world.open(offer, "approve")
    signed_approve = world.sign(approve)
    decline = world.open(offer, "decline")
    assert world.answer(decline, signed_approve) == {"error": "not_verified"}
    assert world.answer(approve, signed_approve) == {"error": "expired"}   # superseded
    signed_decline = world.sign(decline)
    again = world.open(offer, "approve")
    assert world.answer(again, signed_decline) == {"error": "not_verified"}
    assert not world.files("grant-*") and not world.files("*decline*")


def test_decline_stops_the_offer_and_task_and_a_later_approve_is_refused(world):
    offer = world.stage()["challenge"]
    assert world.answer(world.open(offer, "decline")) == {"result": "declined"}
    assert world.files("development-passkey-decline-*") == [f"development-passkey-decline-{offer}.json"]
    assert not world.files("grant-*") and not world.files("issuance-*")
    assert world.open(offer, "approve") == {"error": "already_decided"}
    with pytest.raises(Denied):
        world.authority().verify(offer, world.fx.expected())
    with pytest.raises(Denied):
        world.stage()
    from fresh_v1.host import Held, Host
    host = Host.__new__(Host)
    host.p, host.uids = {"grant_root": str(world.fx.grants)}, {"alfred": os.geteuid()}
    with pytest.raises(Held, match="declined"):
        host.development_grant({}, offer)


def test_one_answer_per_offer_and_signature_single_use(world):
    offer = world.stage()["challenge"]
    opened = world.open(offer)
    assertion = world.sign(opened)
    assert world.answer(opened, assertion) == {"result": "approved"}
    assert world.answer(opened, assertion) == {"error": "already_decided"}
    assert world.answer(opened) == {"error": "already_decided"}


def test_a_used_signature_is_refused_even_without_a_decided_slot(world):
    opened = world.open(world.stage()["challenge"])
    assertion = world.sign(opened)
    digest = hashlib.sha256(passkey.b64url_decode(assertion["response"]["signature"])).hexdigest()
    owner_grants._write_once(world.fx.grants, f"owner-passkey-signature-{digest}.json", {})
    assert world.answer(opened, assertion) == {"error": "not_verified"}


def test_crash_after_the_decided_slot_accepts_no_second_answer(world):
    offer = world.stage()["challenge"]
    opened = world.open(offer)
    owner_grants._write_once(world.fx.grants, f"owner-passkey-decided-{offer}.json", {"crash": 1})
    assert world.answer(opened) == {"error": "already_decided"}
    assert not world.files("grant-*")


def test_statement_and_offer_expire(world):
    offer = world.stage()["challenge"]
    opened = world.open(offer)
    assertion = world.sign(opened)
    world.now += 301
    assert world.answer(opened, assertion) == {"error": "expired"}
    world.now += owner_approval.OFFER_MAX_AGE
    assert world.open(offer) == {"error": "expired"}
    assert world.call({"op": "list_owner_approvals"}) == {"approvals": []}


def test_sign_count_must_advance_and_zero_needs_synced_passkeys_allowed(world):
    fixture.write_pin(world.pin_path, world.key.pin(sign_count=5))
    world.key.sign_count = 5
    offer = world.stage()["challenge"]
    assert world.answer(world.open(offer), advance=False) == {"error": "not_verified"}
    assert world.answer(world.open(offer)) == {"result": "approved"}       # 6 > 5


def test_zero_sign_count_refused_when_the_pin_forbids_it(world):
    fixture.write_pin(world.pin_path, world.key.pin(allow_zero=False))
    assert world.answer(world.open(world.stage()["challenge"])) == {"error": "not_verified"}


def test_a_changed_plan_is_refused_at_open_and_at_answer(world):
    offer = world.stage()["challenge"]
    opened = world.open(offer)
    changed = {**world.fx.request, "scope": ["calculator.py", "other.py"]}
    world.request_now = lambda _offer: (changed, None)
    assert world.answer(opened) == {"error": "changed_since_review"}
    assert world.open(offer) == {"error": "changed_since_review"}
    assert not world.files("owner-passkey-decided-*")


def test_a_development_answer_never_verifies_for_publication(world):
    dev = world.open(world.stage()["challenge"])
    raw = pub_plan(world)
    pub_offer = world.publication.stage(raw, space_id="dm-owner", peer_uid=0)["challenge"]
    publication = world.open(pub_offer)
    assert world.answer(publication, world.sign(dev)) == {"error": "not_verified"}


def test_not_pinned_refuses_and_re_registering_in_alfred_os_fails_closed(world):
    offer = world.stage()["challenge"]
    opened = world.open(offer)
    world.key = fixture.Authenticator()          # the owner re-registered in Alfred OS
    assert world.answer(opened) == {"error": "not_verified"}
    world.pin_path.unlink()
    assert world.open(offer) == {"error": "not_pinned"}


def test_re_pinning_after_approval_makes_the_grant_non_executable(world):
    offer = world.stage()["challenge"]
    assert world.answer(world.open(offer)) == {"result": "approved"}
    fixture.write_pin(world.pin_path, fixture.Authenticator().pin())
    with pytest.raises(Denied):
        world.authority().verify(offer, world.fx.expected())


@pytest.mark.parametrize("field", ["authenticator_data", "client_data_json", "signature"])
def test_any_edit_to_the_stored_assertion_fails_verify(world, field):
    offer = world.stage()["challenge"]
    assert world.answer(world.open(offer)) == {"result": "approved"}
    path = world.fx.grants / f"development-passkey-decision-{offer}.json"
    record = json.loads(path.read_bytes())
    raw = bytearray(passkey.b64url_decode(record["assertion"][field]))
    raw[-1] ^= 1
    record["assertion"][field] = passkey.b64url(bytes(raw))
    path.write_bytes(owner_grants._bytes(record))
    with pytest.raises(Denied):
        world.authority().verify(offer, world.fx.expected())


def test_grant_edited_after_issuance_fails_verify(world):
    offer = world.stage()["challenge"]
    assert world.answer(world.open(offer)) == {"result": "approved"}
    path = world.fx.grants / f"grant-{offer}.json"
    grant = json.loads(path.read_bytes())
    grant["expires_at"] += 3600
    path.write_bytes(owner_grants._bytes(grant))
    with pytest.raises(Denied):
        world.authority().verify(offer, world.fx.expected())


def test_open_limits_and_notice_failure(world):
    offer = world.stage()["challenge"]
    world.notice_fails = True
    assert world.open(offer) == {"error": "busy"}
    assert not world.files("owner-passkey-challenge-*")
    world.notice_fails = False
    for _ in range(owner_approval.MAX_OPENS_PER_OFFER):
        assert "reference" in world.open(offer)
    assert world.open(offer) == {"error": "busy"}
    assert len(world.files("owner-passkey-expired-*")) == owner_approval.MAX_OPENS_PER_OFFER - 1


@pytest.mark.parametrize("request_,peer", [
    ({"op": "list_owner_approvals"}, 1234),
    ({"op": "list_owner_approvals", "extra": 1}, ALFRED_OS),
    ({"op": "stage_development_approval"}, ALFRED_OS),
    ({"op": "open_owner_approval", "offer": "0" * 32}, ALFRED_OS),
    ({"op": "open_owner_approval", "offer": "../x", "action": "approve"}, ALFRED_OS),
    ({"op": "open_owner_approval", "offer": "0" * 32, "action": "maybe"}, ALFRED_OS),
    ({"op": "answer_owner_approval", "reference": "0" * 32, "assertion": {"id": "x"}}, ALFRED_OS),
    ([], ALFRED_OS),
])
def test_wrong_peer_unknown_ops_and_extra_fields_are_invalid(world, request_, peer):
    world.stage()
    assert world.call(request_, peer) == {"error": "invalid"}


def test_unknown_offer_and_reference(world):
    assert world.open("0" * 32) == {"error": "unknown_offer"}
    assertion = world.key.assertion(b"\0" * 32)
    assert world.call({"op": "answer_owner_approval", "reference": "0" * 32,
                       "assertion": assertion}) == {"error": "unknown_offer"}


def test_simplewebauthn_extras_are_accepted_but_nothing_else(world):
    opened = world.open(world.stage()["challenge"])
    assertion = world.sign(opened)
    assertion["unexpected"] = True
    assert world.answer(opened, assertion) == {"error": "invalid"}


# --- channels -----------------------------------------------------------------------------

def test_imessage_channel_is_unchanged_and_alfred_os_offers_ignore_native_replies(world):
    staged = world.stage(channel="imessage")
    assert staged["state"] == "awaiting_native_owner_reply" and world.texts
    assert not world.files("owner-offer-*")


def test_alfred_os_offer_sends_no_text_and_ignores_replies(world):
    world.stage()
    event = {"messageId": "reply", "direction": "inbound", "sender": {"id": "owner"},
             "space": {"id": "dm-owner", "type": "dm"}, "nativeReplyTargetGuid": "anything",
             "nativeIsForward": False, "content": {"type": "text", "text": "yes"},
             "timestamp": "2026-10-18T00:00:00+00:00"}
    assert world.issuer.observe(event, peer_uid=1234) == {"state": "not_development_approval"}
    assert not world.texts


def test_policy_absent_means_imessage_and_invalid_policy_refuses(world, tmp_path):
    assert owner_approval.load_channel_policy(tmp_path / "absent.json",
                                              owner_uid=os.geteuid()) == "imessage"
    world.channel.write_text(json.dumps({"schema": owner_approval.CHANNEL_SCHEMA,
                                         "default": "both"}))
    world.channel.chmod(0o644)
    with pytest.raises(Denied):
        world.stage()
    with pytest.raises(Denied):
        owner_approval.resolve_channel("sms", world.channel, owner_uid=os.geteuid())


def test_alfred_os_offer_needs_the_pin(world):
    world.pin_path.unlink()
    with pytest.raises(Denied):
        world.stage()
    assert not world.files("owner-offer-*")


def test_only_one_development_approval_open_at_a_time(world):
    world.stage()
    other = {**world.fx.request, "task_id": "T-0100"}
    with pytest.raises(Denied, match="pending"):
        world.issuer.stage(other, space_id="dm-owner", peer_uid=0)


# --- publication ------------------------------------------------------------------------------

def pub_plan(world):
    plan = {"schema": "alfred.draft-pr-plan/1", "status": "READY_FOR_OWNER_AUTHORIZATION",
            **pub.BOUND, "qa_report_sha256": "a" * 64}
    raw = (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode()
    world._pub_patch = pytest.MonkeyPatch()
    world._pub_patch.setattr(pub, "PLAN_SHA", hashlib.sha256(raw).hexdigest())
    world.fx.addCleanup(world._pub_patch.undo)
    return raw


def test_publication_approve_prepares_one_draft_pr_authorization(world):
    raw = pub_plan(world)
    offer = world.publication.stage(raw, space_id="dm-owner", peer_uid=0)["challenge"]
    assert not world.texts
    opened = world.open(offer)
    assert opened["kind"] == "publication" and opened["statement"]["publication"]["plan_sha256"] == pub.PLAN_SHA
    assert world.answer(opened) == {"result": "approved"}
    record = world.publication.prepare(offer, peer_uid=0)
    assert record["owner_event_id"].startswith("alfred-os-passkey-")
    assert record["publication_plan_sha256"] == pub.PLAN_SHA
    with pytest.raises(Denied, match="already exists"):
        world.publication.stage(raw, space_id="dm-owner", peer_uid=0)


def test_publication_decision_must_come_from_the_alfred_os_peer(world):
    raw = pub_plan(world)
    offer = world.publication.stage(raw, space_id="dm-owner", peer_uid=0)["challenge"]
    assert world.answer(world.open(offer)) == {"result": "approved"}
    world.publication.alfred_os_uid = ALFRED_OS + 1
    with pytest.raises(Denied):
        world.publication.prepare(offer, peer_uid=0)


def test_publication_decline_writes_no_decision_and_blocks_the_plan(world):
    raw = pub_plan(world)
    offer = world.publication.stage(raw, space_id="dm-owner", peer_uid=0)["challenge"]
    assert world.answer(world.open(offer, "decline")) == {"result": "declined"}
    assert not world.files("publication-decision-*")
    with pytest.raises((Denied, FileNotFoundError)):
        world.publication.prepare(offer, peer_uid=0)
    with pytest.raises(Denied, match="declined"):
        world.publication.stage(raw, space_id="dm-owner", peer_uid=0)
    with pytest.raises(Denied, match="no publication decision"):
        world.publication.merge_authorization(
            raw, draft_pr_url=f"https://github.com/{pub.BOUND['destination']}/pull/1", peer_uid=0)
    from fresh_v1.host import Held, Host
    host = Host.__new__(Host)
    host.p, host.uids = {"grant_root": str(world.fx.grants)}, {"alfred": os.geteuid()}
    with pytest.raises(Held, match="declined"):
        host.publication_expired(offer)
    with pytest.raises(Held, match="declined"):
        host.publication_authorization({}, offer)


# --- the socket and the Intake ------------------------------------------------------------

def exchange(path, payload: bytes) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(path))
        client.sendall(payload)
        data = b""
        while not data.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data)


def test_owner_socket_framing_peer_and_acl(world, tmp_path):
    from developer_v1 import trusted_intake_development as intake
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    path = run / "owner-approval.sock"
    world.service.alfred_os_uid = os.geteuid()
    try:
        intake.serve_owner_approvals(path, world.service, os.geteuid())
    except OSError:
        pytest.skip("POSIX ACLs unavailable here")
    if not path.exists():
        pytest.skip("POSIX ACLs unavailable here")
    acl = os.getxattr(path, "system.posix_acl_access")
    assert len(acl) == 4 + 5 * 8
    assert exchange(path, b'{"op":"list_owner_approvals"}\n') == {"approvals": []}
    assert exchange(path, b'{"op":"nope"}\n') == {"error": "invalid"}
    assert exchange(path, b"x" * (70 * 1024) + b"\n") == {"error": "invalid"}
    world.service.alfred_os_uid = os.geteuid() + 1
    assert exchange(path, b'{"op":"list_owner_approvals"}\n') == {"error": "invalid"}


GOOD_SETTINGS = {"schema": "alfred.owner-approval-intake/1",
                 "owner_approval_socket": "/run/alfred-development-intake/owner-approval.sock",
                 "alfred_os_uid": 977,
                 "owner_passkey_pin": "/etc/alfred-development/owner-passkey.json",
                 "approval_channel_policy": "/etc/alfred-development/approval-channel.json"}


@pytest.mark.parametrize("change", [
    {"owner_approval_socket": "/tmp/x.sock"}, {"alfred_os_uid": 0}, {"alfred_os_uid": "977"},
    {"owner_passkey_pin": "/var/lib/alfred-os/owner-passkey.json"}, {"extra": 1},
    {"schema": "alfred.owner-approval-intake/2"},
])
def test_intake_owner_approval_settings_are_root_owned_and_exact(tmp_path, change):
    from developer_v1 import trusted_intake_development as intake
    path = tmp_path / "owner-approval.json"
    assert intake._owner_approval_config(path, owner_uid=os.geteuid()) is None   # absent: off
    path.write_text(json.dumps(GOOD_SETTINGS))
    path.chmod(0o644)
    assert intake._owner_approval_config(path, owner_uid=os.geteuid())["uid"] == 977
    with pytest.raises(ValueError):
        intake._owner_approval_config(path, owner_uid=os.geteuid() + 1)          # not root's
    path.write_text(json.dumps({**GOOD_SETTINGS, **change}))
    with pytest.raises(ValueError):
        intake._owner_approval_config(path, owner_uid=os.geteuid())


def test_intake_stage_ops_validate_the_channel():
    from developer_v1 import trusted_intake_development as intake
    assert intake._channel({}) is None and intake._channel({"channel": "alfred_os"}) == "alfred_os"
    with pytest.raises(Denied):
        intake._channel({"channel": "both"})


# --- enrollment -----------------------------------------------------------------------------

def test_enrollment_pins_the_alfred_os_login_passkey_only_after_a_test_signature(tmp_path):
    from developer_v1 import enroll_owner_passkey as enroll
    key = fixture.Authenticator()
    source = tmp_path / "owner-passkey.json"
    source.write_text(json.dumps({"passkeys": [
        {"id": key.credential_id, "publicKey": passkey.b64url(key.cose()), "counter": 0,
         "rpId": "localhost", "createdAt": "2026-10-18T00:00:00Z"},
        {"id": "other", "publicKey": "x", "rpId": "alfred.tailnet.ts.net"}]}))
    entry = enroll.alfred_os_passkey(source, "localhost")
    pin = enroll.candidate(entry, rp_id="localhost", origin="http://localhost:3100",
                           allow_zero=True, now=1.0)
    challenge = enroll.enrollment_challenge(pin, b"\1" * 32, 1.0)
    final = enroll.verify_enrollment(pin, key.assertion(challenge), challenge)
    assert passkey.validate_pin(final)["origins"] == ["http://localhost:3100"]
    assert passkey.pin_fingerprint(final["public_key"]) == hashlib.sha256(key.cose()).hexdigest()
    with pytest.raises(passkey.NotVerified):
        enroll.verify_enrollment(pin, fixture.Authenticator().assertion(challenge), challenge)
    with pytest.raises(passkey.NotVerified):
        enroll.verify_enrollment(pin, key.assertion(b"\0" * 32), challenge)
    text = enroll.snippet(challenge, final)
    assert passkey.b64url(challenge) in text and final["credential_id"] in text
    assert "__" not in text and "userVerification:'required'" in text


def test_enrollment_refuses_non_root_and_unprotected_pin_directories(tmp_path):
    from developer_v1 import enroll_owner_passkey as enroll
    if os.geteuid() != 0:
        assert enroll.main(["show"]) == 2
    with pytest.raises(SystemExit):
        enroll.install(fixture.Authenticator().pin(), tmp_path / "pin.json", replace=False)
