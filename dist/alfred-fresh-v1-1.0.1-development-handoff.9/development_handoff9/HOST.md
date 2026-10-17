# handoff.9 host procedure

## Why
On 2026-10-17 two owner requests were refused with `explicit_authorized_project_required`
(Hermes log, 17:46:06 and 17:53:29 UTC). Each time, Hermes asked the owner a question
first, then submitted the owner's short answer ("2"), whose text names no project. The
intake takes the project only from the exact submitted owner text, so it refused.

## What changes (one source, two paths, one restart)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-v1.1/trusted_intake.py` (the running intake) | When the submitted owner turn names no project, the intake files the owner's own earlier request instead. That request must be in the same DM, within the existing 5-minute event lifetime, unfiled, and must name exactly one authorized project; requests naming different projects are refused as ambiguous. The answer turn is consumed and Hermes's status calls on it follow the original request. |
| `/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py` | The same source, kept identical as earlier releases do. |

The project still comes only from genuine owner text, and the preview still needs the
owner's native "Yes, go ahead". A self-contained request behaves exactly as before.
`alfred-development-intake.service` is restarted.

## Preconditions
handoff.8 is installed: its four files must have their installed-after bytes.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 9`.
