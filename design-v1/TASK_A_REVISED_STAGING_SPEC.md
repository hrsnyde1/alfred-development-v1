# Proposed revised Task A — natural-language Photon intake boundary

**Draft, unallocated, not `ready`; high-risk protected-path work.** This is a
replacement *candidate* for the older
`milestone2/proposals/TASK_A_LINUX_ISOLATION_AND_TRANSPORT.md`; that file is
left intact as historical staging evidence. Human approval of the revised
ADRs, a canonical task ID, exact protected diffs, a ready spec and separate
operator authorization are prerequisites to implementation or migration.

## Objective

Prove a whole-process Linux boundary and the smallest protected observation,
draft-preview, natural-language confirmation and durable lab inbox path that
keeps the installed single Photon connection and ordinary Hermes messaging
working. The protected gate must independently validate both the original
owner request and the fresh threaded owner confirmation. It must never treat
Hermes' sender field, model text, event handle or IPC possession as that proof.

## In scope after separate authorization

1. Inventory and pin installed Hermes adapter, sidecar, Spectrum/Photon SDK,
   service, credential, Evidence Bridge and Gateway contracts. Measure actual
   process identity, groups, mounts, sockets, file permissions and subprocess
   inheritance. Produce an exact path/owner/ACL and route matrix.
2. Stage a protected SDK event observation at the **existing** Photon
   connection. Preserve ordinary conversation delivery. Record bounded
   original native event identity/text before Hermes receives a derived copy;
   reject missing explicit sender, bot/internal/delegated/forwarded or quoted
   initiators, group/other-account/cross-company events and mutable text
   conflicts. Expose the raw direct `replyTargetGuid` and its provenance;
   the installed high-level `targetMessageId` can reflect a fallback and is
   insufficient on its own. No second Photon login or blanket messaging
   replacement.
3. Define a narrow untrusted Hermes draft-proposal interface. Accept only
   references to a protected original event and bounded draft fields. Bind
   the exact owner utterance and static lab scope in the protected ledger;
   validate the existing `alfred.devreq/1` schema and show every material
   field in a canonical preview. Model-supplied identity, destination,
   request ID, status, approval, repository path and workflow fields are
   ignored or denied, never authority.
4. Send preview using protected Photon control, persist the returned outbound
   message ID, draft digest/version, sender and conversation. Accept a fresh
  affirmative **only** from a direct native SDK `replyTargetGuid` to that exact preview,
   by the same authenticated owner in the same conversation before expiry.
   Deny generic unthreaded yes, wrong target, overlapping ambiguous previews,
   changed scope, duplicate, replay, delay after expiry, cancellation and
   uncertain send result. A revised draft gets a new challenge.
5. Durably assign one UUID and immutable revision-1 envelope only after
   confirmation. Publish atomically to the existing *lab* bound Hermes inbox
   through create-only access; fsync payload and ledger, reconcile crash
   points and Gateway duplicate outcomes. A locally submitted receipt cannot
   be called Gateway `filed`. Lab `run-once` tests may use only disposable
   registry/repository/home fixtures and require explicit test authorization.
6. Preserve a reviewed ordinary messaging compatibility route while removing
   Hermes access to the private control token, credentials, shutdown, private
   event feed and arbitrary-path protected-side attachments. Unsupported
   attachment/media behavior must be documented and accepted separately,
   without granting broad path access. Prove the old/new service cannot run
   concurrently and that a rollback restores the original working service.
7. Specify and test detected-uncertainty handling: stream interruption,
   restart, cursor rejection, pre-commit failure, unknown preview send,
   missing native reply target, inbox retry and Gateway status inconsistency.
   Request a fresh authenticated resend or new confirmation; never silently
   promote an uncertain event. No V1 perfect replay or full-history service.

## Outside Task A

No real Development Gateway filing, real registry entry, authoritative task
creation, Kanban intake, CTO scheduler, Task B plugin/status service,
approval, execution, specialist delegation, GitHub action, merge, deployment
or production identity/service operation under this draft. Task A tests may
exercise an isolated `alfred`/`dev-001` fixture only. The previous broad
all-chat reply-handle binding and Photon catch-up work is not a V1 intake
prerequisite; its historical security findings remain relevant to any
privileged route that survives the redesign.

## Candidate protected diffs for later exact review

- Hermes Photon sidecar event normalization/SDK observation and adapter
  compatibility configuration under
  `/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/` **only if**
  needed; never edit installed source in staging. Any Gateway queue/result
  change requires a separately justified amendment, not blanket permission.
- Root-owned protected intake gate, ledger, socket and credential/service
  templates under candidate `/opt/alfred-photon-intake`,
  `/var/lib/alfred-photon-intake`, `/run/alfred-photon-intake` and
  `/etc/systemd/system/`; dedicated Hermes runtime/state and lab Gateway
  controlled copy as detailed in `TOPOLOGY_AND_BOUNDARIES.md`.
- Disposable lab inbox, protected fixture registry and `dev-001` repository;
  no diff to real Gateway source, live registry, journal, approvals, PAUSE/STOP,
  real `.dev/tasks`, Evidence Bridge source or publisher.

The human-reviewed Task A spec must replace these candidates with exact
versions, hashes, owner/mode/ACL entries, install/rollback commands and
service identities. Current UID-1000 Hermes/local-backend deployment is not
accepted as a safe protected event owner. The previous proposed UIDs 31011,
31012 and 31014 remain **candidate values**, never an allocation.

## Acceptance gates

- Synthetic concurrency and negative tests: two overlapping same-chat
  requests, queued/delayed drafts, wrong native reply target, bare “yes”,
  forged owner/sender, Company Mastermind, reused preview, revised scope,
  wrong company, expiry, conflict, crash before/after each commit, duplicate
  request ID, unreadable inbox, status contradiction, challenge flooding and
  resource bounds.
- An authorized disposable Photon account confirms the *native* reply target
  and outbound preview ID are reliable with this deployed SDK and one
  connection, including delay/reconnect. If not, block the natural-language
  confirmation design rather than falling back to chat/session/latest handle.
- Independently measured OS tests show the entire Hermes process tree cannot
  read/forge protected Photon events or reach Gateway authority and that
  broker/Gateway permissions preserve inbox confidentiality and durability.
  Test privileged route denial, sidecar lifecycle, service recovery, media
  compatibility and both Evidence Bridge tools through Photon.
- Gateway lab tests preserve `alfred.devreq/1`, static requester binding,
  protected registry resolution, one canonical `proposed` spec and no
  execution. The **real** `gateway.py run-once` remains blocked until the
  task-ID allocation safety issue recorded in proposed ADR 0011 is resolved.
- An independent reviewer accepts the source, provider behavior, OS boundary,
  crash recovery and rollback evidence in writing. Passing unit tests alone
  do not grant Task B or deployment authority.

No release artifact is requested by this design revision. Historical
v0.1.2/v0.1.3 archives and review findings remain unchanged.
