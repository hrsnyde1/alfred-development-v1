# Alfred Development V1 completion notification integration

Staging implementation is complete. Sending remains disabled by default and no
real message was sent. The existing Publisher, Developer, QA, Reviewer, Gateway,
Photon, protected records, and services were not modified or restarted.

## Transfer inspection and compatibility

Inspected archive:
`/home/alfred/alfred-incoming/mac-development-v1/alfred-development-v1-mac-20261015-111544.tar.gz`

Recomputed SHA-256:
`bffb2993acb7e4ca6a53367897c8bd667fd73c32f6391ee2c0bb0e403301bc13`

Verified the exact 24-member inventory (23 hashed payloads plus the internal
manifest), every payload size/hash, duplicate absence, and regular relative
paths. The transferred archive remains unchanged. Raw inspection files are
outside the product tree under
`/tmp/alfred-development-v1-mac-inspection-20261016-0835`.
Only the delivery implementation and its relevant tests were ported, with
explicit Linux adaptation. The archive's historical tests and partial full
suite results are not Linux certification: its recorded relevant run passed
791 tests, while its sandboxed full run had teardown errors and its unsandboxed
full run was time bounded and incomplete.

| Transferred component | Linux integration |
| --- | --- |
| `completion.py`: Mac `PublishOutcome` and Gateway GitHub port | Replace with actual Linux `alfred.draft-pr-result/1`, pinned exact plan and separate publication authorization |
| Open-draft-only readback | Reconcile current GitHub open draft, ready, closed, or merged state while retaining historical draft creation |
| In-memory preparation suppression | Preview consumes no key; the persistent delivery guard controls attempts |
| `delivery.py`: private directory, strict bounded state, flock, fsync/replace, uncertain-before-send | Preserve; change import namespace and add an optional Photon send receipt ID |
| Boolean mocked delivery seam | Existing Photon `/send` message ID is retained as send acceptance; original literal True mocks and old records remain compatible |
| Missing production sender | On-demand local HTTP adapter to the existing sole Photon sidecar, using the existing private Intake configuration |

No Mac Gateway implementation or fake publisher port was copied. The bundled
result schema is byte-identical to the Linux Publisher schema. The installed
Publisher V1.1 worker hash was checked as
`051ed86f1fe07260fd663636b665bbef5ddab6c2b8852ecc0a777264ee944ec3`,
and its manifest hash as
`926c925fedcaad40ef9240c2558ff9d10f241329f290a99e212a449f1c66442e`.

## Required integration contract

1. The existing on-demand completion caller invokes this entrypoint after
   Publisher's `next_stage=alfred_completion_notification`. It must supply the
   protected handoff described below; arbitrary result dictionaries or outbox
   events are not accepted by the installed CLI. No new background watcher,
   service, Gateway event, or automatic Publisher retry is introduced.
2. A root-owned directory and configuration pin the successful Publisher
   result bytes, exact plan bytes, and existing separate owner authorization
   bytes. Every component is opened without symlink traversal; writable paths,
   duplicate JSON keys, oversized inputs, and hash mismatches block processing.
   The result must satisfy the real Linux schema, `PUBLISHED_DRAFT`, null detail,
   the completion next stage, exact identity/revision/plan, and matching QA and
   Reviewer digests. A development grant cannot replace publication authority.
3. Bind the task to the approved destination/base/branch/revision and the exact
   plan SHA-256
   `511fa533fd9dc5bb41d51bff1baa21b28a54b8b0b670e5b3f0f602a78d38b903`.
   Use the already verified installed Publisher and existing authorization as
   the source of this read-only handoff. The notifier does not rerun Git,
   regenerate plans, expire historical approval evidence, or issue grants.
4. A read-only `gh api --hostname github.com --method GET` of the exact PR
   verifies its URL, repository, head branch/revision and base branch/repository.
   Main's current SHA may have advanced after the authorized merge; it is not
   incorrectly compared with the historical publication baseline. Unavailable
   or inconsistent readback blocks notification rather than guessing status.
5. Keep one fixed trusted native owner DM, recovered from the matching genuine
   publication challenge/decision, and check its owner against the existing
   Intake configuration. The owner route is never supplied by notification
   content or a requester. The merge-authorization attestation is explicit;
   GitHub's `merged_by` field by itself does not prove a manual authorized action.
6. Run as existing Intake identity `alfred`. Reuse its existing private
   `v1-1-intake.json` only for the owner and Photon send credentials. The adapter
   uses the existing loopback port, `/send`, `x-hermes-sidecar-token`, and
   `{spaceId,text,format:"text"}` body. It starts no SDK stream and no listener.
   A 200 response with literal `ok:true` and a valid nonempty `messageId` confirms
   SDK send acceptance; it does not prove delivery or owner reading.
7. Keep the private 0700 delivery directory and its state/lock across restarts
   and releases. Initialize once only when no notification has previously been
   attempted. Preserve the 1 MiB bound, fsync and file checks. Timeouts, missing
   receipts, callback failures, crashes and confirmation-write failures retain
   `uncertain` and prohibit automatic resend. There is no reset or pruning API.
   Changed wording for an existing publication also fails closed.
8. Honor existing Gateway PAUSE before preparing and immediately before sending.
   Installation leaves `enabled:false`; `preview` never sends or records an
   attempt. A real `notify` invocation and enabling require separate authority.

## Current T-0002 reconciliation and proposed text

Read-only GitHub reconciliation on 2026-10-16 showed PR #1 closed and merged,
`draft:false`, exact approved head revision, and `merged_by:hrsnyde1` at
`2026-10-16T08:19:24Z`. Merge commit:
`596d91daf3311ad3aa0ee42e7220f699f58daf59`.
The sanitized response is in `evidence/pr-1-readback.json`. The owner explicitly
identified this as a separate authorized owner merge. No deployment evidence
was obtained. The archive's old "draft awaits review" text would be stale.

After the protected Publisher handoff passes validation, the proposed text is:

```text
dev-v1-accept · T-0002
Alfred successfully created Draft PR #1.
You subsequently merged it as hrsnyde1 in a separate authorized owner action.
https://github.com/hrsnyde1/alfred-dev-v1-acceptance/pull/1
Deployment has not been verified.
```

This is proposed wording, not a delivery receipt. The runtime rereads GitHub
before any future notification and does not trust this inspection snapshot.

## Local validation and installation

```sh
/home/alfred/Git/alfred/.venv/bin/python -m pytest -q tests/test_completion_integration.py tests/test_completion_delivery.py tests/test_draft_pr_publisher.py
```

**91 passed**: 40 Linux integration cases, 26 transferred durable-delivery
regressions, and 25 Publisher V1.1 regressions. Photon delivery and Publisher
results are mocks; all writes and Git pushes in tests use disposable local
fixtures. Coverage includes rejected success inputs, current merged wording,
owner-attestation boundaries, exact read-only GitHub calls, fixed Photon routing,
missing acknowledgement, PAUSE, disabled operation, restarts, changed text,
corrupt/missing/unsafe state, competing trackers and an actual child-process
exit after mock sending. Ruff check and formatting pass for the six source/test
Python files. Tested interpreter: existing Linux host Python 3.14.7 with
Pydantic 2.13.5. A separate Python 3.12 dependency environment was not installed.

[HOST_INSTALL.md](HOST_INSTALL.md) contains the exact pinned installation,
disabled handoff, one-time state initialization, read-only preview, and rollback
procedure. The runtime manifest has six explicit files. Its SHA-256 is
`e315211f3c8e13d05e81598d77d9e64c0d92d3690cf186d9826968913eacde82`.

Remaining host prerequisite: an administrator must read and pin the protected
successful result and authorization and prepare the genuine owner route.
Read-only inspection of those protected hashes was attempted but sudo required
a password; no hashes or owner event identifiers were invented. No protected
handoff, delivery state, authorization, or production installation was created
by this work. Installation and any real iMessage remain separate operator actions.
