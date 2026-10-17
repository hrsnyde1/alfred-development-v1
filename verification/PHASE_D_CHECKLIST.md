# V1 acceptance checklist: the evidence gates behind "95% confident"

The target is V1 as designed: one backend specialist, the template CTO and the
`dev-v1-accept` lab repository (`hrsnyde1/alfred-dev-v1-acceptance`). Work through
the gates in order and stop at the first failure. Each gate needs Hayden's own
authorization. Nothing here authorizes a gate.

| Gate | What | Who | Pass evidence |
| --- | --- | --- | --- |
| 1 | Offline tests on the host | alfred | `verification/run_host_tests.sh` ends `GATE 1 PASS` |
| 2 | Review and merge alfred-development-v1#1 (handoff.2) | Hayden | PR merged; the host checkout is at the merged revision |
| 3 | Phase A preparation | root | Prepare script ends `PHASE_A_PREPARED_HELD` |
| 4 | Phase B file installation | root | `INSTALLED_HELD`, then `HOST.md` §4 hash checks pass |
| 5 | Phase C restart (Intake + Photon + Hermes) | root | All three units active; an ordinary Alfred chat works |
| 6 | Live happy path (below) | Hayden's iPhone + root | `capture_evidence.py` reports `"overall": "PASS"` |
| 7 | Live refusals (below) | Hayden's iPhone (+ one other sender) | Each refused; no new task, grant or PR |
| 8 | Second task | Hayden's iPhone | A different request also reaches `PASS`, with no reset |

## Gate 1: run as alfred on the host

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
bash verification/run_host_tests.sh
```

Paste back the final summary lines. Do **not** paste the `results/` logs into a
public place.

## Gate 6: live happy path

Before you start:
- PAUSE stays until the operator removes it for this one task.
- Confirm no other conversation is in flight.
- Keep the request tiny and inside the allowed scope (`calculator.py`, `test_calculator.py`).

Example text to Alfred:

> For dev-v1-accept: add a multiply(a, b) helper to calculator.py that returns a times b,
> with a test in test_calculator.py.

Expected sequence on your phone (each item is one message; nothing should arrive twice):

1. **Preview** with a SHA-256 → reply *in thread*: `Yes, go ahead` (within 5 minutes).
2. **CTO plan** ending with an exact approval phrase → reply *in thread* with that exact phrase.
3. *(Developer, QA and Reviewer run; no messages.)*
4. **Publication approval** with a second exact phrase → reply *in thread* with that phrase.
5. **Completion** with the draft PR link.

After each message, as root (read-only):

```bash
/usr/bin/python3 -I -B verification/capture_evidence.py --task T-NNNN
```

How to read the result:
- `IN_PROGRESS` is normal while waiting on an approval or the next timer tick.
- `HELD` means a stage started and has no result. Keep PAUSE in place and paste the report. Never delete files to retry.
- `FAIL` names the gate.

Final pass criteria:
- every gate is `PASS`;
- the PR is a **draft** on `hrsnyde1/alfred-dev-v1-acceptance`, its diff touches only scoped files, and its tests pass;
- you received exactly one of each message.

Then you merge or decline it. Nothing in the pipeline merges.

## Gate 7: live refusals (each must change nothing)

Run one at a time, each against a fresh request where applicable. After each, confirm
there is no new filed task, grant or PR, and that the next valid request still works.

1. A message from a phone number other than yours asking for a change.
2. Replying to the preview with "yes" as a **new message**, not a threaded reply.
3. Replying in thread after **more than 5 minutes**.
4. **Forwarding** the approval message instead of replying.
5. Asking for a project that is not registered (for example, "for project nonexistent").
6. Replying to the *publication* approval with the *development* phrase.

## Gate 8: repeatability

Send a second, different tiny request (for example, a `divide` helper that refuses division by
zero). It must reach `PASS` without resetting delivery state or reusing a grant. T-0003 stays held
and untouched throughout.

## Still open after all gates

These are known limits from the existing reviews. They do not block V1 acceptance, but they mean
"95%" is about V1 as designed, not every failure mode:

- live Photon SDK redelivery after an outage (H4);
- acceptance of the operational logs (M2);
- the broader Hermes Photon regression suite;
- variation in model output between runs.

Gate 7 covers the refusal paths tested in staging but not exhaustively.
