# handoff.29 host procedure: one "yes" takes a request all the way to a draft PR

## Why
Owner's instruction, 2026-10-18: "for my registered projects, my one yes to the request
preview also approves opening the draft PR. No second Ready to publish text. Merging
stays my manual step." Also: understand requests in the owner's own words, and end
with one text saying it's ready to push.

## The texts the owner gets from the pipeline after this

1. **The request preview** (unchanged): what goes to the team, the goal, what changes.
   Reply "yes" to start.
2. **All done**: "All done with demo-site. Built, tested and reviewed. It's ready for you
   to push." plus the draft PR link.

For a project listed in `/etc/alfred-development/delegation.json`, there is no "Ready to
publish" text in between. The draft PR approval is recorded as **delegated**: its
record says so, and it never claims an owner reply. It is checked against the policy
again right before publishing. Merging, and anything that makes a change live, stays
the owner's.

## Wording
A request that names a registered project ("the demo site") is a development request
in any wording, unless it is a plain question ("How is the demo site doing?"). Without a
project name, any common action ("make", "set", "I want…", "can you…", "get rid of"…)
together with a software word ("page", "button", "footer", "site"…) counts. Everyday
chat ("Remind me to call mom") stays chat. Every request still goes through the
preview and the owner's "yes" before anything runs.

## What changes (seven files; the intake restarts)

| Destination | Change |
| --- | --- |
| `/etc/alfred-development/delegation.json` | `"publication_approval": "delegated"` (the project list is unchanged) |
| `/opt/alfred-developer-v1/developer_v1/owner_grants.py` | Accepts `"owner"` or `"delegated"` |
| `/opt/alfred-developer-v1/developer_v1/publication_approval.py` | Delegated draft-PR approval, rechecked before publishing |
| `/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py` and `/usr/local/lib/alfred-v1.1/trusted_intake.py` | Reads the policy; broader wording |
| `/usr/local/lib/alfred-completion-v1/completion_integration/completion.py` | "Ready for you to push" |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/squads.py` | The squad chat says the draft PR is opening |

## Turning it off
To go back to a second "yes" before each draft PR without a rollback: set
`"publication_approval": "owner"` in `/etc/alfred-development/delegation.json`. It applies
to the next draft PR, including one already approved but not yet published.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 29`.
