"""A throwaway software passkey for tests and the post-install checker only.

It signs WebAuthn assertions exactly as a browser authenticator would, with a fresh
random P-256 key. It is never installed in /opt and never used for a real approval.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

from developer_v1 import owner_passkey as passkey

ORIGIN = "http://localhost:3100"
RP_ID = "localhost"


def _der(r: int, s: int) -> bytes:
    def integer(value):
        body = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
        if body[0] & 0x80:
            body = b"\x00" + body
        return b"\x02" + bytes([len(body)]) + body
    inner = integer(r) + integer(s)
    return b"\x30" + bytes([len(inner)]) + inner


class Authenticator:
    def __init__(self, *, rp_id: str = RP_ID, origin: str = ORIGIN, sign_count: int = 0):
        self.d = secrets.randbelow(passkey.N - 1) + 1
        self.public = passkey._multiply(self.d, passkey.G)
        self.credential_id = passkey.b64url(os.urandom(16))
        self.rp_id, self.origin, self.sign_count = rp_id, origin, sign_count

    def cose(self) -> bytes:
        x, y = (v.to_bytes(32, "big") for v in self.public)
        return bytes.fromhex("a5010203262001215820") + x + b"\x22\x58\x20" + y

    def pin(self, *, allow_zero: bool = True, sign_count: int = 0) -> dict:
        return {"schema": passkey.PIN_SCHEMA, "credential_id": self.credential_id,
                "public_key": passkey.b64url(self.cose()), "alg": passkey.ES256,
                "rp_id": self.rp_id, "origins": [self.origin],
                "allow_zero_sign_count": allow_zero, "sign_count": sign_count,
                "enrolled_at": 1.0}

    def sign(self, message: bytes) -> bytes:
        e = int.from_bytes(hashlib.sha256(message).digest(), "big")
        while True:
            k = secrets.randbelow(passkey.N - 1) + 1
            r = passkey._multiply(k, passkey.G)[0] % passkey.N
            s = pow(k, -1, passkey.N) * (e + r * self.d) % passkey.N
            if r and s:
                return _der(r, s)

    def assertion(self, challenge: bytes, *, origin: str | None = None,
                  rp_id: str | None = None, flags: int = 0x05, advance: bool = True,
                  client_type: str = "webauthn.get", cross_origin=None,
                  credential_id: str | None = None, signer=None) -> dict:
        """What @simplewebauthn/browser's startAuthentication returns."""
        if advance and self.sign_count:
            self.sign_count += 1
        client = {"type": client_type, "challenge": passkey.b64url(challenge),
                  "origin": origin or self.origin}
        if cross_origin is not None:
            client["crossOrigin"] = cross_origin
        client_bytes = json.dumps(client, separators=(",", ":")).encode()
        auth = (hashlib.sha256((rp_id or self.rp_id).encode()).digest() + bytes([flags])
                + self.sign_count.to_bytes(4, "big"))
        signature = (signer or self).sign(auth + hashlib.sha256(client_bytes).digest())
        credential = credential_id or self.credential_id
        return {"id": credential, "rawId": credential, "type": "public-key",
                "response": {"clientDataJSON": passkey.b64url(client_bytes),
                             "authenticatorData": passkey.b64url(auth),
                             "signature": passkey.b64url(signature), "userHandle": None},
                "clientExtensionResults": {}, "authenticatorAttachment": "platform"}


def write_pin(path: Path, pin: dict) -> None:
    path.write_text(json.dumps(pin))
    path.chmod(0o644)
