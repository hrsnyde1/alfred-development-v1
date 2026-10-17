# Revised Option B Linux topology and trust boundaries

**Proposal only.** This supersedes the broad-broker topology assumptions in
`milestone2/proposals/LINUX_TOPOLOGY_AND_LAB_FIXTURE.md` for future review;
that historical proposal and all systemd/permission templates remain
unchanged. IDs and paths below are candidates, not installed facts.

| Zone | Candidate identity and allowed access | Prohibited access |
| --- | --- | --- |
| Hermes, Personal Alfred, all plugins/tools/children | Dedicated `alfredhermes` UID 31012 under a root-managed whole-service sandbox; own isolated state and a reviewed ordinary messaging socket only; existing Evidence Bridge read group as needed. | Photon credentials, private SDK event store, protected intake ledger/token, direct Gateway inbox, real/lab Gateway code/state, operator home, sudo/LXD/Docker, unconfined child/user services. |
| Protected Photon owner and intake gate | Dedicated `alfredphoton` UID 31011; **one** existing Spectrum connection; native SDK event observation; private challenge send, ledger/audit and create-only lab inbox publication. | Real Gateway journal/registry/specs, approval/publisher credentials, arbitrary paths supplied by Hermes. |
| Lab Gateway | Dedicated `alfreddevlab` UID 31014; protected reviewed source copy and one-project `alfred`/`dev-001` fixture; manual lab `run-once` only after specific authorization. | Real Gateway, Photon credentials, Git remote, publisher and execution credentials. |
| Real Gateway and operator | Existing protected authority remains where it is. | No Task A migration or real filing by implication. |

Keep the old UID-1000 Hermes service inactive only during a separately
approved migration; never run old and new services concurrently. Preserve
original state and Evidence Bridge v0.2.1 as rollback evidence. Whole-process
denials must be measured with the actual UID, groups, mount namespace, socket
permissions, inherited descriptors, subprocesses and IPC. A Docker terminal
setting alone cannot confine an in-process Hermes plugin. No candidate unit
is installed by this design.

## Minimal interfaces

1. **Private SDK observation:** inside the protected Photon owner, record the
   exact native inbound event, explicit sender, conversation, direction,
   message ID and reply target before passing a derived message through the
   existing Hermes conversation feed. Hermes may propose a draft referencing
   an existing protected event. It cannot create that observation.
2. **Untrusted draft proposal:** a narrow Hermes-to-gate method accepts only
   a bounded event reference and draft data. It returns a non-authoritative
   staged/denied state. It never accepts sender IDs, event payload replacements,
   arbitrary filesystem paths, credentials, destination, `request_id`, Gateway
   status, approval or execution fields as authority. It cannot publish to
   the Gateway inbox.
3. **Protected challenge and confirmation:** the gate sends the canonical
   preview through its own private SDK control path and records the returned
   outbound message ID. Only a later owner SDK event with that native reply
   target can confirm. The model cannot invoke a `/confirm` route.
4. **Ordinary messaging compatibility:** Hermes keeps its existing conversation
   behavior through a restricted compatibility channel, without the private
   control token. Each sidecar route is inventoried. Shutdown stays with the
   supervisor; arbitrary-path `/send-attachment` is disabled or redesigned
   with an isolated, bounded media staging root and no protected-side file
   reads. Any unsupported feature is a compatibility blocker for migration,
   not a reason to grant Hermes the private token. No second Photon client is
   introduced to avoid changing connection semantics.
5. **Gateway transport:** only the protected gate publishes exact
   `alfred.devreq/1` bytes to the static bound Hermes inbox. The broker gets
   create-only/search access where technically enforceable; Gateway can read
   and consume. The gate has no read/write access to the Gateway registry,
   journal, specs, approval state or publisher. Publication uses a prepared
   private ledger, file and directory durability, no-follow/no-clobber
   operations and same-UUID crash reconciliation. The protected Gateway is the
   sole filer.

## Technical blocker and acceptance measurements

The installed SDK types include `replyTargetGuid` and
`threadOriginatorGuid`, and the current sidecar emits `targetMessageId`, but
there is no measured guarantee that the deployed Photon account returns an
unambiguous native `replyTargetGuid` for every ordinary threaded reply. The
protected owner must distinguish that direct field from
`threadOriginatorGuid`, a Spectrum fallback, Hermes' sent-message cache or
textual quote. If native target, outbound challenge message ID, account or
conversation cannot be verified, “Yes, go ahead” must remain non-authorizing.
The currently normalized high-level event loses the distinction between the
two provider target fields, so exposing raw direct-target provenance through
the existing connection is a required upstream interface change.
No same-chat, one-pending, latest-handle or model-confidence fallback is
allowed. This may require a deeper SDK/sidecar interface change; Task A must
stop and return an architecture decision if it cannot be implemented with the
single connection and preserved messaging experience.

Before accepting the topology, independently test at the OS level: denial of
Hermes access to the Photon token/ledger and all real/lab Gateway authority;
denial of broker access to Gateway journal/specs and unrelated inbox files;
socket peer checks, symlink/hardlink/race defenses, orphan recovery,
credential handoff, systemd lifecycle and rollback; normal Photon text/media
regressions; both Evidence Bridge tools; overlapping same-chat requests and
threaded confirmation against a disposable authenticated Photon account.
Synthetic tests alone cannot establish the provider reply-target behavior or
whole-process confinement.
