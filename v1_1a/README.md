# V1.1a Gateway task filing staging candidate

Source pin: `/home/alfred/Git/alfred` at
`0086db5f2c9a41b66161559a11056e4d14138cf9`. The source checkout was read
only and remained clean. The only proposed protected-source change is
`patches/gateway-task-filing.proposed.patch`; nothing was installed.

## Scope and mechanism

- `.dev/bin/taskspec.py`: allocate above task filenames in the checkout, local
  and remote-tracking branch tips, branch names, all local worktrees (including
  untracked task files), and `.dev/task-id-reservations.txt`. Ref inspection is
  read only, bounded per Git command, and fails closed on Git errors. The
  reservation file pins T-0009 and T-0013 for the Alfred repository, as named
  in proposed ADR 0011. No automatic fetch is performed.
- `.dev/bin/intake.py`: hold an exclusive lock on the target `.dev/tasks`
  directory across request-ID deduplication, allocation and publication. A
  repeated request ID returns its original task only when authority and draft
  content match. A changed replay fails. New specs are validated, rendered to
  a same-directory temporary regular file, file-synced, linked into the final
  name without overwrite, and directory-synced. A crash after the link is
  recovered by request-ID lookup. The existing `alfred.devreq/1` envelope,
  registry resolution, requester binding and `proposed` status are unchanged.
- `fixture/dev-001` contains an isolated task directory. Tests create its
  temporary Git repository and substitute its temporary absolute path into
  `fixture/registry.template.yaml`; this fixture is not a live registry edit.

The directory lock coordinates Gateway filers that use this patch on one local
filesystem. A separate `/ship` session does not currently take that lock.
Therefore this candidate does **not** remove ADR 0011's hold on live
`gateway.py run-once` by itself.

## Verification

All commands below used the existing pinned Python environment and temporary
test directories. The Gateway regressions ran in a disposable `git archive`
copy of the pinned source with the proposed files overlaid; they did not call
the live dispatcher.

| Check | Result |
| --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 /home/alfred/Git/alfred/.venv/bin/python -m pytest -q -p no:cacheprovider v1_1a/tests` | 15 passed |
| `python -m pytest -q -p no:cacheprovider tests/dev/test_taskspec.py tests/dev/test_intake.py tests/gateway/test_dispatcher.py tests/gateway/test_envelope.py tests/gateway/test_requesters.py tests/gateway/test_requester.py tests/gateway/test_adr.py tests/gateway/test_cli.py tests/gateway/test_hermes_requester.py` in disposable checkout | 495 passed |
| `ruff check .dev/bin/taskspec.py .dev/bin/intake.py` and `ruff format --check .dev/bin/taskspec.py .dev/bin/intake.py` in disposable checkout | passed |
| `ruff check v1_1a/tests` | passed |
| `patch --dry-run -p1 -d <pristine-disposable-checkout> -i <absolute-patch-path>` | all three paths checked successfully |

An initial run had four regression failures because malformed historical task
files were rejected. That change was removed to preserve established Gateway
behavior; the final 495-test run has no failures or skips. Malformed historical
files still consume their filename ID. New publications cannot leave a partial
canonical spec because the final name is linked only after file fsync.

## Review and live-activation blockers

1. Proposed ADR 0011 R-ID requires Hayden's reviewed task spec, protected-path
   authorization in an attested human session, and acceptance of the exact
   source diff before a protected merge. The owner's existing hold on real
   `gateway.py run-once` remains in force.
2. `/ship` interactive allocation must be made to share the allocation lock or
   be operationally excluded while Gateway filing runs. This staging patch
   coordinates Gateway filers only. A stale remote-tracking ref also cannot
   prove no new remote ID; a reviewed pre-filing fetch/single-writer gate is
   needed for live use.
3. The disposable `dev-001` registry fixture is not a protected production
   registry entry. Its activation needs separate approval under ADR 0003.
   Photon origin verification, whole-process isolation and automatic CTO
   pickup belong to later authorized stages.
4. Request-ID recovery is proved for the single `dev-001` project fixture.
   A cross-project replay after a crash before the Gateway journal records
   `filed` requires a separate protected Gateway-wide binding or an enforced
   one-project V1 scope before multi-project intake is enabled.

Rollback after a separately approved installation would restore the two pinned
source files and remove the new reservation file in the same protected change,
while keeping the Gateway stopped. No rollback action was executed here.
