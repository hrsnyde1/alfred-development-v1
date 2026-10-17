# handoff.13 host procedure: the CTO's specialists use approved team skills

## Why
Lucius Fox proposes skills to `hrsnyde1/alfred-team-skills`, and the owner approves them
by merging. This release lets the merged `cto` skills reach the development team. The
Central CTO is deterministic code, so it does not read skills itself. It selects them for
each task and records them in the plan. The specialist's model receives their text.

## How skills are bound to an approval
1. The owner (as root) runs the library's deploy tool for one merged commit. It writes an
   immutable snapshot `/usr/local/lib/alfred-team-skills/cto/<commit>/`, with a manifest,
   and `ACTIVE`, all root-owned and read-only to every agent.
2. While planning, `fresh_v1/role.py` loads `ACTIVE`'s snapshot and checks it fully:
   ownership and modes, the manifest's file list and SHA-256s, and the library validator's
   format, safety-screen and budget rules (copied into `developer_v1/team_skills.py`, so a
   library change cannot loosen them). It selects a skill when the skill has no filter,
   names one of the task's specialists (`applies_to.specialists`), or has a keyword in the
   task title or objective (`applies_to.keywords`). The plan gains
   `team_skills: {library_commit, role, skills: [{id, title, sha256, tokens}]}`.
3. The development grant binds the plan's digest, so it also fixes these skills.
4. Before claiming the grant, the Developer reloads that same commit, not the current
   `ACTIVE`, and refuses any difference. The grant then stays unused. The worker adds the
   skills to the Codex payload as `team_practices`, with the instruction that they never
   permit other files, commands or scope. Codex still runs with `--ignore-user-config` and
   `--ignore-rules`, so no other skill or rule source is involved.

Without `ACTIVE` the plan has no `team_skills` field and behaviour is exactly handoff.12.
A broken or altered snapshot stops planning (fail closed); removing `ACTIVE` restores the
old behaviour.

## What changes (six files, no restart)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/v1_cto/plan.schema.json` and `/home/alfred/Git/alfred/.dev/bin/plan.schema.json` | Accept the optional `team_skills` record (the Gateway copy keeps its owner). |
| `/opt/alfred-developer-v1/developer_v1/team_skills.py` (new, root 0644) | Snapshot loader, selection and plan binding. Reads only; never writes. |
| `/opt/alfred-developer-v1/developer_v1/pipeline.py` | Verifies the plan's skills before the grant is claimed. |
| `/opt/alfred-developer-v1/developer_v1/real_worker.py` | Adds `team_practices` to the model payload (at most 24 KiB). |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py` | Records the selected skills in the plan. |

Each stage runs as a new process, so no unit is restarted. The schemas are written first,
so every plan reader accepts `team_skills` before a plan can contain it. The live
`developer_v1/release.sha256` is left as it is (it already predates handoffs 8 to 11).

## Preconditions
handoff.12 (multi-project) is installed. All 20 installer pins (5 replaced files, 1 absent
new file, 14 dependencies) matched the live host, read only, before the build.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 13`. It restores the five
files and removes `team_skills.py`. To turn team skills off without a rollback, use the
library tool: `cto-rollback --disable` (see the library README).
