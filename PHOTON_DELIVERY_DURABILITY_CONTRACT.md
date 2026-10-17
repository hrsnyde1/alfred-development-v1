# Task A Photon inbound delivery and reconciliation contract

**Status: proposed fail-closed contract; provider completeness is unverified.**
This investigation used installed source and published SDK documentation, not
a live Photon account. Installed paths below are relative to
`/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/node_modules/`.

## What the installed code establishes

| Question | Source evidence | Finding |
| --- | --- | --- |
| Explicit receipt/ack | `@spectrum-ts/core/dist/authoring.js:223-231`, `@spectrum-ts/imessage/dist/index.js:2455-2462`; installed sidecar `../index.mjs:701-715` | The high-level iterator advances its process-local cursor when it emits, before sidecar fsync. There is no application-level durable-acceptance ack in this path. The sidecar's `acknowledgeInboundRead` is a **read receipt**, not a provider delivery ack. A crash before the first local fsync can lose a yielded event locally. |
| Resume after reconnect | `@spectrum-ts/core/dist/authoring.js:199,272-275,393-398` | `lastCursor` lives in memory. In-process reconnect calls catch-up if the cursor exists. Cursor rejection resets it and logs that an event gap is accepted. New process startup starts live without a persisted cursor. |
| Lower-level event log | `@photon-ai/advanced-imessage/dist/grpc.d.ts:103-112,291-298`; `dist/client-NRHONKWO.js:543-568` | The lower-level API describes `events.catchUp(since)` as replay of durable events after a fully handled sequence, followed by `catchup.complete`. Calling without `since` starts at the beginning of the **retained** log. This is a real reconciliation capability, but neither the installed types nor the published README establish retention duration, a low-water sequence, account-level completeness across outages, or redelivery after local pre-fsync loss. |
| Historical messages | `@photon-ai/advanced-imessage/dist/grpc.d.ts:183-192`; `dist/client-NRHONKWO.js:1220-1250`; `dist/groups-CMgks3Ll.d.ts:548-572` | `messages.listRecent` and `listInChat` provide paged time-filtered history. They can assist a bounded comparison. Their presence alone proves neither an exhaustive interval nor the persistence of deleted/expired messages. The installed high-level sidecar does not call them. |
| High-level catch-up | `@spectrum-ts/imessage/dist/index.js:2417-2462` | The wrapper calls lower-level catch-up only with a valid in-memory cursor; `catchUpEvents` returns for an absent cursor. It filters a global event sequence to message events and converts them into message objects; the installed sidecar normalization does not retain the sequence. |
| Live sidecar | `../index.mjs:642-659,693-720` | The installed loop normalizes and forwards, then marks read. It has no durable first-write or post-crash reconciliation. Its outer resubscription loop cannot reconstruct events missed between process death and new live subscription. |

The [advanced-imessage-ts README](https://github.com/photon-hq/advanced-imessage-ts/blob/main/README.md)
documents catch-up and live event APIs. The
[spectrum-ts README](https://github.com/photon-hq/spectrum-ts)
documents the high-level `app.messages` iterator. The
[spectrum-convex README](https://github.com/photon-hq/spectrum-convex)
and [iMessage Vercel adapter README](https://github.com/photon-hq/vercel-chat-adapter-imessage/blob/main/README.md)
describe webhook delivery/retry in other integration topologies. They do not
establish an acknowledgment contract for this pinned gRPC iterator or prove
that changing topology preserves Task A's single authenticated connection.

## Required local commit and recovery protocol

1. The protected Photon owner receives the **full** lower-level event stream,
   not only high-level `app.messages`. It validates provider/project identity,
   event type, global sequence, original message GUID, sender, conversation,
   timestamp and immutable payload. It records a bounded payload or a reason
   for rejection. The sequence is an observation of provider order, never
   proof of content or authorization by itself.
2. The owner writes an append-only or transactional local record, fsyncs the
   record and parent directory, then durably advances its own contiguous
   high-water cursor. Cursor advancement must happen **after** every event in
   the prefix has a durable decision, including ignored event types. A crash
   before this point leaves the cursor unchanged; replay must deduplicate on
   provider event identity and payload digest. A conflicting replay stops
   intake and alerts an operator.
3. Read receipts, Hermes forwarding and Gateway submission occur only after
   local durable acceptance **and** continuity verification. A read receipt
   cannot serve as a commit marker. If forwarding or processing fails, the
   durable event remains pending with bounded retries and an explicit delayed
   or unavailable state. Gateway receives only a canonical event-bound
   envelope and remains the sole task filer.
4. On startup or reconnect, freeze promotion to Hermes. Read the last durable
   cursor, call lower-level `catchUp(since)`, record every returned event and
   `catchup.complete` head, and join the live stream without an uncovered
   interval. Check the provider's documented overlap/ordering rule and
   deduplicate. A cursor rejection, missing retention coverage, unsupported
   event, failed history pagination, or unexplained sequence discontinuity
   places the affected interval in `uncertain`. **Message-only** sequences
   cannot establish a gap: chat/group/poll events share the global sequence.
5. Compare a bounded `messages.listRecent`/`listInChat` window as supplemental
   evidence if the provider documents its completeness and retention. Persist
   reconciliation interval, source, low/high water, observed GUIDs, conflicts
   and operator decision. Do not infer full recovery from an empty page or a
   `catchup.complete` head alone.
6. A live event may be marked `verified` only after provider continuity for
   its interval is established. `uncertain`, `held`, `rejected`, `delayed` and
   `unavailable` are explicit durable states. Expiry must not silently erase
   unresolved evidence. No real `uncertain` event may be released to Hermes,
   used for `/reply`, or filed through Gateway.

This protocol is **conditional**. The lower-level type comments support a
retained event log, but no verified retention floor, complete replay window,
or atomic catch-up-to-live handoff has been established for the deployed
provider. The installed sidecar holds one Spectrum connection; accessing the
lower-level event stream through that existing authenticated owner, without
opening a second unreviewed Photon connection, needs a supported SDK interface
or a reviewed sidecar integration change. If those properties cannot be
confirmed, an outage or crash before
the first fsync can leave permanently unknowable inbound events. The correct
fail-closed behavior is to stop automatic intake and task filing for the
uncertain interval, preserve observations and diagnostics, and require a
separately approved reconciliation decision. A human decision can authorize a
bounded exception or mark work unresolvable; it cannot retroactively prove
that no message was lost.

## Failure transitions to test

| Failure point | Required post-restart state |
| --- | --- |
| SDK emitted; local first fsync failed | No accepted local event. Resume from previous durable cursor **if provider coverage is verified**; otherwise interval uncertain and filing stopped. |
| Payload record fsynced; cursor not fsynced | Replay same event; deduplicate identical bytes; reject a conflicting event. |
| Cursor committed; Hermes feed failed | Replay local pending event to Hermes under same identity; no provider redelivery assumption. |
| Reconnect with valid cursor | Catch up all event types through a documented complete head, then cover handoff to live; hold intake until verified. |
| Cursor rejected or retained-log floor unknown | Mark interval uncertain, alert, do not reset to live and silently accept a gap. |
| Sequence discontinuity | Inspect full event stream and provider ordering; hold if a gap remains unexplained. |
| Duplicate provider event | Exactly one local accepted identity and no duplicate Gateway filing. |

`tests/test_sidecar_spool.py`, `tests/test_durable.py` and
`tests/test_security_contracts.py` exercise local crash, replay, duplicate,
uncertainty and SDK-source properties with synthetic data. No test here
demonstrates provider retention, a live catch-up-to-subscribe handoff, or an
actual post-crash redelivery. Those require a supported provider contract and
an authorized disposable Photon integration environment.
