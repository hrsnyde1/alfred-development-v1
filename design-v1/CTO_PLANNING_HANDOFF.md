# Future Gateway-filed CTO planning handoff

**Future stage only.** This is a contract for a separately authorized
scheduler; no scheduler, queue, Kanban card, tool or execution grant is created
by Task A. It does not revise accepted ADR 0008 or proposed ADR 0011.

## Trigger and job

Only a trusted Gateway-owned observer may read the protected journal and
canonical task spec. It recognizes a `filed` record whose request UUID,
revision, project and task ID agree with the canonical spec. An unsigned
requester outbox event, broker submission receipt, Hermes message, Company
Mastermind recommendation or model-generated `filed` text is not a trigger.
It deduplicates on `(project, task_id, request_id, spec_hash)` and records a
bounded planning-job ledger. Missing, conflicting, stale, revoked, PAUSE/STOP
or non-`proposed` state is `unavailable` and launches nothing.

The job contains only a bounded, read-only snapshot of the canonical proposed
spec, its protected project ID and provenance label. It conveys no Gateway
journal path, approval nonce, credentials, publisher token or mutable
registry. The CTO session runs in a separately reviewed read-only environment
without shell, write, publisher or protected Gateway tools. The existing CTO
role may produce a plan, open questions, risk assessment and suggested
specialist roster. A trusted validator treats this as data and stores a
bounded candidate artifact outside the canonical spec for human review; it
cannot set `ready`, approve, create an execution grant,
schedule a Builder, modify protected paths or publish code. A changed spec
hash invalidates the plan association.

## Later autonomy gates

1. A human approves the final spec and plan under the existing hash-bound,
   revocable Gateway approval process. The owner separately authorizes any
   protected execution and any real headless workflow phase.
2. A trusted orchestrator, **not the CTO model**, re-derives eligibility from
   protected registry, spec, approval, PAUSE/STOP, scope, role registry,
   budget and OS confinement before each stage. Approved specialists receive
   only their scoped job. QA and Reviewer remain independent; an applicable
   Security Reviewer needs its own separately accepted role policy.
3. GitHub publication remains under a separate human authorization until a
   reviewed publisher design is explicitly approved. Human merge and
   deployment decisions remain separate. No status projection or Kanban view
   grants any of these permissions.

This handoff uses one existing CTO planning session only when a real filed
task needs planning. Identity, trigger, deduplication, safety checks and
status are deterministic code; no extra LLM security verifier or additional
agent is introduced. Any future scheduler must have its own ADR/spec,
budget, isolation review, test fixtures and explicit activation approval.
