# handoff.14 host procedure: a held task no longer blocks later requests

## Why
After handoff.12 was installed, demo-site T-0001 was filed (2026-10-17, 22:03 UTC)
but never started. Every poll stopped at dev-v1-accept T-0010, a duplicate request
held since 19:22 because its Reviewer did not approve, and returned
`held: independent Reviewer did not approve`. Only tasks with a recorded failure
file were skipped; a held task without one blocked every request behind it.

## What changes (one file, no restart)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | The poll moves past a held task to the next one, as it already does for tasks waiting on the owner. It reports the first held task only when nothing else ran. The held task's evidence is untouched and nothing is retried. Base: the handoff.12 host. |

The Evidence poll imports `host.py` on each run, so nothing restarts.

## After install
demo-site T-0001 starts on the next poll (about two minutes after resume). T-0010
stays held, as evidence.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 14`.

## Relation to handoff.13 (team skills)
Independent. This replaces only `host.py`, which handoff.13 does not change, and it
does not pin the files handoff.13 replaces. handoff.13 pins the handoff.12 `host.py`,
so install handoff.13 first if you want both.
