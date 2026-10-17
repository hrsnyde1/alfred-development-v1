# Task A authenticated event-to-turn identity contract

**Status: proposed contract, not satisfied by installed Hermes or the current
staging patch.** This is a source investigation; no installed source was
modified. Paths below are relative to `/home/alfred/.hermes/hermes-agent/`.
The exact source inventory and SHA-256 values are in
`AFFECTED_UPSTREAM_SOURCE_PATHS.md`.

## Observed processing path

| Step | Installed source evidence | Identity consequence |
| --- | --- | --- |
| SDK reception | `plugins/platforms/photon/sidecar/index.mjs:701-715` iterates `app.messages`, normalizes `message.id`, `sender.id`, space and text at `:642-659`, then forwards JSON. | The installed sidecar supplies no durable per-turn attestation and marks read after delivery to the adapter. The proposed protected front can authenticate the sidecar peer and journal the event. |
| Adapter admission | `plugins/platforms/photon/adapter.py:787-800,816-858,921` creates a `MessageEvent` whose `raw_message` contains the sidecar event, then calls `handle_message`. | `raw_message`, `message_id` and `source` are mutable Hermes process data. They are useful correlation fields, not independent proof at the protected boundary. |
| Queue and dispatch | `gateway/platforms/base.py:4038-4078,4080-4188` starts a task or sends an active-session event through inline, debounce or pending paths. `:1803-1849` can append text to a pending event. `gateway/run_busy.py:375-425` has a bounded FIFO for some busy modes, but its photo merge and other base paths still exist. | Same-chat events may share a session key, merge text, be replaced, be cancelled, or enter distinct tasks. A chat-level or task-inheritance binding is not an event binding. |
| Agent turn | `gateway/run_inbound.py:1285-1368` claims a session and `gateway/run_turn.py:2144-2198,4265-4346` prepares the turn, tools and agent worker. `gateway/turn_context.py:14-57` carries session, generation and inbound message ID but no protected event/job identity. | Session ID, run generation and message ID alone do not attest the original authenticated event. Tool work may outlive or be redirected from its opening event. |
| In-band follow-up | `gateway/run_turn.py:4351-4359,3811-3945` drains a pending event by recursively awaiting `_run_agent` **inside the opening processing task**. | The v0.1.4 adapter's `_process_message_background` rebinds a new drain task, but this recursive path inherits the first event's `ContextVar`. The outer base method can later deliver the nested response using the opening `MessageEvent`. |
| Final and inline send | `gateway/platforms/base.py:3602-3617,4562-4637` sends inline bypass replies or the normal final response. `plugins/platforms/photon/adapter.py:1461-1539` posts to its sidecar. | A delayed or recursive response can be generated after the opening event has ceased to be the current turn. Every outbound path needs an explicit result identity. |
| Tool send | `tools/send_message_tool.py:35-42,267-277,524-558,689-760` routes model-selected targets through a worker/loop bridge. `gateway/run.py:4245-4249` and `tools/thread_context.py:36-64` copy context variables across threads. | Ambient context can be inherited, absent or stale. A model-selected destination or handle cannot prove the originating turn; standalone sends and tool sends need explicit policy. |

The current staging [patch generator](make_photon_patch.py) binds a handle in
`_on_inbound_line` and at a new `_process_message_background` task. Focused
test `test_installed_in_band_followup_inherits_first_turn_binding` executes
the resulting stale-context behavior; `test_known_handle_substitution_is_currently_accepted_at_restricted_boundary`
shows that a caller with two live handles can send text for event 2 under
event 1's handle. These are **observed gaps**, not accepted behavior.

## Required identity and state contract

1. The protected Photon owner authenticates and durably records an event
   before issuing a job. Its immutable key includes provider/project,
   platform, original `sender.id`, conversation ID and provider message ID;
   record the original payload digest and, when available, provider sequence.
   Model arguments, phone/space fallback, Company Mastermind text and Hermes
   metadata never create or amend this key.
2. A trusted coordinator assigns a unique `job_id` and a monotonic job
   generation to exactly one recorded event. A multi-event turn would require
   an explicit ordered set of event IDs and a separately reviewed policy;
   Task A should use one event per job. The coordinator durably records
   `admitted → running → output-ready → delivery-reserved → delivered/uncertain`
   or `cancelled/expired`. Every transition checks the same original event,
   conversation, authorized sender, static `dev-001` scope and generation.
3. Hermes receives an immutable job envelope. Its queue must preserve every
   protected Photon event as a separate FIFO item for a conversation. Full
   queue, debounce, merge, replacement, cancellation, restart and recovery
   paths must either keep the exact job or return an explicit refusal to the
   coordinator. They may never silently absorb an event into another job.
4. Hermes `TurnContext` and the result type must carry `job_id`, authenticated
   event ID, conversation, company/project scope and generation **as typed
   data**, across the initial task, in-band recursive follow-up, inline bypass,
   agent worker, tool callbacks, streaming, final send, error notification and
   queued retry. The final send must use the identity attached to the result's
   own turn, not the opening `MessageEvent` in an outer stack frame. A naked
   `str` response cannot authorize delivery.
5. The protected boundary independently checks a live job in its own ledger,
   exact recipient/conversation, generation, state, deadline and one-shot
   delivery reservation. It derives the outbound destination from the
   authenticated event. A missing, stale, conflicting, cancelled, substituted
   or already reserved job fails closed. Unknown side effects after an
   outbound timeout remain `uncertain`; no blind replay. `/submit` uses only
   the canonical Gateway envelope bound to that same event and static lab
   project. The Gateway alone files a proposed task and grants no execution.
6. Tool sends, standalone Photon senders, cron/background sends and generic
   adapter `send` must be unavailable for a Task A Photon job unless they
   carry a trusted job/result identity and pass the same protected check.
   Model-selected paths, recipients, handles and company identifiers are
   never authority. Attachment delivery remains disabled pending separate
   compatibility review.

## Trust-boundary limit

A `job_id`, handle, token, `ContextVar`, signed blob or per-turn field held in
the same untrusted Hermes process remains a transferable capability. Hermes
can submit event B's result under event A's known capability. `SO_PEERCRED`
proves the caller's process identity, not which model turn authored its text.
The protected process cannot infer semantic provenance from arbitrary reply
content.

Full protection against compromised Hermes therefore needs an **architectural
choice**: a trusted turn coordinator/executor that observes and attests the
actual job/result edge, or OS-isolated one-job workers whose identity and
single-job channel are enforced outside Hermes and whose output is accepted
only from that worker. Both require upstream queue/result interfaces and
separate OS acceptance. If the threat model instead trusts the Hermes process
and protects only against prompt-supplied arguments, that narrower guarantee
must be explicitly approved; it is not the current untrusted-Hermes boundary.
Until then, automatic text replies and Gateway filing for real Photon events
must remain disabled.

## Proposed upstream changes and acceptance tests

- Add a protected-job field or typed envelope to
  `gateway/platforms/event.py`, `gateway/turn_context.py`, the Photon adapter,
  and the Gateway queue/runner paths listed above. Change recursive follow-up
  to return an identity-bearing result and make base delivery consume that
  result. Exempt protected Photon jobs from text/photo merging or implement an
  audited per-event FIFO with explicit backpressure and recovery.
- Route every send and tool action through one trusted coordinator check;
  disable standalone Photon send and any bypass without a job identity. Keep
  static requester binding and `dev-001` Gateway authority unchanged.
- Test overlapping same-chat events, multi-event FIFO, delayed tools,
  in-band recursive follow-up, inline commands, streaming, cancellation,
  restart, context loss, event-handle swap, recipient swap, replay and
  cross-company laundering. Assert that each result reaches only its exact
  original event or is explicitly held/refused. Repeat with actual patched
  Hermes and separate OS identities before acceptance.

**Feasibility and next step:** typed job propagation and queue preservation
are implementable as staging upstream patches. They do not independently
attest a result from a compromised shared Hermes process. Record an
architecture decision choosing a protected turn coordinator with an
observable job/result edge or one-job OS-isolated workers, and specify whether
any narrower Hermes-trust model is acceptable. Implement that decision in
staging before enabling real Photon replies or Gateway filing.
