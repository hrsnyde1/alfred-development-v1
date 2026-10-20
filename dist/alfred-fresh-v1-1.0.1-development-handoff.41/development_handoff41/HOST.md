# handoff.41 host procedure: only code-checkable criteria go on the checklist

## Why
QA and the independent Reviewer must mark every acceptance criterion in the CTO plan as
passed. demo-site T-0012 and T-0013 (2026-10-20) each ran all three fix rounds and were
held, although the Reviewer's last review said "No concrete code defect is established
by this diff". Three of T-0013's criteria can't be shown by a diff or a sandboxed test:
- "Site is verified responsive and functional on desktop and mobile" (needs a browser)
- "No existing content, copy, layout structure, or functionality is changed or broken"
  (needs the running site)
- "Changes pass Build -> QA -> Review cycle with no merge/deploy until Hayden explicitly
  approves" (the process itself, which the pipeline enforces)

## What changes (one file, no restart)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py` | The plan step moves such criteria from `acceptance_criteria` into the plan's `risks_blockers` |

The moved criteria read as follows in the plan Hayden approves:
- "Enforced by the pipeline, not checked in code: …"
- "Hayden checks on the draft PR (needs a browser or the running site): …"

Everything else stays on the QA and Review checklist exactly as written. If nothing
checkable would remain, the criteria are left untouched. A dry run of T-0013's real
inputs keeps its five code criteria and moves exactly the three above. The calculator
project loses only "no merge or deployment performed."

## Order
handoff.40 first. This release pins its `role.py`.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 41`.
