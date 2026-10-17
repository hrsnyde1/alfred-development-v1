# handoff.6 host procedure

## Why
- **T-0007 (Gate 6):** the Developer claimed its grant and called Codex, but it
  was refused with "model produced ambiguous response". The grant closed
  `failed`, and there were no edits.
- **The cause:** a read-only reproduction with the same objective, baseline
  files and model showed Codex sending **two** agent messages. The first was a
  progress note, `{"status": ...}`; the second was the schema-bound edits.
- **The broker:** the Developer's broker required exactly one message.
  T-0005 and T-0006 happened to get one, so this fails intermittently.
- **The Reviewer:** it has the same rule (`len(answers) == 1`), so it would
  fail the same way. QA already uses the last message.

## What changes (four files)

| Destination | Change |
| --- | --- |
| `/opt/alfred-developer-v1/developer_v1/real_worker.py` | Accepts exactly one message carrying the edit contract (`edits` + `summary`), which must be the final message. Progress notes are ignored. Two contract-shaped messages are still ambiguous, and every later edit and scope check is unchanged. |
| `/opt/alfred-developer-v1/developer_v1/release.sha256` | The Developer inventory, with only the `real_worker.py` line changed. |
| `/opt/alfred-reviewer-v1/independent_reviewer/worker.py` | The same rule for the decision object (`decision`, `findings`, `coverage`). It is Reviewer release `host-candidate-v5`, pin `62481e52…`. |
| `/opt/alfred-reviewer-v1/independent_reviewer/release.sha256` | The v5 Reviewer manifest, with only the `worker.py` line changed from v4. |

The installer refuses unless all of these hold:
- PAUSE is present;
- the four destinations have exactly their installed bytes;
- `role.py`, `host.py`, `handoffs.py` and `upgrade.py` match handoff.5;
- **every other file listed in both installed inventories** matches its
  recorded digest;
- each new inventory differs from the old one only in its worker line, and
  that line matches the new worker.

It keeps each file's owner and mode, writes a root-only backup, and rolls
itself back on any fault. The workers are started anew for each stage, so no
reload or restart is needed.

## After install
- **Held tasks:** T-0003 through T-0007 stay held and untouched. The poll skips
  T-0004 through T-0007 because their failures are recorded.
- **Next run:** Gate 6 is retried with a fresh request, T-0008.

## Rollback
Run in a root shell with PAUSE present:

```
install_patch.py rollback --backup <backup>
```
