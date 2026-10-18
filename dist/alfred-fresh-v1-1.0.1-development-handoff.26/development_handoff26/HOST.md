# handoff.26 host procedure: the development agents use their own Claude token

## Why
demo-site T-0004 (2026-10-18 18:03 UTC): the frontend agent failed in seconds with
`worker exception: Denied`. The owner's Claude Code login was due for a token refresh.
A refresh writes a lock folder and temporary copies beside `~/.claude.json` and under
`~/.local/state`, and the Evidence sandbox keeps `/home` read-only, so Claude answered
"Failed to refresh OAuth token". That error was not recognised as the provider being
unavailable, so the approved Codex fallback did not run either.

## Order
Install handoff.23 (the completion acknowledgement fix) first. handoff.26 refuses
otherwise, because handoff.23 pins the files this release replaces.

## What changes (three files, no restart)

| Destination | Change |
| --- | --- |
| `/opt/alfred-developer-v1/developer_v1/real_worker.py` | Shipped as `development_handoff26/real_worker.py`: the installed file plus this fix only. Claude runs with the agents' own long-lived token and a private home, `/var/lib/alfred-development-state/claude-agents` (0700, already writable in the sandbox). The owner's own Claude Code login is never used or written. Login, token and API errors count as "unavailable", so the Codex fallback builds instead. With no token saved, every builder uses Codex. |
| `/usr/local/sbin/alfred-dev-ops` | `claude-token`: paste the token (hidden). It is saved to `/etc/alfred-development/claude-agents.token`, root-owned, group alfred, 0640. Only a 12-character fingerprint is printed or logged. |
| `/etc/systemd/system/alfred-development-evidence.service.d/60-claude-agents.conf` | No longer opens `~/.claude` or `~/.claude.json` to the sandbox. |

The agents' token is separate from your own login: signing out of Claude Code, or a
refresh in your own sessions, does not affect it. It is valid for one year; run
`claude setup-token` and `alfred-dev-ops claude-token` again to renew it.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 26` and
`sudo systemctl daemon-reload`. To stop using the token without a rollback, delete
`/etc/alfred-development/claude-agents.token`; every builder then uses Codex.
