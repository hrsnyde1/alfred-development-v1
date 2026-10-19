# handoff.37 host procedure: plain-language requests reach the right developers

## Why
On 2026-10-19 demo-site T-0008 ("make the UI/UX have clean features like scrolling,
hovering over, etc.") held at planning. The CTO's keyword routing found no frontend
word in "Harbor & Pine Studio demo site: UI/UX polish (scroll, hover,
micro-interactions)", fell back to its general rule, matched "alfred" and chose
Builder. demo-site staffs only Backend and Frontend, so the plan step refused, and
the refusal reached nobody (it is redacted to `plan: python/python_failed`). Hayden:
"I say exactly what I said in the text, and it's able from there to know exactly
which ... developers."

## What changes (one file, no restart)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py` | The plan step staffs from the files the CTO expects to change when keyword routing picks someone the project does not staff, or no one |

1. Keyword routing runs first. When the project allows its choice, it is used exactly
   as before, so every request that routed before routes the same way.
2. Otherwise the files decide. Web files (`.html .css .js .jsx .ts .tsx .vue
   .svelte`) go to Frontend and the rest to Backend. When the project staffs no such
   split, Builder takes the whole job if the project allows it.
3. Staffing never leaves the project's `specialists` and `allowed_scope`, and Hayden
   still approves the plan, which names the developers and files.

A dry run of T-0008's own inputs with this file plans **Frontend** on `app.js`,
`index.html` and `styles.css`. T-0008 itself stays held; resend the request, in the
same words.

## Order
handoff.36 first. This release pins its identity bundle and today's `host.py`.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 37`.
