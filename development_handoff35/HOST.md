# handoff.35 host procedure: agent identities may include Escalation.md

## Why
The Development CTO identity (alfred-team-skills PR #11) adds `Escalation.md`: the
exact stop conditions and the `NEEDS DECISION:` format. Neither identity loader read
it, and the full CTO identity with it (8,833 bytes) is over the old 8,192-byte cap.
Hayden asked to "add Escalation.md to both identity loaders and raise the profile cap,
as a pinned release."

## What changes (two files, no restart)

| Destination | Change |
| --- | --- |
| `/opt/alfred-developer-v1/developer_v1/agent_profiles.py` | Reads `Escalation.md` when an agent has one, after the eight files; the cap goes to 12,288 bytes per identity |
| `/opt/alfred-developer-v1/developer_v1/team_snapshot.py` | An Alfred OS snapshot may list `Escalation.md`; it is injected after Quality and before Handoffs |

Agents without the file are unchanged. No identity content changes: the agents keep
today's bundle until a separately authorized rebuild of `agent_profiles.json`. The
specialists' prompt budget (24 KiB for identity plus practices) is unchanged.

For Alfred OS snapshots to carry the file, its team applier (alfred-hq,
`bridge/alfred_os_team_apply.py`) must also allow `Escalation.md`; that is the bridge's
own change.

## Order
Install handoff.34 (Repo Intelligence) first. It pins these two files as they are now;
this release refuses until handoff.34 is installed.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 35`.
