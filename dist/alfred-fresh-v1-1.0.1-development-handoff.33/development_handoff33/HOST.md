# handoff.33 host procedure: one approval, on the CTO's plan

## Why
Owner's instruction, 2026-10-19: "separate planning approval from routine development …
That's too much human-in-the-loop." "All I want is a simple approval text of the plan
that is being mapped out. I don't want the first one where it's development task
created. All I want is just it explaining what the plan is that they put together, and
then I approve the plan." "Then the only other time I should be talking to Alfred is if
he's completed it or if the merge failed or if they need user approval for any of the
tasks."

Choices: every request waits for the owner's yes on the plan; the plan text is a short
summary (the goal, who on the team does what, which files) ending "Reply yes to start."

## What the owner sees after this (listed projects: dev-v1-accept, demo-site)

1. **No text when you ask.** The request is filed straight away; there is no "Here's what
   I'll hand to the development team…" preview and no confirmation reply.
2. **The plan** (one text, once the CTO has planned it), for example:

   ```
   Plan for Demo site: Make the footer text gray.
   - Frontend: styles.css
   Reply yes to start.
   ```

   Reply **yes** to that text (also "y", "go ahead", "start", "approve"), within 12 hours.
   Nothing is built before that yes. Any other reply ("what about mobile?") starts
   nothing and leaves the plan open; a yes after 12 hours is refused.
3. **The end**, unchanged: done and merged (with "Reply undo within 24 hours"), or the
   merge failed (the draft PR waits for you), or stuck after 3 fix rounds, plus the
   undo result if you reply undo.

Projects not in the list keep today's flow: the request preview, the development
approval text and your own draft PR approval and merge.

## How it works
- `/etc/alfred-development/delegation.json` gains `"mode": "owner"` under
  `development_approval`. The project list is unchanged and still scopes the delegated
  draft PR and merge (handoffs 29 and 31). Absent or `"delegated"` means what it meant
  before: the policy itself approves the plan, with no text.
- The intake still checks your number, the DM, the registered project and the request
  wording rule, and still publishes exactly the envelope built from your own message.
  For a listed project it files it at once and records
  `request-route-*.json` with schema `alfred.direct-request-route/1`
  (`"approval": "owner_plan_reply"`, your message's ID, the envelope digest). The host's
  poll accepts that route or the older confirmed one, and nothing else.
- When the CTO plan is ready, the intake sends the plan text instead of using the
  delegation. Its receipt binds the exact plan bytes, the request, your number, the DM
  and the 12-hour window. Your native in-thread "yes", not forwarded, single use, is
  recorded as the development decision; the grant is `photon_native_owner_reply`, as
  for every owner reply.
- This plan text is sent by iMessage even though the approval channel default is
  `alfred_os`, because a text is what the owner asked for. A stage request that names a
  channel explicitly still gets it. Projects outside the list follow the channel policy
  as before.
- Independent QA re-checks that evidence with its own copy of the rules: a plain yes
  counts only for a 12-hour plan receipt; a policy-decided grant is refused for a
  project in `"owner"` mode.
- The squad chat says "📨 Plan for … sent to Hayden; waiting for the yes to start." and,
  at the draft PR, "(Hayden approved it with the plan)".

## What changes (seven files; the intake restarts)

| Destination | Change |
| --- | --- |
| `/etc/alfred-development/delegation.json` | Adds `"mode": "owner"` to `development_approval` |
| `/opt/alfred-developer-v1/developer_v1/owner_grants.py` | The new mode; the plan text and its plain "yes"; draft PR and merge delegation keyed on the project list |
| `/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py` and `/usr/local/lib/alfred-v1.1/trusted_intake.py` | Listed requests are filed without a preview; the plan text uses the registry's project name |
| `/opt/alfred-independent-qa-v1/independent_qa/worker.py` | QA's own copy of the evidence and policy checks |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | The 12-hour text counts as open; the poll accepts the direct route |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/squads.py` | The squad chat's plan step |

## Preconditions
handoff.32 is installed (all 19 pins were read from the live host, read only, on
2026-10-19 and match main at cc6263f).

## Not in this release
- Hermes's own chat replies (for example "Filed — confirmed live") come from Hermes, not
  the pipeline; they are handled by the Hermes skill (alfred-team-skills PR #7). The
  intake now answers Hermes's `submit` with `"state": "submitted"` (filed) instead of
  `"awaiting_confirmation"` for listed projects.
- An unanswered plan text is not resent on its own after 12 hours; the task waits.

## Turning it off
Remove `"mode"` (or set it to `"delegated"`) in `/etc/alfred-development/delegation.json`
to have the policy approve plans again with the preview back; or remove a project from
the list to give it the full owner flow.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 33`. It restores every
file, including the previous policy; recorded approvals stay as evidence.
