# handoff.15 host procedure: the development team fixes its own work

## Why
The owner wants the team to keep fixing until the work is what was asked for:
"If it doesn't, it does a loop and continues to fix itself." Until now, one failed
QA or Reviewer verdict stopped a task for good (T-0010). The owner chose up to three
automatic fix rounds, then a plain-language text.

Testing also showed two latent faults this release fixes:
- QA required a developer to change **every** assigned file. A plain request such
  as "add dark mode" is assigned all of a project's allowed files (handoff.12) but
  changes only some, so it would always fail QA.
- The developer runner's claim scan read finished agents' reports as claims, so a
  task with two agents (or a fix round) crashed before starting the second.

## How a fix round works
1. QA fails, or the Reviewer does not approve: their findings are collected.
2. The same approved team runs again from the **same approved baseline**, scope and
   specialists. Each agent's instructions carry the findings and its files from the
   previous attempt (read safely: no symlinks, bounded size).
3. The round claims the original approval once (`execution-<ref>-r<n>.json`), only
   after the previous round's claim completed. At most three rounds.
4. QA and the Reviewer check the round exactly as they check round 0, so their
   checks are unchanged. The round that passes is the one published.
5. After the third failed round the owner gets one text ("I couldn't finish this
   one: ... Nothing was published.") and the task stops without blocking others.

Tasks planned before handoff.12 (no recorded specialists) keep the old behaviour.
Round 0 keeps every original file name, so tasks in progress continue unchanged.

## What changes (ten files, intake restart)

| Destination | Change |
| --- | --- |
| `fresh_v1/handoffs.py` | The fix loop; plain-language findings for developers. |
| `fresh_v1/host.py` | Fix-round developer request, round-specific QA/Reviewer folders, the owner text, safe reads of the previous attempt. Base: the handoff.14 host. |
| `fresh_v1/role.py` | `--round`: round-specific execution request and QA/Reviewer folders. Base: handoff.13 (team skills). |
| `developer_v1/pipeline.py`, `run_task.py` | Pass the round; its own final worktree and QA input; requests up to 64 KiB. Base: handoff.13 pipeline. |
| `developer_v1/owner_grants.py` | Per-round claims of the same approval, in order, at most three. |
| `developer_v1/execution.py` | Claim scan reads only claim records. |
| `independent_qa/worker.py` | A developer may change some of its assigned files (at least one, none outside). |
| intake (both paths) | `notify_owner_stuck`: the one plain-language text after the last round (root only). |

## Preconditions
handoff.13 (team skills) and handoff.14 are installed. The installer refuses before
any change otherwise.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 15`.
