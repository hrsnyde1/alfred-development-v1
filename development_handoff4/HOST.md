# handoff.4 host procedure

## Why
- **T-0005 (Gate 6):** the Developer completed: one commit touching only
  `calculator.py` and `test_calculator.py`, and its grant was claimed and closed
  `completed`.
- **The QA failure:** QA preparation then ran `setfacl -R` on the lab repository
  to give the QA identity read access. The Evidence sandbox kept the checkout
  read-only (only `.git` was writable), so the command failed with EROFS.
- **No QA dispatch:** this happened in root's host code before any QA worker
  started (`qa-output` was never created). It wrote no failure evidence, so the
  uncertain `qa.attempt.json` blocks T-0005 and every later request.

## What changes (four files)

| Destination | Change |
| --- | --- |
| `/etc/systemd/system/alfred-development-evidence.service.d/40-fresh-v1.conf` | The whole lab repository is writable, instead of only its `.git` directory. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | An OS or subprocess fault in a stage's host preparation, before its worker starts, is recorded as `<stage>.failure.json` with phase `host_prepare`. A fault after dispatch stays uncertain. QA can run once under the T-0005 recovery decision, reusing the original root-built `qa-input`. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py` | The chain runs `qa-recovery-1` only when `qa.recovery.json` exists, and verifies the decision before and after it. Otherwise it is unchanged. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/qa_recovery.py` | New. A read-only `inspect` and a single append-only operator decision, for `dev-v1-accept/T-0005` only. |

The installer refuses unless all of these hold:
- PAUSE is present;
- the three existing destinations have exactly their handoff.3 bytes, and
  `qa_recovery.py` is absent;
- five unchanged runtime files match their pins;
- the Developer activation marker is unchanged.

It writes a root-only backup and rolls itself back on any fault. It performs no
service action.

## The T-0005 recovery decision
`inspect` refuses unless T-0005 is exactly the held original:
- the job identity and policy match;
- `qa.attempt.json` is the original uncertain attempt;
- `qa.result` and `qa.failure` are absent;
- the job directory contains exactly the twelve expected entries, with no
  `qa-output` (so QA was never dispatched);
- the Developer result is `ready_for_independent_qa`, and its grant claim is
  recorded `completed`;
- every root-built `qa-input` file is pinned by digest;
- the runtime files are pinned.

`authorize` requires PAUSE and the exact inspection digest. It writes
`qa.recovery.json` once and never renews it. The decision is valid for one hour
if unused.

After PAUSE is removed, the existing timer runs QA once as `qa-recovery-1`. If
that attempt is interrupted or ambiguous, it is never retried. Reviewer, the
publication approval and the draft PR then follow the normal chain. No new
development approval is needed. The original `qa.attempt.json`, `qa-input` and
every other record stay untouched.

## Rollback
Run in a root shell with PAUSE present:

```
install_patch.py rollback --backup <backup>
```

Then run `systemctl daemon-reload`. Rollback removes `qa_recovery.py`. An
existing `qa.recovery.json` then has no effect, because the handoff.3 chain
ignores it.
