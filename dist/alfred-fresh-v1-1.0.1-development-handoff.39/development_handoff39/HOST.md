# handoff.39 host procedure: one staffing decision, from the plan to the developers

## Why
handoff.37 made the plan step staff plain-language requests from the files they
touch. demo-site T-0009 ("make the UI/UX have clean features like scrolling, hovering
over, etc.") then planned Frontend on `app.js`, `index.html` and `styles.css`. But two
later steps each guessed again from keywords:
- intake's approval request (the grant Hayden's yes signs);
- the developer dispatch (`route`).

Both got Builder. The developer step refused the approved Frontend work item, held as
`developer: python/python_failed`.

## What changes (three files; restarts the intake)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py` | The plan step records its staffing in the plan (`"specialists"`) |
| `/opt/alfred-developer-v1/developer_v1/router.py` | `select_specialists` returns that record when a plan has one; older plans route by keyword as before |
| `/usr/local/lib/alfred-fresh-v1/v1_cto/plan.schema.json` | One optional field, `specialists` |

Hayden's grant binds the plan digest, so the yes approves exactly that staffing, and
the dispatch still checks it against the grant. The release restarts
`alfred-development-intake.service`, which imports `router.py` once at start.

The gateway's own `cto.py poll --prepare-only` validates plans against its own schema
copy, which already lacks `team_profile`. A plan it cannot validate is counted
"unavailable" and nothing is sent, so no message changes. `cto.py show` cannot display
such plans until that copy gains the field (a gateway repository change).

## Order
handoff.37 first (this release pins its `role.py`). Independent of handoff.38, which
changes other files; either may be installed first.

T-0009's grant was bound to Builder, so it cannot continue. Resend the request after
installing.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 39`, then
`sudo systemctl restart alfred-development-intake.service`.
