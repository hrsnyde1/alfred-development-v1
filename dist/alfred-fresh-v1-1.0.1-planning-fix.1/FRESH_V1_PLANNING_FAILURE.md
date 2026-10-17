# Fresh-Task V1.0.1: T-0003 planning failure

## Conclusion

**Confirmed implementation defect: the unprivileged worker cannot read its policy.**
The installed root helper supplies `/etc/alfred-fresh-v1/policy.json` to the
`alfred` worker. That file is root:root, mode 0600, with no read ACL. The first
input read in `role.main()` therefore fails with EACCES before `prepare_plan()`
can look up GitHub main, fetch, construct its verified CTO plan or request approval.

The original worker stderr and exit code were discarded. The historical traceback
cannot be recovered from the available journal. This conclusion comes from the
installed control flow, matching release hashes, original file metadata and a
read-only reproduction of the exact imports and policy read, not a recovered
historical traceback or a retry of planning.

T-0003 remains **HELD**. The staging patch does not release or retry it.

## Evidence and exclusions

| Check | Finding |
| --- | --- |
| Installed host.py and role.py | Match the pinned V1.0.1 release exactly. |
| Canonical policy | UID/GID 0:0, 0600; `alfred` open fails errno 13. Last modified before the first attempt. |
| Exact installed worker imports, then policy read | Imports succeed, policy read returns exit 1 / PermissionError errno 13. The planning entry point was never called. |
| job.json | Root-owned; named read ACLs already supply the four existing worker identities. |
| First journal failure | 2026-10-16 20:15:49 UTC: runuser session opens/closes, then held/CalledProcessError. |
| Subsequent evidence ticks | Held: previous attempt requires reconciliation. No automatic replay. |
| Preliminary CTO plan | SHA-256 `a9a900a7259aa8945b64e48d40228a0fee7ab5dcde2294cbd2db7589302a45ee`; created before the root attempt; pending delivery; no baseline revision. This is the separate Gateway prepare-only output. |
| GitHub main GET, clean alfred environment | Exit 0, valid revision. Uses installed gh and existing authentication; no token output. |
| Git ls-remote, same credential-helper settings | Exit 0, main returned. No local fetch or remote write. |
| Canonical Git metadata | Owned by alfred, writable to alfred; planning ref absent. No fetch was executed in this investigation. |

The Evidence unit is root:alfredevidencero with NoNewPrivileges, a restricted
capability set, ProtectSystem=strict and ProtectHome=read-only. Its existing
Fresh-Task drop-in allows AF_UNIX/INET/INET6/NETLINK, Git metadata writes at the
registered repository's `.git`, and the required handoff/Gateway directories.
It has no private network or IP deny rule. These settings cannot grant alfred
read access to a root-only policy file.

The journal's pam_limits EPERM messages are **not evidence that Git failed**.
The installed Ubuntu pam_limits binary (1.5.3-5ubuntu5.7,
SHA-256 `c760ee59d9cf02f0f783168977dcb178a485ae6e37599a342590d473c0b9a1df`)
was inspected: the failed-setrlimit branch skips accumulating EPERM as a session
failure. runuser also records a completed session. No PAM configuration,
resource limit or capability change is proposed. The upstream runuser
[session/error propagation code](https://raw.githubusercontent.com/util-linux/util-linux/v2.39.3/login-utils/su-common.c)
helps distinguish a session-open refusal from a child failure; the installed
distribution binary, rather than upstream pam_limits assumptions, was checked.

The successful GET/ls-remote probes were outside the systemd mount namespace.
They establish authentication/helper availability, not that a future sandboxed
fetch has passed. No Git permission, missing-object, safe.directory or fetch-syntax
failure was observed. Those are not the confirmed cause. The local fetch has a
local write effect and was intentionally not replayed.

## Failure propagation defect

The root subprocess wrapper captures stdout/stderr and raises CalledProcessError.
The handoff boundary records only the exception class. Local Git additionally
redirects stderr to /dev/null. This hides whether failure happened at worker
startup, policy read, GitHub lookup, local fetch, ref verification or tree read.
The service exits successfully while the task is held; oneshot health is not
evidence of successful planning.

## Minimal staged correction

Only three runtime files change, within the existing Fresh-Task glue:

- `fresh_v1/host.py`: root validates the current canonical policy as before, then
  freezes a separate `worker-policy.json` in the protected job directory and
  shares it read-only through the existing four worker ACLs, as already done for
  job.json. An existing snapshot must exactly match current validated policy.
  The original policy stays root:root 0600. Its paths/configuration are shared;
  credential contents are never read or copied. Each later dispatch still checks
  the canonical activation and PAUSE/STOP boundaries.
- `fresh_v1/role.py`: reads that protected snapshot with the same descriptor,
  owner, parent, link and mode checks. Wraps planning subprocesses with fixed
  diagnostic phase names and emits a redacted error object at the process boundary.
- `fresh_v1/diagnostics.py`: fixed schema/enum diagnostics. No raw stderr, command,
  stdout, exception message, token, owner text or environment is persisted.

Root exclusively creates `<worker-stage>.failure.json` on failure, with phase,
category, operation/worker return codes and errno. Startup and invalid-result
failures also receive redacted evidence. It creates neither a success result nor
context. Existing attempt semantics and immutable failure evidence prevent
automatic replay, including after restart. These records are diagnostic evidence,
not authorization evidence or proof of no side effects for an arbitrary failure.

The transaction utility `fresh_v1_planning_patch.py` changes only those three
code paths. It pins the installed V1.0.1 dependencies, requires operator PAUSE,
backs up before mutation, restores on partial failure and supports explicit
interrupted recovery. It does not change policy, service configuration, activation
markers, permissions on existing evidence, credentials or any agent/component.

## Verification

- **299 passed, 2 skipped, 58 subtests passed** in the existing focused V1 suite
  plus the new planning regression tests. The skipped cases are explicit real
  model probes. Photon, GitHub writes and model responses were mocked.
- New regressions cover OS read denial, the corrected sealed input/read ACLs,
  policy changes and disablement, individual subprocess failure phases, secret
  redaction, timeout/startup/invalid-output failures and restart refusal to replay.
- Disposable installation/rollback tests cover all three partial-failure points,
  interrupted recovery, invalid pins/contracts/inventory/PAUSE, and preservation
  of activation, T-0003's uncertain attempt, T-0001/T-0002 grants, QA/Reviewer
  evidence, publication authorization/plan, credentials and notification tracking.
- The original V1.0.1 archive and its pinned 196-file inventory remain intact.
- Ruff passes for changed Python files. See `fresh-v1-planning-regression.xml`
  and `fresh-v1-planning-inspection.json`.

Privilege transitions are modeled in staging tests; real filesystem denial and
ACL behavior are exercised separately. No production worker or systemd sandbox
was invoked. Host execution remains a separately authorized acceptance step.

## Separate T-0003 recovery recommendation

Existing evidence supports recording **planning failed before the policy could
be read**, with this report attached to a separate operator incident/audit record.
It does **not** contain a completed baseline-bound CTO plan or context that can
be recovered. The preliminary plan must not be promoted into plan.result.json,
context.json or an approval request. A current GitHub main lookup cannot establish
a missing historical planning result.

Preserve the task, preliminary plan and original uncertain attempt exactly as
they are. The installed `once()` deliberately has no reconciliation/retry bypass.
Installing this patch leaves T-0003 held and does not add such a bypass.

If the owner/operator later authorizes continuation, first review a narrowly
scoped append-only recovery mechanism: retain the original attempt; bind the
operator decision to the canonical task, this incident evidence and installed
patch hashes; record a distinct single new planning attempt. That would be a new
operation requiring separate authorization, not recovery of an existing result.
No recovery record or new attempt has been created here. Do not delete/rename the
attempt, fabricate context, manually issue an approval, or create a replacement
task to evade the held guard. The existing poll selects this held task first, so
a new request alone would not resolve the queue hold.

## Host procedure

See `FRESH_V1_PLANNING_PATCH_HOST.md` for the exact pinned package, file-only
installation and rollback commands. Those commands are for later operator
approval. No production change, restart, iMessage, planning retry or GitHub write
was performed during this investigation.
