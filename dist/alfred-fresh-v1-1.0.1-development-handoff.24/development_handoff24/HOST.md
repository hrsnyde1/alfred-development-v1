# handoff.24 host procedure: the owner confirms a completion text they received

## Why
demo-site T-0003 published its draft PR and the owner received its "All done with
demo-site…" text, but the sidecar's acknowledgement arrived after the old two-second
bound (handoff.23 fixes that for later sends). So
`/home/alfred/Alfred/completion-delivery/delivery.json` keeps the record `uncertain` with
`receipt_id: null`, the host recorded `completion.failure.json` (`python/python_failed`),
and the poll holds the task for good. Nothing can complete it today: `once()` refuses the
existing `completion.attempt.json`, and the tracker answers `uncertain` without sending,
by design, because an uncertain record must never be resent.

`completion_integration/DELIVERY_RECONCILIATION.md` sets the rule: the owner's
confirmation and the transport state are separate facts. Keep the uncertain record as it
is and record the confirmation separately. This release makes that a restricted owner
operation the poll accepts.

## What changes
Two files; nothing restarts.

- `/usr/local/sbin/alfred-dev-ops` gains `confirm-delivered project/task`. The owner types
  `RECEIVED` to confirm. It refuses unless all of these hold:
  - the task directory exists, is not complete, and has no confirmation yet;
  - `completion.attempt.json` exists, the only failure file (if any) is
    `completion.failure.json`, and any `completion.result.json` says `uncertain`;
  - the task's last Publisher result is `PUBLISHED_DRAFT`;
  - under the tracker's own lock (refused while a send holds it), `delivery.json` is
    protected and alfred-owned, and holds exactly one record for the task. That record
    is `uncertain` with no receipt, and its identity is the task's draft PR URL and the
    final revision recorded in `completion/config.json`.

  It then writes two root-owned 0600 files into the task directory:
  `completion-confirmed.delivery.json` (the bytes of `delivery.json`) and
  `completion-confirmed.json` (`alfred.completion-owner-confirmed/1`: record key,
  identity, text digest, `transport_state: uncertain`, `receipt_id: null`, the snapshot's
  SHA-256, `resend_permitted: false`, who and when). Like every operation, it appends to
  `/var/log/alfred-dev-ops.jsonl`.
- `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py`: before skipping a held task, the poll
  checks for that confirmation. If the record, its snapshot and the attempt all match, it
  writes `complete.json` with `"notification": "owner_confirmed_received"`. A record that
  does not match holds the poll ("completion delivery confirmation invalid").

Not changed: `delivery.json`, `delivery.lock`, the attempt and failure files, and the
completion runtime and tracker. The operation never sends or resends a Photon message
and never makes up a receipt. The uncertain record stays the duplicate guard.

## Known cases
- demo-site/T-0003: run `sudo alfred-dev-ops confirm-delivered demo-site/T-0003` after the
  install. The next poll marks it complete.
- dev-v1-accept/T-0002: this is the historical task from before fresh V1. It has no task
  directory under `/var/lib/alfred-v1-handoffs`, so the poll never ran or held it.
  `confirm-delivered` refuses it as "not found". Its owner confirmation was already
  recorded on 2026-10-16 in `/etc/alfred-completion-v1/reconciliation-T-0002/`, per
  DELIVERY_RECONCILIATION.md. Nothing more is needed.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 24`. Confirmation files
already written stay. The rolled-back host.py ignores them.
