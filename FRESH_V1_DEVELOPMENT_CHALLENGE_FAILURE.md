# T-0003 development challenge investigation

## Finding and limit

**BLOCKED for retry/recovery. The historical transport exception is not recoverable
from the inspected evidence.** The confirmed code defect is diagnostic loss:
Intake collapses errors from Gateway input loading, exact canonical binding and
the issuer into `development_request_unavailable`, without recording the cause.
No evidence-backed functional transport correction can yet be selected.

This is different from the earlier planning EACCES incident. That incident had
a proven barrier before any send. This challenge attempt may have reached send.
An approximately two-second delay suggests a timeout but does **not** establish
one. Do not change the timeout, acknowledge a null receipt, or retry on that basis.

## Installed trace and read-only results

1. Fresh `Host.development_challenge` creates its exact task worktree directory,
   then sends the root-only `stage_development_approval` socket operation. The
   observed refusal means it passed the earlier `wrong_peer` and request-type
   checks; this code is raised only inside the subsequent validation/issuer catch.
2. Intake calls `read_gateway_inputs`, which resolves the active authorized
   project from the registry, requires one canonical task and one matching
   trusted Gateway filing, and validates the CTO plan schema. A pure invocation
   of the **installed** loader on T-0003 passed. No issuer was instantiated.
3. Intake calls pure `approval_request`, recomputing spec, plan, repository,
   worktree, scope and specialist bindings. That installed function passed using
   the actual frozen context. It selects the backend specialist.
4. The actual challenge text is 1,226 characters (limit 4,000); plan is 2,875
   bytes. A receipt size calculation is below the issuer's 16,300-byte limit.
   The protected store reader passes, both historical grants are T-0002, and
   there are no pending records or recursively matching T-0003 records. Historical
   development grants therefore do not currently block this task.
5. Issuer `stage` validates the administrator/DM/request and store state, checks
   challenge/receipt sizes, then calls `self.send`. It writes `challenge-*` and
   `pending-*` **only after** a valid native message ID returns. Missing receipts
   cannot distinguish no send from delivery followed by an acknowledgement error.
6. `_sidecar_preview_sender` posts to the existing Photon `/send` with a two-second
   HTTP timeout. It requires HTTP 200, a bounded JSON response, `ok: true` and a
   string message ID. Photon awaits its existing `space.send(builder)` and returns
   `result?.id || null`. Successful sends are not journaled. No new connection,
   `/inbound` subscription, live socket request, or messaging operation was used.

Intake runs as alfred:alfred (UID 1000), started at 19:28:35 UTC, with
`PYTHONPATH=/home/alfred/Git/alfred/src:/opt/alfred-developer-v1:/usr/local/lib/alfred-fresh-v1`.
Its installed source predates that start. `ProtectSystem=strict` permits writes
to `/var/lib/alfred-development-grants`; `ProtectHome=no`. The task worktree is
alfred-owned mode 0700 and empty, including in the running Intake mount view.
No permissions or identity checks were changed.

Incident journal, 2026-10-16 UTC:

- 21:59:46.377368: task worktree mkdir subprocess session ended.
- 21:59:48.467371: Evidence returned the generic Intake refusal.
- 22:01:49.600151: next existing timer tick held on the previous challenge attempt.
- Intake and Photon journals have no entries in 21:50–22:10. Photon logs send
  failures but not successful sends; absence is not evidence of no transmission.

Current validation is reproducible, but it is not a historical traceback. A
unique historical failed subcondition cannot be proven from these observations.

## Preserved bindings and inspection limits

| Artifact | SHA-256 / binding |
| --- | --- |
| Canonical CTO plan | `e5b58519eb9943c7b9d093b19880c4a0c881dc5a2491c6e1c68b70ff10f032d6` |
| Frozen context | `bda345a14ec110cf5b3118d7289204c304ba13795f9c9677351aa940d0ab198e` |
| Canonical spec | `2474942d42eef568c150fda9da76601fe4b3bcd946546a22ca9ec6eeeaf22f58` |
| Baseline | `596d91daf3311ad3aa0ee42e7220f699f58daf59` |
| Scope | `calculator.py`, `test_calculator.py` |
| Installed flat and package Intake source | `d3e1677cb8d7ee17ab801448e85db48fee12d88bbf21a3561e9e755eef742168` |
| Installed Developer manifest | `c23cb89acc0ddc17fe382c4ea3e985c8404ebbf2dace1d20bbad19da81fa9edd` |
| Installed Fresh host | `9cb19786ec25b87de5012704fb739b7c8bce9bacdad38469c41b774909ce2b73` |

The original challenge attempt is root-private; this session cannot independently
read its bytes. Its existence and unchanged 77-byte metadata are observable;
`uncertain_until_result` is supplied operator evidence, not a root read repeated
here. Root must checksum its actual bytes before and after any later installation.
There is no challenge result or grant. No original attempt, context, plan,
planning-recovery record, worktree, approval or historical artifact was edited.

At the latest inspection Gateway and Evidence were idle between normal timer
ticks, Intake active, and **Gateway PAUSE was absent**. No service or PAUSE state
was changed. Future installation requires operator-established PAUSE and idle
workers; the existing uncertain-attempt guard is still preventing automatic replay.

## Minimal staged diagnostic correction

Only `developer_v1/trusted_intake_development.py` changes runtime behavior. On
this existing refusal it writes one redacted JSON line to the existing stderr
journal: phase, validated project/task, computed plan hash, allowlisted exception
class/reason, bounded errno, and conservative delivery state. Gateway/binding
failures are `not_attempted`; **every issuer failure remains `uncertain`**, even
if it could have failed before send. Raw exception text, messages, DM/owner IDs,
credentials and response bodies are never logged. Logging failure still refuses.

The socket response, two-second timeout, receipt checks, issuer, native threading,
root caller restriction, owner verification, grant storage and one-use execution
are unchanged. This patch cannot retrospectively diagnose or recover T-0003.
The Developer manifest changes only the Intake source digest. No other runtime
module, policy, service configuration, Gateway, Photon, worker or notifier changes.

See `FRESH_V1_DEVELOPMENT_DIAGNOSTICS_HOST.md` for file-only installation/rollback
and `FRESH_V1_T0003_CHALLENGE_RECOVERY.md` for the separate recovery hold.

## Tests

The original pinned Intake is reproduced with mocked timeout, invalid receipt and
HTTP refusal **after simulated delivery**. All yield the same refusal and absent
challenge evidence, disproving any unique diagnosis from those observations.
New tests cover exact validation phases, redaction, logging failure, unchanged
transport checks, no retry across another poll, and unchanged frozen evidence.
Disposable installation tests cover all three write positions, rollback,
activation-marker preservation, evidence preservation and fail-closed preflights.

Final focused run: **353 passed, 58 subtests passed, 2 skipped**. The two opt-in
authenticated live-model probes were not run. New diagnostic/install tests:
**22 passed**. No live transport, model call, remote Git operation or protected
evidence mutation was used. Changed/new Python files pass focused F/E9 lint;
new test and transaction files pass the configured full lint rules.

The broader first run exposed four historical recovery-install fixture failures:
the fixture read the already-upgraded live host as its pre-upgrade source. Its
source now comes from the pinned historical staged releases with hash assertions;
no production or recovery runtime code changed. Final results are recorded in
`development-challenge-staging-tests.xml` and the release test summary.
