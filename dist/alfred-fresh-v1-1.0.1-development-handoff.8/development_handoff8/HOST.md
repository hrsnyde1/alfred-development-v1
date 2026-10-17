# handoff.8 host procedure

## Why
The owner asked Alfred to approve development on their behalf, for registered projects
only, while keeping every publication approval and asking about missing details as
before. handoff.8 adds that as an owner-written delegation, never as a simulated
owner reply.

## What changes (four files, one restart)

| Destination | Change |
| --- | --- |
| `/opt/alfred-developer-v1/developer_v1/owner_grants.py` | When `/etc/alfred-development/delegation.json` (root-owned, not group/other writable) lists the project, the intake issues a grant with `source: delegated_owner_policy` and a `delegation-<ref>.json` record. It sends no text and writes no `challenge-`/`decision-` file. The runner's verifier accepts that evidence only while the policy still lists the project. |
| `/opt/alfred-developer-v1/developer_v1/pipeline.py` | Passes an optional policy path through (used by tests; the host uses the default). |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | The QA input copies `delegation-` evidence for a delegated grant, otherwise `challenge-`/`decision-` exactly as before. Base: the handoff.7 host. |
| `/opt/alfred-independent-qa-v1/independent_qa/worker.py` | Independent QA verifies either the native-reply chain (unchanged checks) or the delegation chain. |

`alfred-development-intake.service` is restarted so the intake loads the new module.
With no policy file, behaviour is exactly handoff.7. Publication approval is unchanged,
and the policy schema refuses anything except `"publication_approval": "owner"`.

The same release carries `ops/alfred_dev_ops.py`, the restricted root operations helper
(`status`, `pause`, `resume`, `install N`, `rollback N`). It executes only code from
inside a hash-verified release, refuses unless PAUSE is set, restarts only the intake,
and logs every operation to `/var/log/alfred-dev-ops.jsonl`. `install` asks you to type
the start of the archive SHA-256 from Claude's report, without displaying it first.

## Preconditions
handoff.7 is installed: `host.py` must have exactly its handoff.7 bytes, or the
installer refuses before any change.

## Rollback
`sudo alfred-dev-ops rollback 8` with PAUSE set. To stop delegation without a rollback,
delete `/etc/alfred-development/delegation.json` or remove the project from it. Grants
that have not yet run are refused from that moment.
