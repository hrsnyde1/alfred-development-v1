# handoff.11 host procedure: plain-language texts and "yes" approvals

## Why
T-0009 reached the owner's publication approval (handoff.10), but the approval asked
for an in-thread reply of a phrase ending in a 32-character code within 5 minutes,
and it expired unanswered. The owner, who is the only person on this Photon line,
asked for the simplest possible flow in natural language without task numbers.

## Owner decision
Approve by replying "yes" in the approval message's own thread. Messages are plain
language. An expired approval can be resent on request.

## What changes (seven files, one restart)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-v1.1/trusted_intake.py` and `/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py` | The request preview reads "Here's what I'll hand to the development team for <project name>: … Is that right? Reply yes". It accepts "yes", "go ahead" or "start" (and the old "Yes, go ahead"). It passes the plain-language summary to the publication approval. |
| `/opt/alfred-developer-v1/developer_v1/publication_approval.py` | New approvals say "Ready to publish: <goal> (<project name>) … Reply yes to this message", valid 12 hours. Accepted replies: yes, y, approve, approved, publish, go ahead (the old exact phrase still works). Still required: the owner's number, the same DM, a direct in-thread reply to that exact message, not forwarded, single use. The branch, commit and plan digest stay in the receipt. Receipts issued before this release keep their 5-minute exact-phrase wording and verify unchanged. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | Passes the CTO plan's goal as the summary; reads the owner's resend records; reports whether an approval expired unanswered. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py` | An expired, unanswered approval is resent only after the owner ran `alfred-dev-ops resend <task>`, once per authorization, never on its own and never while the previous one is still open. |
| `/usr/local/lib/alfred-completion-v1/completion_integration/completion.py` | "All done with <project>. It's on GitHub as a draft for your review. Nothing is live yet." plus the link. "You merged it" still requires both GitHub readback and the owner's attestation. |
| `/usr/local/sbin/alfred-dev-ops` | Gains `resend <task>`. |

`alfred-development-intake.service` is restarted. Nothing else changes: delegation,
QA, Reviewer, the info-only findings rule, publication binding and the no-merge,
no-deploy rule are as in handoff.10.

## Not in this release
Hermes still replies to approval texts in its own words, because the Photon sidecar
delivers the owner's reply to Hermes too. That change belongs to the sidecar, whose
live copy is in Hermes's private folder, and is a separate step.

## Preconditions
handoff.10 is installed.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 11`.
