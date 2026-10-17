# Proposed ADR 0003 amendment — natural-language Photon Gateway Front

**Status: proposed for human architecture review; inactive.** This replaces
the earlier staging `milestone2/proposals/ADR-0003-photon-gateway-front-amendment.md`
as the *candidate text for review*, without modifying that historical file or
the accepted ADR. It grants no implementation, Gateway filing, CTO run,
approval, execution or publication authority.

## Proposed decision

Activate a narrowly scoped Phase 4 requester design for authenticated direct
owner Photon conversations. The existing Photon connection and ordinary
messaging adapter remain in use. A protected event owner observes native SDK
inbound events before they enter Hermes. Personal Alfred may classify and
draft a development request from a protected reference to an original owner
event. Its proposal is untrusted. The protected gate, and not Hermes, validates
the original event and a **separate fresh owner confirmation** of the exact
canonical draft before writing the existing bound requester inbox.

No mandatory command or special syntax is part of the owner experience. A
generic unthreaded “yes” is insufficient. The protected gate records the
outbound message ID of its complete draft preview and accepts a fresh
affirmative only when the native SDK reply target names that exact preview,
the explicit sender and conversation match the original owner request, the
draft version/digest is unchanged and the challenge is live and unused. If
the provider cannot reliably expose that reply target, the path remains
disabled pending a further architecture decision. The detailed state and
failure contract is `NATURAL_LANGUAGE_INTAKE_ARCHITECTURE.md`.

The gate generates and durably stores a UUID `request_id` and immutable
`alfred.devreq/1` envelope. Duplicate delivery and publication retries reuse
the exact UUID/bytes; a conflicting replay fails closed. The envelope's
`origin`, text and project hint are untrusted to the Gateway. The only intake
folder remains the static Hermes requester binding in
`alfred.gateway.requesters.BINDINGS`. The trusted Gateway alone parses the
existing schema, resolves the protected registry, checks requester permission
and files a canonical `proposed` task. A broker receipt is `submitted`, never
`filed`. The Gateway's journal and spec are authoritative; an outbox event is
only a display projection.

This amendment chooses **detected-uncertainty resubmission**, not a perfect
Photon delivery guarantee. When a disconnect, crash window, cursor rejection,
missing target ID or uncertain publication is detected, the gate holds the
affected request and asks the owner for a fresh authenticated resend or new
preview confirmation. Silent provider loss may not be detectable. No V1
full-history replay or catch-up service is required. Read receipts are not
used as delivery acknowledgments.

One human confirmation authorizes **submission only**. It does not mark a
Gateway task `ready`, approve a spec hash, grant protected execution, permit
specialist work, publish to GitHub, merge or deploy. ADRs 0002, 0004, 0006,
0008 and 0009 keep their existing gates, including PAUSE/STOP, one-time
approval, revocation, protected-path restrictions and human merge. The future
CTO planning scheduler is a separate proposal in `CTO_PLANNING_HANDOFF.md`;
it may react only to a trusted Gateway `filed` record and has no execution
authority. It is not activated by this amendment.

## Preconditions before real filing

1. Separately approve an ADR 0009 Linux exception and a whole-process boundary
   that denies Hermes and all model/tool children protected Gateway state,
   credentials, inbox bypass and Photon event-forgery routes. A Docker terminal
   backend alone does not isolate in-process plugins.
2. Separately authorize a revised high-risk Task A with exact protected path
   diffs. Independently prove the protected Photon event/control split,
   original owner sender check, native reply-target binding, service identity,
   normal-messaging compatibility, Evidence Bridge preservation and rollback.
3. Resolve the task-ID allocation safety gate recorded in proposed ADR 0011
   before any real `gateway.py run-once` or automatic filing. The proposed ADR
   is not itself authoritative; its safety finding must be resolved and
   recorded in an approved work item.
4. Separately authorize Task B/Gateway intake integration and any later CTO
   scheduler. No real company registry mapping, execution, status endpoint or
   GitHub credential is implied by this design.

## Superseded candidate scope

The earlier command-based Option B proposal required `/dev` syntax; this one
uses natural-language conversation and an authenticated threaded confirmation.
Earlier broad protected-broker staging proposed all-chat event handles,
handle-bound text reply delivery and comprehensive Photon replay. Those are
not prerequisites for this narrow V1 submission path, because Hermes cannot
submit by handle and detected delivery uncertainty fails closed. Prior
security findings concerning privileged sidecar routes, same-UID isolation,
Gateway inbox durability and compatibility remain requirements wherever this
design uses those boundaries. The immutable v0.1.2/v0.1.3 archives and
independent review results are not revised.
