# handoff.42 host procedure: refusal texts, installable after handoff.41

## Why
handoff.38 makes a refused plan step text Hayden the reason instead of holding the task
silently. It pinned handoff.37's `role.py` only as an ordering guard. Handoffs 39, 40 and
41 replaced `role.py` since, so `install 38` would now refuse. This release carries the
same four files and pins handoff.41's `role.py` instead.

One wording change: a task marked high risk is refused with the "project outside
policy" reason (demo-site T-0014). handoff.38 would have said the project "isn't set up
for automatic development", which is wrong for that case. The text is now:
"can't be planned: automatic development runs only low-risk changes to projects set up
for it. If this one is low risk, ask me to file it again marked low risk."

## What changes (four files; restarts the intake)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/diagnostics.py` | The plan step's own refusals become a fixed category |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | A task held by such a refusal texts the owner once |
| `/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py` | The notify op and its fixed texts |
| `/usr/local/lib/alfred-v1.1/trusted_intake.py` | The same file, the intake's installed copy |

## Order
handoff.41 first. Do not install handoff.38; this release replaces it.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 42`.
