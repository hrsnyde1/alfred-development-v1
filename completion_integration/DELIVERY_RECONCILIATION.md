# T-0002 completion delivery reconciliation

The owner confirms receipt of the completion iMessage. The notifier has no
durable successful acknowledgement for that attempt. These are separate facts.
Keep the original tracking record `uncertain`, with its missing receipt, and
record the owner's confirmation separately. No retry or code installation is
needed to close this notification operationally.

## Confirmed findings and diagnostic limit

- The installed library matches the reviewed manifest SHA-256
  `e315211f3c8e13d05e81598d77d9e64c0d92d3690cf186d9826968913eacde82`.
  Its runtime and tracker match staging; no production source was changed.
- The current configuration is disabled. Its SHA-256 is
  `ac029d591949d65a3a16f171a4cf9190787c978a8f61361eda6a475964395ba2`.
- The retained publication result is `PUBLISHED_DRAFT`, with the completion next
  stage. Result, plan, and separate authorization hashes match their installed
  configuration pins. The record's text digest matches the reviewed merged-PR
  completion text. There is no evidence here of a publication prerequisite
  mismatch causing this already received notification to fail.
- `delivery.json` SHA-256 is
  `917c0b7f273dffac784d820d0b7df560f8f5504b3f19f7f51ca3fea87475b9ac`.
  It contains version 1 and one uncertain record, last modified at
  `2026-10-16T08:52:54.088874Z`. Record key:
  `d7006f612a448bc2ac88181dfe919083ff03f329bdfcf6f4109df7c98b4b8c5d`.
  Text digest:
  `1821f2909c7cd58115019c385c772ccff1fd75f94581381fc4ac6f46ac2a9604`.
  Its `receipt_id` is null.
- The tracker writes/fsyncs uncertainty before calling Photon. A usable receipt
  and successful persistence are both needed to record `sent`. A missing
  receipt does not prove that Photon never returned an ID: failure while saving
  success can leave the earlier uncertain record, without that returned ID.
- The sender uses a two-second HTTP timeout, accepts only HTTP 200 with
  `ok:true` and a nonempty valid `messageId`, and makes no retry. The existing
  sidecar awaits `space.send()` before returning `result?.id || null`. The
  installed Spectrum declaration permits `Message | undefined`; there is no
  confirmed schema mismatch in expecting `messageId` from this sidecar.
- The CLI catches transport, acknowledgement, and tracking exceptions under
  the same generic `BLOCKED` response and discards the exception detail. That
  is the confirmed reason the terminal response cannot identify the failed
  phase. `BLOCKED` does not establish that no message was sent or received.
- Read-only Photon/Intake/Hermes journal inspection around 08:50–08:55 UTC
  yielded no matching entries, including outside the sandbox. Available recent
  Photon entries end at service startup at 07:36:53 UTC. Successful `/send`
  responses are not journaled by the inspected sidecar, and the on-demand CLI
  does not persist its caught exception. The historical exception type,
  response body, and elapsed request time are not available.

**The exact historical exception is not recoverable from this evidence.** A
response timeout, missing/invalid acknowledgement, or confirmation-write failure
can produce the same observed `BLOCKED` response and uncertain record after a
message reaches the owner. Do not report a timeout, missing ID response, disk
failure, or other transport defect as confirmed. No speculative timeout or
acknowledgement-policy change is prepared.

## Minimal operator recovery

1. Keep sending disabled. Do not invoke `notify` or `initialize`, change wording
   to obtain a different key, remove the record, or replace its lock/directory.
2. Retain the original `delivery.json` unchanged. The following optional
   administrator action makes an additional protected byte-identical snapshot
   and an owner-confirmation audit note. It does not set `sent`, create a Photon
   receipt, or authorize a send. The note is independent of the tracker state.
3. The owner statement is the direct statement in this reconciliation request:
   “The first T-0002 completion iMessage was successfully received by the owner.”
   Attribute it as owner confirmation. Do not manufacture a Photon ID, native
   message ID, owner event ID, or delivery/read timestamp. The note records its
   creation time only. If a genuine historical confirmation reference becomes
   available, preserve it separately with provenance.
4. Treat this completion notification as **owner-confirmed received** for the
   operator's completion review. Preserve the transport status as **uncertain**.
   The existing uncertain record remains the durable duplicate guard. The
   notifier does not interpret the audit note as a transport acknowledgement.

The block below is a reviewed future operator procedure, not executed by this
session. It takes the existing lock without creating/replacing it, verifies the
observed configuration/state hashes, and refuses to overwrite any prior audit
directory. The fixed hashes deliberately abort if the inspected evidence has
changed. It uses only standard-library code shown here, with no imported
staging implementation or network operation.

```sh
sudo /usr/bin/python3 -I -B <<'RECORD_OWNER_CONFIRMATION'
import datetime
import fcntl
import hashlib
import json
import os
import pwd
import stat
from pathlib import Path

assert os.geteuid() == 0
account = pwd.getpwnam('alfred')
root = Path('/home/alfred/Alfred/completion-delivery')
lock = os.open(root / 'delivery.lock', os.O_RDWR | os.O_NOFOLLOW)
try:
    info = os.fstat(lock)
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    assert info.st_uid == account.pw_uid and not (info.st_mode & 0o077)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    config_raw = Path('/etc/alfred-completion-v1/config.json').read_bytes()
    assert hashlib.sha256(config_raw).hexdigest() == 'ac029d591949d65a3a16f171a4cf9190787c978a8f61361eda6a475964395ba2'
    config = json.loads(config_raw)
    assert config['enabled'] is False
    source = root / 'delivery.json'
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert info.st_uid == account.pw_uid and not (info.st_mode & 0o077)
        raw = stream.read(1048577)
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == '917c0b7f273dffac784d820d0b7df560f8f5504b3f19f7f51ca3fea87475b9ac'
    state = json.loads(raw)
    key = 'd7006f612a448bc2ac88181dfe919083ff03f329bdfcf6f4109df7c98b4b8c5d'
    assert state['version'] == 1 and set(state['records']) == {key}
    record = state['records'][key]
    assert record['state'] == 'uncertain' and record.get('receipt_id') is None
    assert record['text_digest'] == '1821f2909c7cd58115019c385c772ccff1fd75f94581381fc4ac6f46ac2a9604'
    assert record['identity'] == ['dev-v1-accept', 'T-0002',
        'https://github.com/hrsnyde1/alfred-dev-v1-acceptance/pull/1',
        '89ba188f8a2f801d433a30c9c21363efb3e1043d']
    assert hashlib.sha256(json.dumps(record['identity'], separators=(',', ':')).encode()).hexdigest() == key
    note = {
        'schema': 'alfred.completion-owner-confirmation-audit/1',
        'resolution': 'owner_confirmed_received',
        'transport_state': 'uncertain',
        'photon_receipt_id': None,
        'tracking_state_sha256': digest,
        'record_key': key,
        'identity': record['identity'],
        'text_digest': record['text_digest'],
        'config_sha256': hashlib.sha256(config_raw).hexdigest(),
        'publication_result_sha256': config['publication-result-sha256'],
        'publication_plan_sha256': config['publication-plan-sha256'],
        'owner_confirmation_source': 'Direct owner completion delivery reconciliation request',
        'owner_confirmation_statement': 'The first T-0002 completion iMessage was successfully received by the owner.',
        'recorded_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'resend_permitted': False,
    }
    archive = Path('/etc/alfred-completion-v1/reconciliation-T-0002')
    archive.mkdir(mode=0o750)  # Refuses an existing directory; no overwrite.
    os.chown(archive, 0, account.pw_gid)
    os.chmod(archive, 0o750)
    def write_once(name, data):
        fd = os.open(archive / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        os.fchown(fd, 0, account.pw_gid)
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    write_once('delivery.original.json', raw)
    write_once('owner-confirmation.json', (json.dumps(note, indent=2, sort_keys=True) + '\n').encode())
    directory = os.open(archive, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    parent = os.open(archive.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    assert source.read_bytes() == raw
    assert Path('/etc/alfred-completion-v1/config.json').read_bytes() == config_raw
    print('Owner confirmation recorded separately; original uncertain state and disabled configuration preserved.')
finally:
    os.close(lock)
RECORD_OWNER_CONFIRMATION
```

If this block fails, preserve any partially created audit files and investigate;
do not change the source state or rerun over an existing audit directory. The
source and lock are never removed, rewritten, renamed, or recreated. There is
no service restart, resend, credential change, GitHub operation, or live grant
creation. Recording the note is optional; leaving the disabled notifier and
uncertain guard intact already prevents a duplicate.

## Staging verification

```sh
/home/alfred/Git/alfred/.venv/bin/python -m pytest -q tests/test_completion_reconciliation.py tests/test_completion_delivery.py tests/test_completion_integration.py
```

**70 passed**: four new reconciliation regressions plus the existing 66
completion/delivery cases. Mock delivery followed by response timeout, null
receipt, and success-persistence failure each reproduces the same generic
`BLOCKED` response and uncertain record without a receipt. All suppress a
subsequent send. A separate mock owner-confirmation note leaves the original
record unchanged through two fresh child processes.

Additionally, two fresh processes loaded the **installed tracker** against a
disposable byte-identical copy of the actual T-0002 uncertain record. Both
returned `uncertain` without invoking a send callback. The copied bytes, live
tracking bytes, and live disabled configuration bytes remained unchanged.

Only this procedure and `tests/test_completion_reconciliation.py` are added.
No notifier runtime, receipt policy, tracker schema, release pin, or installed
package is changed. The failure's precise historical exception remains an
explicit diagnostic limit; it is not necessary to resend to reconcile the
owner-confirmed receipt.
