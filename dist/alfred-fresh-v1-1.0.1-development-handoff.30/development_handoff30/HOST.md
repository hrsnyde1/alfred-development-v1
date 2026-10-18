# handoff.30 host procedure: QA accepts the delegated draft-PR policy

## Why
demo-site T-0007 (2026-10-18, after handoff.29) failed Independent QA with
`owner_approval: Grant issuance or completed execution evidence mismatch`, through all
three fix rounds. QA keeps its own copy of the delegation check, and it still required
`"publication_approval": "owner"`, which handoff.29 changed to `"delegated"`. The code
change itself was never the problem.

## What changes (one file, no restart)
`/opt/alfred-independent-qa-v1/independent_qa/worker.py` accepts `"owner"` or
`"delegated"`. Every other delegation check is unchanged. A new test reproduces T-0007:
it fails on the old worker and passes on this one.

## After installing
T-0007 stays stopped. Send the header request again.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 30`.
