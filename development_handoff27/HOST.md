# handoff.27 host procedure: the pipeline speaks in the squads' Telegram chats

## Why
The squads bridge (`alfred-os-squads`) carries messages between the agents' Telegram
bots and the squad group chats, but nothing told the chats what the development team
was doing. With this release the team narrates every task in its squad's chat. Approvals,
QA, review and publishing stay exactly where they are, in the pipeline.

## What you will see (squad "web-app" for Frontend, Backend, Full Stack; "ai-data" for
AI/ML, Data Scientist, Data Engineer)

| Step | Who posts |
| --- | --- |
| 📋 New task, the goal and the team | Dev CTO |
| ▶️ "Frontend, you're up" | Dev CTO |
| ✅ What changed, which files, which model (or ⚠️ why not) | the specialist's own bot |
| 🧪 QA verdict and its findings | QA bot |
| 🔎 Review verdict, 🔁 fix rounds | Dev CTO |
| 📨 Waiting for your go-ahead, 🚀 draft PR link, 🛑 stops | Dev CTO |

An agent whose bot is not connected yet is spoken for by the CTO, prefixed with its name
(for example `[data-scientist] ✅ Done…`). Until a squad's chat is linked (`/squad web-app`
in that Telegram group), its messages wait; steps older than six hours are never posted.

## What changes (three new files; nothing installed changes)

| Destination | Purpose |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/squads.py` | Reads the task records; posts through the bridge's agent API on 127.0.0.1:8798 |
| `/etc/systemd/system/alfred-dev-squads.service` | Sandboxed root oneshot: read-only system, no home, loopback network only, its own state directory |
| `/etc/systemd/system/alfred-dev-squads.timer` | Runs it every 20 seconds |

It needs the bridge's agents token (`/etc/alfred-os-squads/agents-token`, already
created by the bridge install) and the `cto` bot token at least.

## Rollback
`sudo systemctl disable --now alfred-dev-squads.timer`, then `sudo alfred-dev-ops pause`,
`sudo alfred-dev-ops rollback 27` and `sudo systemctl daemon-reload`.
