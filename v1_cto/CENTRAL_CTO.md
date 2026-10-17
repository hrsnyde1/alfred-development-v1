# Central Development CTO V1

One specialist plans filed work across projects bound by the protected Gateway registry. Its implementation is `cto.py`; the plan contract is `plan.schema.json`.

The specialist accepts only a `filed` record from the Gateway journal after matching its project, request ID, revision and task ID to exactly one canonical `proposed` Hermes spec. It reads only that registry project's repository, inventories files, and inspects bounded source and test excerpts. It identifies existing paths and asks for clarification when required source is absent. For T-0001 the registry points to a repository with no website; the plan must say so.

Its output is a candidate development plan and owner summary. It cannot change a task spec, choose a different repository, mark development approved, launch a Developer, execute tests, publish code, merge or deploy. The JSON schema permits only `awaiting_development_approval`. The plan file is stored under the protected Gateway directory and tied to the canonical spec SHA-256. A changed spec fails closed.

The owner message goes through `/send` on the existing authenticated Photon sidecar. The destination and token come from a protected operator configuration, never from the spec or model text. The send attempt is recorded before external I/O; an uncertain result is never retried automatically. An acknowledged outbound ID marks delivery only, never development approval.

## Separate development approval contract

The earlier direct reply to a Gateway preview authorizes **filing only**. This milestone records no development approval and exposes no `approve` command. A future trusted Developer gate must require a separate, positively authenticated owner approval record bound to the exact project, task ID, request ID, spec hash and plan hash; it must reject clarification-required or stale plans, ordinary unrelated conversation and delivery status as evidence of approval. That gate is outside this milestone.
