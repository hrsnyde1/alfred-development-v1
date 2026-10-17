# Proposed isolated native Photon live test — separate approval required

**Not executed.** This protocol is for a disposable authenticated Photon project/account in a separately authorized isolated Linux environment. It never uses the production owner conversation, credentials, service or Gateway. No real development request is sent.

## Prerequisites and controls

1. Human approval explicitly names the disposable Photon project/account, test sender and recipient identities, test window, environment, operator and evidence retention. Use two test senders so an incorrect principal can be measured. Their accounts must not be the real owner or a Company Mastermind.
2. Isolated host/container with a single test Spectrum/Photon connection, pinned versions, the reviewed provenance patch rebuilt from upstream source, and a private observer inside that one connection. No production token, route or file mount. Ordinary conversation delivery remains enabled for compatibility measurements. Disable every Gateway submission route; no Gateway credential or inbox is present.
3. Preflight records package/source hashes, sidecar and observer hashes, SDK version, test account pseudonyms, wall-clock sync, service status and a rollback image. The observer emits only case ID, pseudonymous sender/account/conversation, direction, event ID equality token, outbound ID equality token, **separate** `replyTargetGuid` and `threadOriginatorGuid` equality tokens, `isForward`, event sequence if available, timestamp and result code. Never log raw credentials, message contents or unredacted identifiers in the review report. Use one case-scoped HMAC key so equality can be verified; keep the key and any necessary raw capture in restricted, short-lived evidence storage.
4. Send only labels such as `LAB NATIVE REPLY TEST A — no task requested`. The test gate may render a preview-style prompt but has no inbox writer. Record actual outbound `messageId`; if it is empty or unknown, stop that case and mark it inconclusive.

## Test matrix

| Case | Exact action | Required observation |
|---|---|---|
| Direct A | Test sender 1 uses native **Reply** on preview A and sends `Yes, go ahead`. | New inbound event, explicit sender/account/DM, `replyTargetGuid == A.id`, no forward flag. Exact preview match is accepted by the *test-only* policy. |
| Unthreaded | Sender 1 sends `Yes, go ahead` as an ordinary new message. | No direct target equal to a live preview. Must be denied even if `threadOriginatorGuid` or Spectrum `targetMessageId` points to A. |
| Concurrent | Send distinct preview A and B before either reply; sender 1 replies to B first, then A. | Two nonempty distinct outbound IDs; each native direct target names its own preview despite order. No latest-preview choice. |
| Delayed | Wait near and beyond configured challenge expiry before replying to A. | Field may still point to A, but expired challenge is denied. Check clock skew. |
| Wrong target | Reply to an unrelated older message or to preview B while presenting draft A. | Direct target names the actual replied-to message; A is denied. |
| Other sender | Test sender 2 replies to A. | Actual sender differs; denied regardless of target. |
| Forward/quote | Sender 1 forwards or quotes the preview text and adds `Yes, go ahead`. | `isForward` and direct target behavior recorded. Any missing/ambiguous provenance is denied. |
| Reconnect | In the disposable environment only, interrupt and restore the test connection, then reply to an old preview and a newly sent preview. | Record any replay, duplicate or changed GUID; old challenge is revoked on uncertainty; new direct reply must target the new actual outbound ID. |
| Unknown send | Inject a local observer failure after a test preview sends but before its ID is committed. | Visible preview remains unarmed; later reply is denied and a new preview is requested. |

For every case, compare the native SDK fields with Spectrum's `content.target.id` and the ordinary sidecar `targetMessageId`. Record whether `replyToGuid` appears in a lower-level diagnostic capture, but do not reinterpret it as authority without provider documentation and separate review. Run the direct/concurrent/reconnect cases from each relevant client device type if the intended V1 use includes them.

## Acceptance and rollback

Acceptance needs reproducible nonempty preview IDs and a direct native `replyTargetGuid` that equals the exact preview ID for fresh, delayed and post-reconnect *new* replies, while unthreaded, wrong-target, cross-sender and forwarded/ambiguous cases fail closed. Normal text send/receive and the intended media/Evidence Bridge regressions must also remain functional. Missing direct targets, aliasing to thread origins, duplicate preview IDs, wrong sender attribution, or an uncontrolled privileged route blocks implementation and triggers architecture review. No finite live run proves zero provider message loss.

At completion, stop only the disposable test service, revoke disposable credentials, remove test data under the approved retention policy and restore the isolated image. Record every inconclusive case and hash the final evidence bundle. No production service rollback is needed because production is never touched.

Even a passing live test grants no Task A implementation, real Gateway filing, task execution, Task B, publication, merge or deployment authority. Those require the separate approvals listed in the feasibility report.
