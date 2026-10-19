# handoff.36 host procedure: the reviewed workforce reaches the agents

## Why
The 13 identity PRs (alfred-team-skills #11-#23), the shared charter (#24) and the
condensing follow-up (#25) are reviewed, but the host still runs handoff.21's bundle
(team-skills `59836a2`). Hayden asked to make the merged workforce operational through
the existing architecture. The charter loader is alfred-development-v1 PR #41, already
on main but not installed.

## What changes (two files, no restart)

| Destination | Change |
| --- | --- |
| `/opt/alfred-developer-v1/developer_v1/agent_profiles.py` | PR #41: stores `agents/CHARTER.md` once in the bundle; each identity is the charter, then the agent's own files |
| `/opt/alfred-developer-v1/developer_v1/agent_profiles.json` | Rebuilt from alfred-team-skills `3f89e281` by `rebuild_bundle.py`; 13 agents plus the charter, 72,037 bytes |

Nothing else changes: models (`models.json`), staffing (`policy.json`), tools, approvals,
QA, Reviewer, publishing and merge. Specialists get the new text from their next task.
Alfred OS team snapshots still layer on top as before.

Per-call identity size, charter included: 5,993 to 8,132 bytes (about 1.5k to 2.0k
tokens), leaving at least 16 KiB of the 24 KiB prompt budget for practices and
Repo Intelligence.

## Order
1. Merge alfred-team-skills #25 **with a merge commit** (not squash), so `3f89e281` is on
   its main. If it is squashed instead, re-run `rebuild_bundle.py` at the new main
   commit, update `TEAM_SKILLS_COMMIT` in `tests/test_claude_agents.py`, and rebuild this
   release.
2. handoff.35 must be installed. This release pins its `team_snapshot.py` and refuses
   otherwise.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 36`. That restores both
files byte for byte: handoff.35's loader and handoff.21's bundle.
