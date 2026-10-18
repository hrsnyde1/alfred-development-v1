# handoff.22 host procedure: handoff.20 after handoff.21

## Why
`alfred-dev-ops install 20` refused after handoff.21 was installed: handoff.20 pins
every other installed file, and handoff.21 had changed `pipeline.py` and
`real_worker.py` and added three files. Nothing was changed by the refusal.

## What changes
Exactly handoff.20's three files, byte for byte (see
`development_handoff20/HOST.md`): after a recorded Publisher `ERROR` the owner can run
`alfred-dev-ops republish project/task`, at most three times. Only the pins of the
files handoff.21 changed or added are updated. Nothing restarts.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 22`.
