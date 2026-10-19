# handoff.38 host procedure: a refused plan reaches Hayden

## Why
On 2026-10-19 demo-site T-0008 held at planning. Alfred had already told Hayden
"Filed. Task ID T-0008". After that he got nothing. The plan step refused the task
("scope or specialist requires clarification"). The worker boundary correctly redacts
every exception, so the refusal was recorded as `plan: python/python_failed`. The poll
froze `plan.failure.json` and the task sat held. handoff.37 fixes that task's staffing.
This release makes sure the next refusal, whatever its cause, is not silent.

## What changes (four files; the intake restarts)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/diagnostics.py` | Plan refusals become a fixed category (phase `plan_refusal`) |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | A task held by such a refusal sends Hayden one text through Intake |
| `/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py` | New root-only op `notify_owner_plan_refused`, with one fixed text per category |
| `/usr/local/lib/alfred-v1.1/trusted_intake.py` | The same file (the second installed copy) |

1. **Fixed categories, never text.** `prepare_plan`'s refusals are recognised by their
   exact message, which is compared and then discarded. Only the category is kept.
   Anything else, including a refusal message with extra text, stays
   `python/python_failed` as before. The host accepts a refusal category only together
   with phase `plan_refusal` for the `plan` stage.

   | `prepare_plan` refusal | Category |
   | --- | --- |
   | scope or specialist requires clarification | `clarification_required` |
   | project outside activated low-risk policy | `project_outside_policy` |
   | registered main unavailable | `registered_main_unavailable` |
   | main moved during planning | `main_moved` |
   | unsupported planning tree / planning tree too large | `planning_tree_unavailable` |

2. **One text, once.** When the poll finds a held task whose `plan.failure.json` has one
   of these categories, it sends the notice through Intake. This happens on the same
   tick for a new hold, or on a later tick for evidence already recorded. The notice is
   recorded with `plan-refusal-notice.attempt.json` / `.result.json`, like every other
   send. A send that did not answer is never repeated. The task stays held and its
   evidence is untouched either way.
3. **Intake words it.** The host sends only the project, task ID, DM and category.
   Intake checks that it came from root, that the task ID is `T-NNNN` and that the
   category is known, then sends a fixed sentence, for example:

   > T-0008 (*the project's registry name*) needs a clearer request: which files or
   > which part should change? Send it again with that detail. Nothing was started.

   No exception text, model output, command, path or traceback is ever in the text.

T-0008's existing evidence says `python_failed`. It predates the categories, so it gets
no text.

## Order
handoff.37 first. That release pins today's `host.py`, so it could not install after
this one. This release pins handoff.37's installed `role.py`.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 38`. The intake is
restarted to load the previous code.
