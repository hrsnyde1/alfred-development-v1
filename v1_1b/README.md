# V1.1b staged Photon → Gateway intake: owner confirmation

Status: staging candidate for focused review. Nothing is installed or authorized for live filing. Pinned sources: Hermes `26610b09a5c4aead8d8dfb276ea33decf0d7fa46`, Gateway `0086db5f2c9a41b66161559a11056e4d14138cf9`. The reviewed V1.1a filer and `dev-001` fixture remain the only filing target.

## Flow and authorization boundary

1. The **existing single** Photon sidecar observes the original SDK message before forwarding the ordinary conversation event to Hermes. The observation carries the SDK sender, inbound direction, DM space, message ID, timestamp and text. The sidecar forwards the native `replyTargetGuid`, `threadOriginatorGuid` and `isForward` as distinct fields from the separately staged Spectrum patch. It never derives direct target provenance from `content.target` or a conversation fallback. Ordinary outbound text and the restricted media spool route remain as staged.
2. Personal Alfred drafts the nine `alfred.devreq/1` fields for an owner natural-language development request. The tool provides draft content and a queued-turn origin claim. The gate checks the original observed request, sender, DM, age, conservative development-request text rule and fixed `dev-001` project. A Hermes UID, event ID and text digest can ask for a **preview only**. They cannot publish an envelope.
3. The protected gate validates and freezes the exact envelope bytes, calculates their SHA-256, and sends a full bounded preview to the original observed DM using `/send` on the existing sidecar. It stores the SDK-returned outbound preview message ID. One confirmation may be pending at a time. A failed or ambiguous preview send retires the request without filing.
4. Only a fresh original SDK **inbound** event with the configured owner sender, same DM, unique message ID, native direct `replyTargetGuid` equal to that preview ID, explicit `nativeIsForward=false`, and exact affirmative text (`Yes, go ahead`, case insensitive) can publish the frozen envelope. The five-minute window is measured from successful preview send. Missing, thread-only, wrong-target, forwarded, expired or conflicting replies cannot file. A gate restart loses the pending preview and fails closed; the owner must resend the development request.
5. The gate publishes the existing envelope with `renameat2(RENAME_NOREPLACE)`, file fsync and directory fsync. Duplicate confirmation/retry cannot create another envelope. Only the trusted Gateway creates the canonical `proposed` task. `development_gateway_status` on the authenticated confirmation or later owner status turn reads the protected Gateway journal and reports the real task ID after `filed`; a pending or uncertain result never invents an ID. Submission is not execution approval.

The preview shows the original utterance and **every** drafted field. The gate stores and publishes the same envelope bytes; a later altered draft is rejected. Long drafts exceeding the bounded preview are refused so the owner is never asked to confirm an incomplete display. This is a confirmation of request submission only.

## Proposed Personal Alfred instruction for later authorization

> When the owner naturally requests a software change for `dev-001`, prepare a faithful draft and call `development_gateway_submit` for that original Photon turn. Tell the owner to reply **directly to the protected preview** with “Yes, go ahead”; do not say a task was filed at the preview stage. On a confirmation turn, call `development_gateway_status`; give a task ID only when it returns `filed` with `task_id`. Continue ordinary conversation otherwise. On expiry, uncertainty or rejection, ask for a fresh owner request. Filing does not approve execution.

This paragraph is staged guidance, not an installed SOUL/profile change. The model is not trusted to establish identity or confirmation; direct Hermes IPC can request a preview but cannot publish.

## Focused activation dependencies

- The corrected native Spectrum provenance patch at `../patches/spectrum-native-reply-provenance.proposed.patch` must be reviewed and applied as part of a separately authorized controlled migration of the **existing** sidecar. It is absent from the installed SDK. Live provider behavior must establish that a direct reply exposes `nativeReplyTargetGuid` equal to `/send`'s outbound `messageId`, while unthreaded/thread-fallback replies do not, and that ordinary replies expose explicit `nativeIsForward=false`. Synthetic tests and a patched-module import do not establish this. Until verified, confirmations fail closed.
- The sidecar, Hermes and gate require distinct unprivileged UIDs. Verify `SO_PEERCRED` and socket permissions, the gate-owned `0600` config (including the fixed sidecar port and token), protected owner SDK sender ID, no Hermes read of the gate config, fixed Gateway journal read and inbox write permissions, and original DM routing. The sidecar and gate must share the existing sidecar token; Hermes already uses that token for ordinary `/send`. The gate chooses destination only from its protected SDK observation. The separate control token and Photon credentials stay outside Hermes.
- Preserve the restricted `/send-media` spool for ordinary photos, voice and documents and protect `/send-attachment` and `/shutdown` with the separate control token. Validate ordinary text/media on the host after the controlled single-connection migration. No second Photon runtime is proposed.
- Accepted ADR 0003 still requires owner approval before Phase 4; accepted ADR 0009 currently grants Hermes inbox read-write and needs an explicit amendment granting the protected gate the sole write path. Separately accept the reviewed V1.1a allocator and ADR 0011 task-ID safety gate before live Gateway pickup. Approve `dev-001` registry binding, plugin registration/default profile allowlist, protected identities and sidecar migration before activation. None of these are authorized by this staging work.
- The SDK does not establish guaranteed redelivery. A lost confirmation, gate restart or ambiguous preview send requires a fresh owner request. Gateway journal reconciliation is required before retrying a filing whose result is uncertain. No catch-up service is introduced for V1.

## Verification

Run each Python suite in a separate process so its staged Gateway modules load before the installed modules:

```sh
PYTHONPATH=/home/alfred/alfred-development-lab/milestone2/task-a/v1_1a/staging/.dev/bin:/home/alfred/Git/alfred/src PYTHONDONTWRITEBYTECODE=1 /home/alfred/Git/alfred/.venv/bin/python -m pytest -q -p no:cacheprovider v1_1a/tests
PYTHONPATH=/home/alfred/alfred-development-lab/milestone2/task-a/v1_1a/staging/.dev/bin:/home/alfred/Git/alfred/src PYTHONDONTWRITEBYTECODE=1 /home/alfred/Git/alfred/.venv/bin/python -m pytest -q -p no:cacheprovider v1_1b/tests
PYTHONDONTWRITEBYTECODE=1 /home/alfred/Git/alfred/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_native_reply_target_feasibility.py
PYTHONPATH=/home/alfred/.hermes/hermes-agent PYTHONDONTWRITEBYTECODE=1 /home/alfred/.hermes/installs/e1541360de565941/test-environment/gen-37875a1c5e2d469c97046e738e30cd30/venv/bin/python -m pytest -q -p no:cacheprovider v1_1b/tests_hermes
/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node --check v1_1b/staging/sidecar/index.mjs
/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node --test v1_1b/tests/development-observe.test.mjs v1_1b/tests/restricted-media.test.mjs
```

The `v1_1b/tests/test_patch.py` case dry-runs and byte-checks the proposed Hermes patch against a disposable copy. The native feasibility suite does the same for Spectrum, including full-module parse and import. Unix socket bind/peer checks are skipped under this sandbox's EPERM and remain a host acceptance check. No Photon connection, production filing or live attachment test was run.

Latest results: V1.1a and V1.1b together 55 passed and one Unix socket identity test skipped; separately V1.1a 15 passed and V1.1b 40 passed/one skipped; native provenance feasibility 20 passed; staged Hermes adapter 5 passed; two Node test files passed; full staged sidecar syntax parse passed. Running **all three** Python source suites in one pytest process produced 11 V1.1a failures because the installed Gateway modules entered Python's module cache before the staged copies. The supported V1.1a/V1.1b combined run and isolated native run passed; the all-three collection is a test-harness limitation, not evidence of an installed Gateway change. No installed Hermes, Spectrum or Gateway file changed.
