# Task A Photon split — staging design and trust boundary

This is an inactive candidate. The installed Hermes and Photon code has not changed.
The proposed upstream diff is `patches/photon-secure-front.proposed.patch`, pinned to
the installed sidecar and adapter SHA-256 values recorded in `make_photon_patch.py`.

## v0.1.4 corrective staging status

The installed Spectrum high-level stream has an in-memory cursor and may
explicitly accept a gap after cursor rejection. A later source investigation
found lower-level Photon catch-up and paged history APIs, but provider
retention and complete replay after process death remain unverified. The
protected journal therefore labels real observations
`unverified` and holds them out of the Hermes feed, `/reply`, and `/submit`.
The sidecar receives a durable `held` decision and does not mark such messages
read. The immutable event identity and text remain in the protected journal
past the ordinary five-minute handle lifetime for operator reconciliation.
There is currently no approved way to promote a real event to reconciled: a
provider-backed continuity proof or separately approved human procedure is
required. Events lost before the first sidecar spool fsync cannot be detected
or reconstructed from this code alone.

The proposed adapter now rebinds the exact raw event on every processing job,
including an installed Gateway drain task. It rejects a merged event whose
processed text no longer equals its original SDK text. This prevents an
honest queued job from inheriting the earlier job's handle, but the installed
Gateway merges rapid same-chat text into one pending turn and can cancel or
discard a pending event. Further, Hermes can present any handle it has seen;
the protected boundary cannot independently prove which model turn produced
the text. Full exact event-to-turn authorization remains unresolved.

The inbox commit order is: fsync private prepared ledger record and ledger
directory; write and fsync an inbox temporary file; Linux `renameat2` with
`RENAME_NOREPLACE`; `syncfs` on the same filesystem; fsync the private `sent`
ledger record and directory. An existing final name on retry is reopened
without following symlinks, checked byte-for-byte, fsynced, and followed by
`syncfs` before `sent`. A crash before rename can leave an orphan temporary
file in the create-only inbox; Gateway-side or operator cleanup is needed
because granting the broker list access would weaken confidentiality. Actual
cross-UID ACL and filesystem crash semantics still require isolated Linux
testing.

This work is incomplete and has no v0.1.4 archive. See
`V014_CORRECTIVE_STATUS.md` for the finding matrix and blockers.

## v0.1.3 service and delivery correction (historical candidate)

`task_a/service.py` is the complete proposed protected entry point. Its
systemd service receives five credentials through `LoadCredential`, accepts
one systemd-owned restricted listener, and supervises one Node sidecar on
the private socket. `/var/lib/alfred-photon-intake` is owner-only `0700`;
`/run/alfred-photon-intake` is broker-owned `0751`; the restricted socket is
`0660` with group `alfredhermes`, while `private.sock` is `0600`. The broker
does not join the Hermes group. Service and socket units are review templates,
and none has been installed.

The sidecar now fsyncs a bounded spool record before delivering an inbound
event. The front fsyncs its journal before `/ack accepted`; only then does
the sidecar attempt a live SDK read receipt. Rejections get explicit ack
without a read receipt. Failed admission remains spooled and is retried.
Broker restart reloads the same handle. A response reserves that handle on
disk before sending, and uncertain send results remain non-retryable to avoid
duplicates. Hermes may receive a bounded replay of an unanswered event.
After three in-process forwards, the event stays on disk and emits a delayed
audit code; restart requeues it.

The adapter stores the handle in an async task context created for the exact
event. Overlapping turns in one chat do not share a mutable latest-handle
slot. In Task A mode the legacy message-ID dedup cache does not swallow a
journal replay. The front derives the outbound destination from the journal,
checks the Hermes peer UID, and accepts only bounded text. The broker opens
the lab inbox with `O_PATH`, published using a no-clobber hard link and
`syncfs`, then records a durable ledger state. The setgid inbox grants the
Gateway group read on new `0640` files without directory read for the broker.

See `THREAT_MODEL.md` and `INDEPENDENT_REVIEW_RESPONSE.md` for residual risks
and measurements still required. In particular, real Photon SDK redelivery
before the first spool fsync is not verified by synthetic tests.

## One Photon connection, two interfaces

1. The patched Node sidecar remains the **only** Spectrum SDK client and retains
   the single `await Spectrum(...)` connection. It runs as `alfredphoton`, reads
   Photon project credentials and the private control token, and binds only a
   `0600` Unix socket under `/run/alfred-photon-intake/`. The existing arbitrary
   filesystem-path `/send-attachment` route is removed from this candidate.
2. The protected Python front reads `/inbound` from that private socket. It
   checks the kernel peer UID before reading, validates explicit SDK-derived
   `sender.id`, DM/text/platform/time fields, rejects duplicate event identity,
   and issues a random opaque handle. It forwards a bounded normalized event
   over a separate Hermes socket. The protected front owns the authenticated
   event record and original provenance; Hermes receives a derived copy.
3. Hermes' patched adapter uses `PHOTON_TASK_A_BROKER_SOCKET` and no Photon
   credentials or sidecar bearer token. Its restricted socket supports only
   `GET /inbound`, `POST /healthz`, `POST /reply`, and `POST /submit`.
   `/reply` accepts exactly `handle` and `text` (at most 4,000 characters),
   reserves the handle for at most one send within five minutes, and derives the destination from
   the admitted event. It accepts no destination, path, URL, media bytes,
   shutdown command, or token from Hermes. The adapter's media helpers fail
   closed in Task A mode. Rich links, polls, reactions and typing are not
   separately exposed; text fallback is the only intended outbound channel.
4. `/submit` accepts exactly a handle and a canonical `alfred.devreq/1`
   envelope string. The protected front checks the Hermes kernel peer UID and
   binds `origin`, `utterance` and `project_hint=dev-001` to the admitted event.
   `LabInboxTransport` writes only the statically configured disposable lab
   inbox. The Gateway remains the sole authority for registry resolution and
   filing a canonical `proposed` task; no approval or execution is conveyed.

The private sidecar still has privileged endpoints other than attachments for
its own supervisor. The Python front calls only its private `/inbound` and
`/send` operations. Hermes has neither the private socket path permission nor
the token in the candidate topology. OS ownership, ACLs, peer checks and
process isolation need independent measurement on a disposable host.

## Event and reply behavior

- Original `sender.id` must match one explicit allowed principal; phone or
  space fallback is never an intake identity. Group, forwarded, quoted,
  non-text, stale, future and duplicate events are refused.
- Handles are random, bounded to 1,024 outstanding events, and pruned after
  the five-minute admission window. A reply consumes its handle before the
  private send, so an uncertain private send cannot be retried as a duplicate.
- The restricted wire schema has no generic proxy. Unknown routes return 404;
  extra fields on `/reply` and `/submit` return 400. A `SO_PEERCRED` UID check
  is required before any restricted request is handled.
- The staging runner is constrained to a marked temporary root. It can read
  only owner-owned mode-0600 token and ledger-key files inside that root.
  It accepts one socket-manager-provided Hermes listener descriptor, allowing
  the socket manager to set the Hermes group without adding that group to the
  broker process. It does not install identities or units and does not launch
  the sidecar.

## What the tests establish

Synthetic SDK event fixtures exercise sender and origin binding, replay,
destination binding, route denial, exact envelope bytes and lab-only inbox
behavior. Static patch tests prove the proposed source diff reproduces from
the pinned bytes and parses. They do **not** authenticate to Photon, measure
Unix socket DAC across UIDs, prove real sidecar startup, or prove live Hermes
message compatibility. This sandbox refused Unix socket bind/send, so those
integration probes were skipped and remain independent acceptance gates.
