# handoff.28 host procedure: the squads announcer reads real developer reports

## Why
The first live run of handoff.27's announcer (2026-10-18 19:46 UTC) stopped with
`TypeError` on a developer report: real reports list changed files as
`{"path", "sha256"}`, not plain names. Nothing was posted, and nothing in the pipeline
was affected.

## What changes (one file, no restart)
`/usr/local/lib/alfred-fresh-v1/fresh_v1/squads.py` reads both shapes, and a task with a
malformed record is skipped (logged by name) instead of stopping the run. A new test
reads every developer report already on the host.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 28`.
