"""Root only: pin, check or remove the owner passkey V1 trusts for Alfred OS approvals.

    sudo ... -m developer_v1.enroll_owner_passkey show
    sudo ... -m developer_v1.enroll_owner_passkey pin [--replace]
    sudo ... -m developer_v1.enroll_owner_passkey remove

`pin` takes the owner's existing Alfred OS login passkey (credential ID and COSE public
key) from Alfred OS's file, shows its fingerprint to compare with Settings → Passkey,
then asks for a test signature: paste the printed snippet into the browser console of
the Alfred OS tab (http://localhost:3100), approve with Face ID / Touch ID, and paste the
line it prints back here. The pin is installed (root:root 0644) only if that signature
verifies. Re-registering the passkey in Alfred OS does not change the pin, so approvals
fail closed until this is run again with --replace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from pathlib import Path

from . import owner_passkey as passkey

ALFRED_OS_PASSKEYS = Path("/var/lib/alfred-os/owner-passkey.json")
RP_ID = "localhost"
ORIGIN = "http://localhost:3100"
ENROLL_SCHEMA = "alfred.owner-passkey-enrollment/1"
ANSWER_SECONDS = 300

SNIPPET = (
    "(async()=>{const b=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')"
    "+'==='.slice((s.length+3)%4)),c=>c.charCodeAt(0));const e=a=>btoa(String.fromCharCode("
    "...new Uint8Array(a))).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');"
    "const c=await navigator.credentials.get({publicKey:{challenge:b('__CHALLENGE__'),"
    "rpId:'__RP_ID__',allowCredentials:[{id:b('__CREDENTIAL__'),type:'public-key'}],"
    "userVerification:'required',timeout:120000}});console.log(JSON.stringify({id:c.id,"
    "rawId:e(c.rawId),type:c.type,response:{clientDataJSON:e(c.response.clientDataJSON),"
    "authenticatorData:e(c.response.authenticatorData),signature:e(c.response.signature),"
    "userHandle:c.response.userHandle?e(c.response.userHandle):null}}))})()")


def snippet(challenge: bytes, pin: dict) -> str:
    """The browser-console call; every value inserted is base64url or a host name."""
    return (SNIPPET.replace("__CHALLENGE__", passkey.b64url(challenge))
            .replace("__RP_ID__", pin["rp_id"]).replace("__CREDENTIAL__", pin["credential_id"]))


def alfred_os_passkey(path: Path, rp_id: str) -> dict:
    """The one Alfred OS passkey for this relying party, read once at enrollment."""
    data = json.loads(path.read_bytes())
    found = [p for p in data.get("passkeys", []) if type(p) is dict and p.get("rpId") == rp_id]
    if len(found) != 1:
        raise SystemExit(f"expected one Alfred OS passkey for {rp_id}, found {len(found)}")
    entry = found[0]
    passkey.cose_es256_key(passkey.b64url_decode(entry["publicKey"]))
    passkey.b64url_decode(entry["id"], limit=1400)
    return entry


def candidate(entry: dict, *, rp_id: str, origin: str, allow_zero: bool, now: float) -> dict:
    return passkey.validate_pin({
        "schema": passkey.PIN_SCHEMA, "credential_id": entry["id"],
        "public_key": entry["publicKey"], "alg": passkey.ES256, "rp_id": rp_id,
        "origins": [origin], "allow_zero_sign_count": allow_zero, "sign_count": 0,
        "enrolled_at": now})


def enrollment_challenge(pin: dict, nonce: bytes, now: float) -> bytes:
    """A test statement no approval can collide with (its own schema)."""
    return hashlib.sha256(ENROLL_SCHEMA.encode() + b"\n" + passkey.canonical({
        "schema": ENROLL_SCHEMA, "credential_id": pin["credential_id"],
        "rp_id": pin["rp_id"], "nonce": passkey.b64url(nonce), "issued_at": now})).digest()


def verify_enrollment(pin: dict, assertion: object, challenge: bytes) -> dict:
    """The pin to install: the candidate with the test assertion's sign count."""
    passkey.check_assertion_shape(assertion)
    result = passkey.verify_raw(pin, passkey.raw_assertion(assertion), challenge,
                                last_sign_count=0)
    return {**pin, "sign_count": result["sign_count"]}


def install(pin: dict, path: Path, *, replace: bool) -> None:
    passkey.validate_pin(pin)
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise SystemExit(f"{path.parent} must be a root-owned directory")
    if path.exists() and not replace:
        raise SystemExit("a pin is already installed; use --replace to re-pin")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as stream:
        os.fchown(stream.fileno(), 0, 0)
        os.fchmod(stream.fileno(), 0o644)
        stream.write(json.dumps(pin, indent=2, sort_keys=True).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    passkey.load_pin(path, owner_uid=0)


def main(argv=None) -> int:
    if os.geteuid() != 0:
        print("Run as root.", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(prog="enroll_owner_passkey")
    parser.add_argument("operation", choices=("show", "pin", "remove"))
    parser.add_argument("--from", dest="source", type=Path, default=ALFRED_OS_PASSKEYS)
    parser.add_argument("--rp-id", default=RP_ID)
    parser.add_argument("--origin", default=ORIGIN)
    parser.add_argument("--no-synced-passkeys", action="store_true",
                        help="refuse sign count 0 (default allows synced passkeys)")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    if args.operation == "remove":
        if input("Type REMOVE to stop all Alfred OS approvals until re-pinned: ").strip() != "REMOVE":
            return 1
        passkey.PIN_PATH.unlink(missing_ok=True)
        print(json.dumps({"state": "pin_removed"}))
        return 0
    if args.operation == "show":
        try:
            pin = passkey.load_pin(passkey.PIN_PATH, owner_uid=0)
        except passkey.NotPinned as exc:
            print(json.dumps({"state": "not_pinned", "reason": str(exc)}))
            return 1
        print(json.dumps({"state": "pinned", "credential_id": pin["credential_id"],
                          "fingerprint": passkey.pin_fingerprint(pin["public_key"]),
                          "rp_id": pin["rp_id"], "origins": pin["origins"],
                          "allow_zero_sign_count": pin["allow_zero_sign_count"]}))
        return 0
    now = time.time()
    entry = alfred_os_passkey(args.source, args.rp_id)
    pin = candidate(entry, rp_id=args.rp_id, origin=args.origin,
                    allow_zero=not args.no_synced_passkeys, now=now)
    fingerprint = passkey.pin_fingerprint(pin["public_key"])
    print(f"Credential: {pin['credential_id']}\nFingerprint: {fingerprint}")
    typed = input("Type the first 12 characters of the fingerprint Alfred OS shows: ").strip()
    if typed != fingerprint[:12]:
        print("Fingerprint not confirmed; nothing installed.", file=sys.stderr)
        return 1
    challenge = enrollment_challenge(pin, os.urandom(32), now)
    print("In the Alfred OS tab at " + args.origin + ", open the browser console, paste this,"
          " approve with Face ID / Touch ID, and paste the printed line below:\n")
    print(snippet(challenge, pin) + "\n")
    line = sys.stdin.readline()
    if time.time() - now > ANSWER_SECONDS:
        print("Too late; nothing installed.", file=sys.stderr)
        return 1
    try:
        final = verify_enrollment(pin, json.loads(line), challenge)
    except (ValueError, passkey.NotVerified) as exc:
        print(f"Test signature did not verify ({exc}); nothing installed.", file=sys.stderr)
        return 1
    install(final, passkey.PIN_PATH, replace=args.replace)
    print(json.dumps({"state": "pinned", "fingerprint": fingerprint,
                      "sign_count": final["sign_count"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
