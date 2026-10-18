# handoff.19 host procedure: plain requests pass QA; stuck tasks can be abandoned

## Why
demo-site T-0002 (2026-10-18 00:02 UTC): planning, delegated approval and the frontend
developer all completed. Independent QA then rejected the work within a second: it
checks every approved file against the CTO plan's scope text, and a plain request
("add a light/dark mode toggle") names no files, while handoff.12 approved all six of
the project's allowed files. The host then raised "independent QA model evidence
missing" inside the QA stage, so QA's verdict was never recorded; every poll since has
held on "qa: previous attempt requires reconciliation", blocking all later requests.

## What changes (three files, no restart)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py` | A request naming no files uses the files the CTO expects to change (`expected_components_files`, for T-0002: `app.js`, `index.html`, `styles.css`) when they can staff every specialist, else all allowed files; the plan's scope then ends with `Approved files: ...`. Requests that name their files are unchanged. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | QA's FAIL or BLOCKED is recorded as its verdict (the fix loop or a verdict hold follows). A PASS still requires the model's evidence. |
| `/usr/local/sbin/alfred-dev-ops` | `abandon project/task`: the owner stops one task for good; one record is added, nothing existing changes. `resend` accepts `project/task`; `status` lists `project/task`. |

## T-0002
Its QA stage stays unrecorded (evidence is not rewritten). Abandon it so later requests
run: `sudo alfred-dev-ops abandon demo-site/T-0002`. Then send the request again.

## Preconditions
handoffs 16, 17 and 18 are installed.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 19`.
