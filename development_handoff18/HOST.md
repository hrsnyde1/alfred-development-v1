# handoff.18 host procedure: the demo site's repository is writable in the sandbox

## Why
demo-site T-0001 started (2026-10-17 23:44 UTC, after handoff.14) but planning failed
with `git_fetch/process_failed`. The Evidence service runs every stage with
`ProtectHome=read-only`; only the calculator's lab repository is listed as writable.
Planning fetches the project's current `main` into its lab repository, and the
developers' worktrees are added to it, so the demo site's repository must be writable
there too. GitHub access was not the problem: both repositories are private and the
same fetch works outside the sandbox.

## What changes (one new file)

| Destination | Change |
| --- | --- |
| `/etc/systemd/system/alfred-development-evidence.service.d/50-project-repos.conf` (new, root 0644) | `ReadWritePaths=/home/alfred/alfred-development-lab/demo-site/repo`. |

The existing `40-fresh-v1.conf` is unchanged (and must be, or the installer refuses).
Run `systemctl daemon-reload` after installing so the next poll uses it. Nothing restarts.

## After install
T-0001 keeps its recorded planning failure as evidence and is not retried. Send the
request again from your phone; it becomes the next demo-site task.

## Rollback
`sudo alfred-dev-ops pause`, `sudo alfred-dev-ops rollback 18`, then
`sudo systemctl daemon-reload`.
