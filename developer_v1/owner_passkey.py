"""WebAuthn passkey assertions for owner approvals in Alfred OS. Standard library only.

V1 trusts exactly one passkey: the public key root pins in
/etc/alfred-development/owner-passkey.json (`enroll_owner_passkey`). Alfred OS's own
passkey file is never read at run time, so re-registering the login passkey there
makes approvals fail closed until root re-pins.

Verification is ES256 (ECDSA P-256 with SHA-256) over
`authenticatorData || SHA-256(clientDataJSON)`, written out here with Python integers
instead of a new dependency. It only verifies public data, so it holds no secret that
timing could leak. Tests check it against the `cryptography` package when present.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from .router import Denied

PIN_PATH = Path("/etc/alfred-development/owner-passkey.json")
PIN_SCHEMA = "alfred.owner-passkey-pin/1"
STATEMENT_SCHEMA = "alfred.owner-passkey-statement/1"
ES256 = -7
MAX_PIN = 4096
MAX_FIELD = 4096
B64URL = re.compile(r"[A-Za-z0-9_-]*\Z")
ORIGIN = re.compile(r"https?://[a-z0-9.-]+(:[0-9]{1,5})?\Z")
FLAG_UP, FLAG_UV = 0x01, 0x04

# NIST P-256.
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


class NotVerified(Denied):
    """The assertion does not prove the pinned owner signed this exact statement."""


class NotPinned(Denied):
    """No usable root-installed pin."""


# --- encodings ---------------------------------------------------------------------------

def b64url_decode(value: object, *, limit: int = MAX_FIELD) -> bytes:
    if type(value) is not str or len(value) > limit or not B64URL.fullmatch(value):
        raise NotVerified("not base64url")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise NotVerified("not base64url") from exc
    if b64url(raw) != value:
        raise NotVerified("non-canonical base64url")
    return raw


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def statement_digest(statement: dict) -> bytes:
    """The WebAuthn challenge: covers kind, action, offer and every bound field."""
    return hashlib.sha256(STATEMENT_SCHEMA.encode() + b"\n" + canonical(statement)).digest()


def _cbor_item(data: bytes, i: int):
    if i >= len(data):
        raise NotVerified("truncated CBOR")
    major, info = data[i] >> 5, data[i] & 0x1F
    i += 1
    if info < 24:
        value = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if i + size > len(data):
            raise NotVerified("truncated CBOR")
        value = int.from_bytes(data[i:i + size], "big")
        i += size
    else:
        raise NotVerified("unsupported CBOR")
    if major == 0:
        return value, i
    if major == 1:
        return -1 - value, i
    if major in (2, 3):
        if i + value > len(data):
            raise NotVerified("truncated CBOR")
        chunk = data[i:i + value]
        return (chunk if major == 2 else chunk.decode("utf-8")), i + value
    if major == 5:
        result = {}
        for _ in range(value):
            key, i = _cbor_item(data, i)
            if type(key) not in (int, str) or key in result:
                raise NotVerified("invalid CBOR map")
            result[key], i = _cbor_item(data, i)
        return result, i
    raise NotVerified("unsupported CBOR")


def cose_es256_key(raw: bytes) -> tuple[int, int]:
    """(x, y) of a COSE EC2 P-256 ES256 public key; anything else is refused."""
    try:
        key, end = _cbor_item(raw, 0)
    except UnicodeError as exc:
        raise NotVerified("invalid COSE key") from exc
    if (end != len(raw) or type(key) is not dict or set(key) != {1, 3, -1, -2, -3}
            or key[1] != 2 or key[3] != ES256 or key[-1] != 1
            or type(key[-2]) is not bytes or type(key[-3]) is not bytes
            or len(key[-2]) != 32 or len(key[-3]) != 32):
        raise NotVerified("public key is not ES256 P-256")
    point = (int.from_bytes(key[-2], "big"), int.from_bytes(key[-3], "big"))
    if not _on_curve(point):
        raise NotVerified("public key is not on P-256")
    return point


def der_signature(raw: bytes) -> tuple[int, int]:
    """Strict DER ECDSA signature: SEQUENCE { INTEGER r, INTEGER s }, minimal encoding."""
    def integer(i):
        if i + 2 > len(raw) or raw[i] != 0x02:
            raise NotVerified("invalid signature encoding")
        size = raw[i + 1]
        body = raw[i + 2:i + 2 + size]
        if (size == 0 or size > 33 or len(body) != size or body[0] & 0x80
                or (size > 1 and body[0] == 0 and not body[1] & 0x80)):
            raise NotVerified("invalid signature encoding")
        return int.from_bytes(body, "big"), i + 2 + size
    if len(raw) < 8 or raw[0] != 0x30 or raw[1] != len(raw) - 2:
        raise NotVerified("invalid signature encoding")
    r, i = integer(2)
    s, i = integer(i)
    if i != len(raw):
        raise NotVerified("invalid signature encoding")
    return r, s


# --- P-256 ---------------------------------------------------------------------------------

def _on_curve(point) -> bool:
    x, y = point
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        slope = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (slope * slope - x1 - x2) % P
    return x3, (slope * (x1 - x3) - y1) % P


def _multiply(k: int, point):
    result, addend = None, point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def es256_verify(public: tuple[int, int], message: bytes, signature: bytes) -> bool:
    r, s = der_signature(signature)
    if not (1 <= r < N and 1 <= s < N) or not _on_curve(public):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, N)
    point = _add(_multiply(e * w % N, G), _multiply(r * w % N, public))
    return point is not None and point[0] % N == r


# --- the root-installed pin -----------------------------------------------------------------

def pin_fingerprint(public_key_b64: str) -> str:
    """SHA-256 of the COSE public key bytes, as Alfred OS shows under Settings → Passkey."""
    return hashlib.sha256(b64url_decode(public_key_b64)).hexdigest()


def validate_pin(pin: object) -> dict:
    if (type(pin) is not dict
            or set(pin) != {"schema", "credential_id", "public_key", "alg", "rp_id", "origins",
                            "allow_zero_sign_count", "sign_count", "enrolled_at"}
            or pin["schema"] != PIN_SCHEMA or pin["alg"] != ES256
            or type(pin["rp_id"]) is not str or not re.fullmatch(r"[a-z0-9.-]{1,253}", pin["rp_id"])
            or type(pin["origins"]) is not list or not 1 <= len(pin["origins"]) <= 4
            or len(set(pin["origins"])) != len(pin["origins"])
            or any(type(o) is not str or not ORIGIN.fullmatch(o) for o in pin["origins"])
            or type(pin["allow_zero_sign_count"]) is not bool
            or type(pin["sign_count"]) is not int or not 0 <= pin["sign_count"] < 2 ** 32
            or type(pin["enrolled_at"]) not in (int, float)):
        raise NotPinned("owner passkey pin invalid")
    try:
        if not b64url_decode(pin["credential_id"], limit=1400):
            raise NotPinned("owner passkey pin invalid")
        cose_es256_key(b64url_decode(pin["public_key"]))
    except NotVerified as exc:
        raise NotPinned("owner passkey pin invalid") from exc
    return pin


def load_pin(path: Path | None = PIN_PATH, *, owner_uid: int = 0) -> dict:
    """The root-pinned key, with the delegation policy's file checks. Raises NotPinned."""
    if path is None:
        raise NotPinned("no owner passkey pin configured")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise NotPinned("owner passkey pin unavailable") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner_uid
                or info.st_mode & 0o022 or info.st_size > MAX_PIN):
            raise NotPinned("owner passkey pin is not root-protected")
        raw = stream.read(MAX_PIN + 1)
    try:
        pin = json.loads(raw)
    except ValueError as exc:
        raise NotPinned("owner passkey pin is not JSON") from exc
    return validate_pin(pin)


# --- the assertion ------------------------------------------------------------------------

ASSERTION_KEYS = {"id", "rawId", "type", "response"}
# @simplewebauthn/browser also returns these; they carry nothing V1 relies on.
OPTIONAL_KEYS = {"clientExtensionResults", "authenticatorAttachment"}
RESPONSE_KEYS = {"clientDataJSON", "authenticatorData", "signature"}


def check_assertion_shape(assertion: object) -> dict:
    """Exact structure, before any cryptography. Raises NotVerified."""
    if (type(assertion) is not dict or not ASSERTION_KEYS <= set(assertion)
            or set(assertion) - ASSERTION_KEYS - OPTIONAL_KEYS
            or assertion["type"] != "public-key" or assertion["id"] != assertion["rawId"]
            or type(assertion["response"]) is not dict
            or not RESPONSE_KEYS <= set(assertion["response"])
            or set(assertion["response"]) - RESPONSE_KEYS - {"userHandle"}
            or not (assertion["response"].get("userHandle") is None
                    or type(assertion["response"]["userHandle"]) is str)
            or type(assertion.get("clientExtensionResults", {})) is not dict
            or len(canonical(assertion.get("clientExtensionResults", {}))) > 512
            or assertion.get("authenticatorAttachment") not in (None, "platform", "cross-platform")):
        raise NotVerified("assertion shape invalid")
    b64url_decode(assertion["id"], limit=1400)
    for name in RESPONSE_KEYS:
        b64url_decode(assertion["response"][name])
    if assertion["response"].get("userHandle") is not None:
        b64url_decode(assertion["response"]["userHandle"], limit=128)
    return assertion


def raw_assertion(assertion: dict) -> dict:
    """What V1 stores and re-verifies: the signed bytes, nothing Alfred OS only reports."""
    response = assertion["response"]
    return {"credential_id": assertion["id"], "client_data_json": response["clientDataJSON"],
            "authenticator_data": response["authenticatorData"],
            "signature": response["signature"], "user_handle": response.get("userHandle")}


def verify_raw(pin: dict, raw: dict, challenge: bytes, *, last_sign_count: int | None) -> dict:
    """Checks 4 to 7 of the design. last_sign_count None skips the counter rule (used when
    re-verifying a stored decision). Returns the checks map and the new sign count."""
    if raw["credential_id"] != pin["credential_id"]:
        raise NotVerified("credential is not the pinned passkey")
    client_bytes = b64url_decode(raw["client_data_json"])
    try:
        client = json.loads(client_bytes)
    except (ValueError, UnicodeError) as exc:
        raise NotVerified("client data is not JSON") from exc
    if (type(client) is not dict or client.get("type") != "webauthn.get"
            or client.get("challenge") != b64url(challenge)
            or client.get("origin") not in pin["origins"]
            or client.get("crossOrigin", False) is not False):
        raise NotVerified("client data does not bind this statement")
    auth = b64url_decode(raw["authenticator_data"])
    if len(auth) < 37 or auth[:32] != hashlib.sha256(pin["rp_id"].encode()).digest():
        raise NotVerified("authenticator data is for another relying party")
    flags = auth[32]
    if not flags & FLAG_UP or not flags & FLAG_UV:
        raise NotVerified("user presence and verification are required")
    sign_count = int.from_bytes(auth[33:37], "big")
    public = cose_es256_key(b64url_decode(pin["public_key"]))
    message = auth + hashlib.sha256(client_bytes).digest()
    if not es256_verify(public, message, b64url_decode(raw["signature"])):
        raise NotVerified("signature does not verify with the pinned key")
    if last_sign_count is not None:
        floor = max(last_sign_count, pin["sign_count"])
        if sign_count == 0:
            if floor or not pin["allow_zero_sign_count"]:
                raise NotVerified("sign count did not advance")
        elif sign_count <= floor:
            raise NotVerified("sign count did not advance")
    return {"sign_count": sign_count,
            "checks": {"client_data_type": True, "statement_challenge": True,
                       "pinned_origin": True, "not_cross_origin": True,
                       "pinned_rp_id": True, "user_present": True, "user_verified": True,
                       "pinned_credential": True, "es256_signature": True}}
