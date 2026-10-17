# Task A v0.1.4 corrective status — not a release

This workspace is a reviewable work-in-progress against the immutable v0.1.3
archive. **No v0.1.4 archive, SHA-256 release digest, or payload manifest was
built.** The release rule requires complete corrections first. No installed
Hermes, Photon, Gateway, service, identity, credential or protected state was
changed.

## Provider delivery investigation

The installed `@spectrum-ts/core` and `@spectrum-ts/imessage` packages are
12.7.0. The core `resumableOrderedStream` holds `lastCursor` in process memory
(`core/dist/authoring.js:199`), catches up only when that cursor exists
(`:395-398`), and on cursor rejection resets it and explicitly accepts an
event gap (`:272-275`). iMessage exposes `events.catchUp` and
`messages.subscribeEvents` (`imessage/dist/index.js:2425-2462`), but this
high-level iterator has no persistent resume cursor or explicit durable
acknowledgement. A subsequent source investigation found that the installed
lower-level `@photon-ai/advanced-imessage` API *does* expose a documented
durable `events.catchUp(since)` event log and paged message history. The
provider's retention floor, complete replay window and catch-up/live handoff
remain unverified; see `PHOTON_DELIVERY_DURABILITY_CONTRACT.md`.
Iterator yield is not a durable acceptance point. Live/provider behavior
remains unverified; these observations must not be described as a provider
redelivery guarantee.

The fail-closed staging state is in `task_a/durable.py:27-168` and
`task_a/photon_front.py:183-228,254-321`. Protected observations retain
immutable identity, text, timestamp, handle, lifecycle and continuity in an
fsynced owner-only journal. Real events are `unverified`, never queued for
Hermes, never eligible for `/reply` or `/submit`, and survive handle expiry as
unresolved records. The sidecar's `held` decision removes a record from its
local spool only after broker journal acceptance and does not issue a read
receipt (`patches/photon-durable-spool.mjs.txt`). This preserves evidence for
events that reached the sidecar, but **cannot account for an event lost before
the first spool fsync**. No real-event promotion path is supplied. A provider
continuity proof or separately approved reconciliation design is required
before real intake can be enabled. Journal saturation stops admission at 1,024
records instead of silently dropping unresolved work.

## Previous independent findings

| Finding | Status | Correction and local evidence | Blocking remainder |
| --- | --- | --- | --- |
| H1 protected launch | PARTIAL | The existing complete proposed entry point and socket/credential templates remain; disposable child lifecycle coverage is in `tests/test_service.py`. | Actual systemd activation, protected UID/group, credentials and SDK launch require isolated Linux acceptance. |
| H2 inbox durability and permissions | PARTIAL | `task_a/transport.py:92-183,219-281` uses `RENAME_NOREPLACE`, file fsync, filesystem sync, private prepared/sent ledger fsync and exact-file resync before retry commit. `tests/test_broker_transport.py:117-225` injects all commit boundaries and checks create-only access. | Cross-UID ACL, Gateway readability, filesystem power-loss semantics and pre-rename orphan cleanup require isolated Linux review. |
| H3 exact event-to-turn binding | PARTIAL | `make_photon_patch.py:161-207` rebinds each original raw event when the installed Gateway starts a processing/drain job, rejects text modified by a merge, and prevents context inheritance. `tests/test_reply_binding.py:78-159` exercises concurrency, queued drain and mismatch denial. | Installed Gateway still merges/discards same-chat pending events; a Hermes caller can present another observed live handle. No protected proof ties arbitrary response text to its generating turn. Patched full Hermes regression is incomplete. |
| H4 inbound durability | PARTIAL | `task_a/durable.py:60-176`, `task_a/photon_front.py:183-228` and the proposed sidecar spool preserve accepted observations, hold unverified events, avoid premature read receipts and retain expired records. `tests/test_durable.py:217-280` and `tests/test_sidecar_spool.py` cover synthetic crash/restart and held acknowledgement. | Provider replay before first fsync is unproven; no approved reconciliation procedure or live Photon crash test. Real filing is fail-closed. |
| M1 resource exhaustion | PARTIAL | Existing five-second request deadline, 32-handler cap, backlog 32 and queue limits remain in `task_a/photon_front.py:324-400`; journal is capped at 1,024 records. Staging resource tests pass. | Kernel slow-client soak and service memory/FD measurement require isolated Linux. |
| M2 audit | PARTIAL | `task_a/audit.py:14-53` records every handled denial as a code-only fsynced record and fails closed at 4 MiB; front and inbox retry paths emit privacy-safe codes. Tests cover forged handles, repeated denials, capacity, retries and recovery. | SDK/OTel diagnostic privacy, operator log rotation and end-to-end service failures need separate review. |

## Broker inbox commit protocol

1. Check the canonical envelope and derive its fixed request filename.
2. Under a private ledger lock, fsync a prepared record containing the exact
   envelope bytes; fsync the ledger directory.
3. Create a temporary file in the create-only inbox, write and fsync it.
4. Atomically rename without replacement using Linux `renameat2` and
   `RENAME_NOREPLACE`; `syncfs` the file's filesystem without granting the
   broker directory read permission.
5. If retry sees the final name, open it with `O_NOFOLLOW`, verify type/link
   count, byte count and exact bytes, fsync the file and `syncfs` before commit.
6. Fsync the private ledger's `sent` state and directory. A repeated `sent`
   returns the same request ID. A missing inbox file after `sent` is consistent
   with Gateway consumption; the broker does not republish.

Crash before rename can leave a temporary file that the broker cannot list.
That is an availability/cleanup issue and must not be addressed by broadening
the create-only ACL. Crash after rename but before `syncfs` is reconciled by
step 5. A corrupted or conflicting final file fails closed. Actual power-loss
durability remains a separate filesystem measurement.

## Independent review checklist

- Reproduce upstream source hashes, proposed patch generation and `git apply
  --check` against the pinned installed Hermes tree. Inspect every sidecar
  route and SDK operation reachable through the restricted socket.
- Establish provider event retention, cursor persistence and explicit ack
  behavior from supported documentation or an authenticated disposable account.
  Inject process death before the first spool fsync, cursor rejection, restart,
  and delayed/reordered events. Keep real filing disabled without proof.
- Trace sidecar event through Hermes queue, debounce/merge, tool calls,
  cancellation, replay and every send path. Demonstrate that no live handle
  swap or same-chat loss can occur before accepting H3.
- Run actual separate-UID socket activation, broker/Gateway inbox ACL, file
  ownership, directory no-list behavior, 32-client slow-header/body soak,
  crash/power-loss recovery, and health/shutdown tests on disposable Linux.
- Run unmodified and patched full Hermes Photon suites with the same pinned
  Node and `pytest-asyncio`, including media tests requiring explicit Task A
  compatibility decisions. Confirm Evidence Bridge v0.2.1 and canonical
  Gateway envelope/authority in a separate authorized test setup.
- Review SDK/OTel diagnostics and log rotation for credential, principal,
  cursor or content disclosure. Confirm no real Gateway execution or approval
  path is reachable.

These checks are independent acceptance work, not a production authorization.
