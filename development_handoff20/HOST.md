# handoff.20 host procedure: the owner can retry a publish that failed

## Why
demo-site T-0003 (2026-10-18, 00:34 to 00:38 UTC) ran the whole team: CTO plan,
delegated approval, the frontend agent, QA, a Reviewer change request, one automatic
fix round, QA and Reviewer approval, and the owner's "yes". The Publisher then reported
`ERROR` with `github: GitHub GET request failed: HTTP 404`: its token cannot see the
private demo repository. No branch or pull request was created. The task is held, and
nothing retries a publish on its own.

## What changes (three files, no restart)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py` | After a recorded Publisher `ERROR`, one more publish attempt per owner authorization (at most three), under the same approval. The Publisher re-checks GitHub for an existing branch or draft PR before it pushes. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | Reads the owner's `publisher-retry-<n>.json`; each retry is its own stage (`publisher-retry-<n>`). |
| `/usr/local/sbin/alfred-dev-ops` | `republish project/task`: only after the latest publish recorded `ERROR`, one retry at a time. |

## Before retrying
Give the Publisher's GitHub token access to `hrsnyde1/alfred-demo-site` (Contents and
Pull requests: read and write), or the retry fails the same way.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 20`.
