# T-0003 recovery preparation

## Readiness

The confirmed failure is recoverable with one separately authorized planning
attempt. **Preparation is complete; live recovery is not authorized or executed.**
The operator must first pass the root read-only preflight below. This session is
running as alfred and cannot read the root-private attempt or canonical policy
bytes; noninteractive sudo requires a password. The supplied successful root
preservation checks are accepted evidence, not misrepresented as checks repeated
by this session. A failed root preflight means **BLOCKED**, with no override.

## Observed evidence and effects

- Installed host/role/diagnostics match planning fix.1; handoffs/protected remain
  unchanged from V1.0.1. Gateway/Evidence were inactive/dead, with zero main and
  control PIDs. Existing Gateway PAUSE is present and was not changed.
- T-0003's directory still contains only job.json and plan.attempt.json.
  Original attempt size and nanosecond modification time are unchanged.
- Policy is root:root 0600, with no POSIX read ACL. Its ctime
  `1792181550744820182` precedes attempt mtime `1792181749323796085`.
  The private access condition has not changed since before the failed attempt.
- One matching canonical filing and one canonical task exist. The authenticated
  native confirmation route still binds the same owner/DM/request. No task
  approval/challenge/grant record was found, including nested request bindings.
- Canonical spec SHA-256:
  `2474942d42eef568c150fda9da76601fe4b3bcd946546a22ca9ec6eeeaf22f58`.
- Preliminary plan SHA-256:
  `a9a900a7259aa8945b64e48d40228a0fee7ab5dcde2294cbd2db7589302a45ee`.
  It is pending/undelivered, has no baseline revision and predates the attempt.
- The local planning main ref is still absent. No GitHub request, fetch or other
  remote diagnostic was executed during this recovery preparation.

The historical root helper launched an alfred **planning process** (the PAM
session is logged). Its required first policy read fails before prepare_plan.
Therefore that attempt could not reach GitHub lookup/fetch, a development
approval send, a grant, or Developer/QA/Reviewer/Publisher execution. Creating the
job/attempt and logging the failed process are its known local effects.

The owner's initial request confirmation and Gateway's earlier preliminary plan
are separate, successful pre-planning effects; neither is erased or repeated.
Prior read-only GET/ls-remote diagnostics in the failure investigation likewise
are distinct from the failed planning attempt.

Missing challenge receipts alone would not prove no send: Intake sends before
writing its receipt. The proof here is the confirmed earlier EACCES control-flow
barrier, corroborated by unchanged evidence, not an inference from missing files.
The historical stderr was discarded, so a historical traceback is not available.

See `fresh-v1-recovery-inspection.json` for the redacted read-only observations.

## Exact append-only design

Only the existing Fresh handoff is extended; no new worker, service or timer.

1. A root-only read-only `inspect` verifies the original uncertain attempt,
   private-policy history, unchanged native route/spec/registry, original pending
   plan, absent later handoffs and absent matching approval evidence. It returns
   a deterministic, redacted report of hashes.
2. After an explicit operator decision, `authorize` requires PAUSE, the existing
   poll lock, an inspection SHA-256 and a real operator decision reference. It
   preserves actual preliminary bytes as root-owned
   `plan-recovery-1.preliminary.json`, then exclusively creates
   `plan.recovery.json` as the final commit. Both are fsynced. It invokes no role,
   transport or approval issuer and creates no attempt/result/context/grant.
3. The decision is **planning only**, for dev-v1-accept/T-0003, generation 1.
   It pins job, original attempt, preliminary plan, canonical spec, native route,
   registry, canonical policy and all six relevant Fresh runtime files. The
   unused decision expires in one hour. It cannot be renewed or overwritten.
4. On a later separately authorized release of PAUSE, the existing Evidence poll
   verifies the protected decision and current evidence. The usual `once()`
   exclusively writes `plan-recovery-1.attempt.json` before calling Host.plan.
   The original `plan.attempt.json` is never changed, renamed or deleted.
5. The installed corrected planner performs normal current-main planning. Root
   freezes context and `once()` writes `plan-recovery-1.result.json` only from its
   actual returned result. The handoff validates context/result/plan consistency
   before proceeding to the existing native development challenge.
6. A successful result is reused across restarts. An interrupted/failed new
   attempt stays uncertain and is never retried automatically. A consumed
   decision's expiry does not invalidate a completed result or manufacture a new
   attempt. No generation 2 or generic retry mechanism is supplied.

**Preliminary plan preservation:** original bytes are retained in the immutable
root copy and pinned decision. A genuinely successful normal CTO run will then
replace its pending canonical plan with the new baseline-bound plan, as the
existing planner already does. No operator writes that new plan. If preservation
requires the original canonical pathname itself to remain unchanged forever,
this procedure is BLOCKED: the existing approval issuer reads that pathname.
This design preserves the historical version while allowing the normal plan to
advance. Preparation itself does not rewrite the canonical preliminary plan.

Both native owner approvals remain mandatory. Operator recovery permission is
neither development nor publication authorization; it carries no owner_event_id.
Developer execution, independent QA/Reviewer identities, exact-plan publication
approval, draft-only Publisher behavior and notification deduplication are unchanged.

## Staged changes and tests

- `fresh_v1/handoffs.py`: one literal plan-recovery-1 branch, with verification
  before and after the existing planning action.
- `fresh_v1/host.py`: a root/activation/PAUSE guarded verifier method.
- `fresh_v1/recovery.py`: exact-incident evidence checks, append-only operator
  preparation and read-only inspection/verification CLI.
- `fresh_v1_recovery_patch.py`: narrowly mapped file transaction over installed
  planning fix.1. It changes only those three runtime files, with durable backup
  and rollback; no policy, evidence, credentials or service configuration changes.
- `tests/test_fresh_v1_recovery.py`: 32 focused cases, including the complete
  mocked pipeline with both real native verification paths, no dispatch during
  preparation/PAUSE, nested approval conflicts, mismatched/expired/untrusted
  evidence, interruption/restart refusal, preservation and code-only rollback.

**331 passed, 2 live-model probes skipped, 58 subtests passed** in the full focused
V1 suite. Privilege transitions and external endpoints remain mocked; production
recovery and live planning have not been executed. Ruff passes.

## Operator gates and risks

Use `FRESH_V1_T0003_RECOVERY_HOST.md` for exact pinned package and commands.

1. Root read-only verification of the private original attempt and existing
   preservation baseline must pass. Do not chmod/chown/setfacl to obtain access.
2. Approve installation of the recovery extension while PAUSE is retained and
   all existing workers are idle. No service reload/restart is needed.
3. Run root `inspect`; review the exact task/evidence report and pin its hash.
   Any unexpected state, approval or changed file means stop and investigate.
4. Separately authorize one new planning attempt, using an actual operator
   decision reference, and run `authorize`. Verify the resulting record without
   executing a worker. Keep PAUSE in place.
5. A later separate decision may release PAUSE through the normal operator
   procedure. Allow the existing timer to do the work; do not call plan/poll,
   inject a Gateway task, issue a challenge manually or launch a specialist.

The next actual planning operation can still fail for a new reason. It will keep
its distinct attempt and redacted failure evidence and remain held. This package
does not authorize automatic retries of planning or ambiguous sends. If an unused
operator decision expires, leave it intact and obtain a new reviewed recovery
decision/design; do not edit its timestamp or bypass the guard.

Rollback restores only code and leaves every original/recovery record and any
later planning, approval, QA/Reviewer/Publisher/notification evidence intact.
Restored pre-extension handoffs hold on the original uncertain attempt.
