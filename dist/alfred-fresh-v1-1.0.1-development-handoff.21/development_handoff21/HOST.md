# handoff.21 host procedure: the development agents run on Claude (Phase 1)

## Why
Phase 1 of [DEVELOPMENT_TEAM_V2](../docs/DEVELOPMENT_TEAM_V2.md): builders run on Claude
through alfred's Claude Code login (Sonnet, or Opus for AI/ML), and every agent works
from its owner-reviewed identity (Soul, Role, Skills, Tools, Workflow, Quality, Handoff,
Memory) from hrsnyde1/alfred-team-skills `agents/`. QA, Security and the Reviewer stay
on Codex.

## What changes (five files, no restart)

| Destination | Change |
| --- | --- |
| `/opt/alfred-developer-v1/developer_v1/real_worker.py` | A Claude route: `claude -p` with no tools, no MCP servers, no user settings, no saved session and an empty working directory. It returns the same JSON edit contract the pipeline already checks. A broker sends each model choice to its provider; if Claude is unavailable (limit, login) the approved Codex fallback runs. |
| `/opt/alfred-developer-v1/developer_v1/pipeline.py` | Accepts Claude and Codex models in `models.json`. Each specialist's identity reaches its prompt. Identities are read before the grant is claimed. |
| `/opt/alfred-developer-v1/developer_v1/agent_profiles.py` (new) | Reads the identity bundle; refuses one that is not as protected as the code. |
| `/opt/alfred-developer-v1/developer_v1/agent_profiles.json` (new) | The 13 identities, from team-skills commit `59836a2a4f4a` (draft PR #4). |
| `/etc/systemd/system/alfred-development-evidence.service.d/60-claude-agents.conf` (new) | The Claude login (`~/.claude`, `~/.claude.json`) is writable in the Evidence sandbox. |

Installing changes no model by itself: with today's Codex-only `models.json`, every
agent keeps its model and gains only its identity. The switch is step 3 below.

## Models after step 3

| Agent | Primary | Fallback | Effort |
| --- | --- | --- | --- |
| Frontend, Full Stack, Data Engineer, Integrations | Claude Sonnet | Codex gpt-6-sol | medium |
| Backend, DevOps, Data Scientist | Claude Sonnet | Codex gpt-6-sol | high |
| AI/ML | Claude Opus | Codex gpt-6-sol | high |
| Security, Mobile, Performance | Codex gpt-6-sol | Codex gpt-6.1-sol | high |

Each Claude call uses the Claude Code subscription login (about $0.02 for a small edit
in testing). Opus counts 2 toward a task's cost limit of 6; everything else counts 1.

## Rollback
`sudo alfred-dev-ops pause`, restore the old `models.json` from the backup made in
step 3, then `sudo alfred-dev-ops rollback 21` and `sudo systemctl daemon-reload`.
