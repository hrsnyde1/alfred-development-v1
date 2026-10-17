# handoff.7 host procedure

## Why
- **T-0008 (Gate 6):** the Developer completed, with a scoped commit and the
  grant closed `completed`, and QA **passed**. The Reviewer preparation then
  failed in `host_prepare` with `unsafe_repository_ownership` (git exit 128),
  so the Reviewer worker never started.
- **The cause:** root snapshots the alfred-owned final worktree with
  `git clone --no-local`. Ubuntu's git 2.43, which carries the 2024 ownership
  hardening, checks the worktree's own git directory, `repo/.git/worktrees/<name>`.
  `safe.directory` named only the worktree.
- **Reproduced:** with `GIT_TEST_ASSUME_DIFFERENT_OWNER=1` against T-0008's real
  final worktree, the old single entry fails with "detected dubious ownership"
  in both the snapshot and the bare clone. The worktree, its git directory and
  the common directory together succeed.
- **Next affected:** the publication-plan stage uses the same clone, so it would
  have failed next.

## What changes (one file)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | `clone_snapshot` trusts exactly the worktree, the git directory named by its alfred-owned `.git` file, and the **registered repository's** `.git`. It refuses any git directory outside `<repository>/.git/worktrees/`. A linked worktree already uses that repository's common config, so trust is unchanged. |

The installer refuses unless all of these hold:
- PAUSE is present;
- `host.py` has exactly its handoff.4 bytes;
- the handoff.5 drop-in and the seven other runtime files match their pins;
- the activation marker is unchanged.

It writes a root-only backup and rolls itself back on any fault. The Evidence
poll imports `host.py` on every run, so nothing reloads or restarts.

## Verification
`verification/role_sandbox_preflight.py` now also runs **root's snapshot clone**
inside the Evidence sandbox: a normal and a bare clone of the newest real final
worktree, into the private `/tmp` only. Before handoff.7 it reports
`installed host lacks clone_snapshot`.

## After install
- **Held tasks:** T-0003 through T-0008 stay held and untouched. The poll skips
  the ones with recorded failures.
- **Next run:** Gate 6 is retried with a fresh request, T-0009.

## Rollback
Run in a root shell with PAUSE present:

```
install_patch.py rollback --backup <backup>
```
