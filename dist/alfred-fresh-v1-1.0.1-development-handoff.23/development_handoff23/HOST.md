# handoff.23 host procedure: a slow Photon acknowledgement no longer fails completion

## Why
demo-site T-0003 was held as `completion: python/python_failed` although the owner
received its "All done with demo-site…" text. `/home/alfred/Alfred/completion-delivery/delivery.json`
kept the record `uncertain` with `receipt_id: null`. dev-v1-accept T-0002 shows the same
symptom (its timing was not recorded); dev-v1-accept T-0009 was `sent`.

Evidence (2026-10-18, read-only):

| Time (UTC) | Event |
| --- | --- |
| 17:57:38.458 | `completion.attempt.json` written; worker starts as `alfred` |
| 17:57:39.442 | `delivery.json` written: the pre-send `uncertain` record |
| 17:57:39.444 | completion-delivery directory last modified |
| 17:57:41.512 | `completion.failure.json` written (`python/python_failed`) |

- The worker failed 2.07 s after the pre-send write. `PhotonSender` used one
  `timeout=2` for the whole loopback request, so the read of the sidecar's answer
  timed out. `TimeoutError` has no errno, which gives exactly `python_failed`.
- No confirmation write was attempted: a `_write` creates and renames a temporary file
  in that directory, which would have moved its mtime past 17:57:39.444. So the
  failure was inside `send()`, not tracking persistence.
- The sidecar answers `/send` only after Photon's remote `space.send()` returns. The text
  had already gone out; only the acknowledgement was late. T-0009's whole stage took
  1.3 s, inside the bound.
- The sandbox is not involved: the fresh-v1 drop-in allows `AF_INET`, and the text was
  sent. The GitHub checks were not involved: `prepare` reruns cleanly.
- `tests/test_completion_ack_timeout.py` reproduces it against a mock loopback sidecar
  that answers after 2.5 s. With the old `runtime.py` it fails with `TimeoutError`;
  with this release it records `sent` with the receipt.

## What changes
One file, `/usr/local/lib/alfred-completion-v1/completion_integration/runtime.py`:
connecting to the sidecar keeps the two-second bound (a refused or slow connect sends
nothing). The wait for the acknowledgement is now up to 30 seconds, well inside the
worker's own 1200 s limit. An answer slower than that still leaves the record
`uncertain` and is never resent. No retries were added. Nothing restarts.

## Not changed
Existing `uncertain` records for demo-site/T-0003 and dev-v1-accept/T-0002 stay as
they are, and those tasks stay held. Their draft PRs are published; reconciling a
confirmed-received completion is a separate owner operation (see
`completion_integration/DELIVERY_RECONCILIATION.md`).

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 23`.
