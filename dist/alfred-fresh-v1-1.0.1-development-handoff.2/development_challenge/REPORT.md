# Development approval handoff correction — staging

## Scope and readiness

The functional correction is prepared for future fresh tasks. **Installation and
activation have not been performed.** T-0003's original challenge remains held;
its historical transport exception and delivery outcome remain unknown.

The confirmed contract defects are independently reproducible: a normal delayed
Photon acknowledgement can outlive Intake's 2-second send timeout; extending that
alone still leaves 5/10-second root clients and a 2.5-second native observer wait.
The issuer previously had no durable send intent, and its ACK and pending index
were separate non-atomic writes. The existing poll also returned the oldest held
challenge on every tick, starving later requests. These findings do not identify
the exact historical T-0003 exception.

## Minimum correction

| Existing component/source | Correction |
| --- | --- |
| Trusted Intake | Development-only 30-second HTTP budget, including a timer that shuts down a stalled socket; explicit pre-connect and bounded, redacted outcome classification. Request-preview/publication send budgets remain 2 seconds. Prior staged failure diagnostics are included. |
| DevelopmentGrantIssuer | Fsync an exclusive task send intent before transmission; record uncertain/refused outcomes append-only; atomically publish a genuine native-ID receipt and pending index. Never resend an attempted task. |
| Native owner decision | A receipt with a matching new send-intent hash can index an ACK-only challenge after interruption. All original owner, DM, timestamp, native threading, phrase, replay and one-use grant checks still apply. No historical receipt without the new intent is adopted. |
| Root clients | Existing automatic host and administrator CLI wait 40 seconds, without retries. |
| Existing Photon observer | Its existing Unix observation waits 45 seconds, beyond the development send budget. SDK connection, `/send` implementation, authenticated sender and native IDs are unchanged. |
| Existing Fresh poll | Skip development-challenge attempts lacking a result, without executing or changing them; process a later genuinely filed task. If only held tasks exist, report the existing reconciliation hold. |

The existing Linux `renameat2(RENAME_NOREPLACE)` primitive is shared between
Intake's existing Gateway inbox publisher and private development ACK/index
publication. Its implementation is unchanged; it now resides in owner_grants.py.
Files are complete and fsynced before no-replace publication, then the directory
is fsynced. No partial ACK/index becomes an approval source. A hard interruption
may leave a private temporary file, which is never an approval receipt and is
not automatically cleaned up or replayed.

Only five runtime source files change, plus the Developer inventory. The Intake
source is installed in its two existing locations, making **seven destinations**.
No new service, Gateway, SDK connection, credential, database, policy or worker.
Developer, QA, Reviewer, Publisher and completion execution are untouched.

## Delivery and acknowledgement semantics

| Evidence | Meaning / action |
| --- | --- |
| Canonical validation rejects before issuing | Proven pre-send failure for that invocation; no send intent or approval is produced. |
| Intent persistence fails, explicit TCP connect fails before POST, or pinned Photon handler returns local 400/401/405 | Proven pre-send refusal, reported as `not_attempted`. If an intent exists it is retained. No automatic retry. |
| Photon returns generic 500 / provider refusal classification | Record the allowlisted reason, but retain `uncertain`. Photon's `error_class` is heuristic and does not certify absence of side effects. `retryable` never authorizes a retry. |
| Timeout/reset/missing or malformed native ID | `uncertain`; retain the original intent and outcome. No receipt/grant is invented and no new process resends. |
| Valid native ID and fully committed receipt | Confirmed **Photon send acknowledgement**, not proof of owner-device delivery or reading. The immutable receipt pins intent, plan, owner, DM, text digest and native ID. |
| Genuine authenticated owner directly replies to that native ID with the exact phrase in time | Existing independent decision evidence and a one-use development grant are issued normally. |
| Process interruption before durable ACK | Intent alone means uncertain, regardless of whether transmission occurred. Never resend. |
| Process interruption after durable ACK but before pending indexing | Index the genuine receipt in memory when a real native reply arrives. No new message or synthetic owner event. |
| Process interruption after Intake ACK but before root handoff result | The existing root attempt stays held. There is no automatic replay or fabricated handoff result. A later operator reconciliation requires actual receipt evidence. |

The approval lifetime is pinned to dispatch time, not delayed ACK/restart time.
This admits a genuine reply queued while ACK is returning and never extends the
five-minute authorization window. Local waits are finite and transport failure
cannot create owner approval.

The task slot hashes **project and task**, not mutable plan/scope/DM, so changing
those values cannot bypass one-use delivery. It is never cleared by expiration,
revocation, a restart, or rollback. Existing pre-intent historical grants still
require the original explicit root revocation before any new challenge; tests
use the pinned historical issuer to verify that path. A modern send remains
one-use even after revocation.

## Preserved authorization boundaries

- Root `SO_PEERCRED` staging; configured trusted Photon observation UID.
- Registry authorization/company validation and exact canonical task/plan binding.
- Configured owner, same DM, genuine direct native reply, no forwarding, freshness,
  exact phrase, immutable decision/issuance hashes and event replay rejection.
- Existing protected Intake evidence store owner and 0600 records; no broader
  filesystem permissions or credentials.
- Existing one-use Developer grants; both owner approvals remain separate.
- No automatic merge, deployment, publication, notification or worker retry.

## T-0003 and historical evidence

No installed source, task evidence, CTO plan, route, attempt, approval or worktree
was changed. Readable preservation bindings:

- Plan: `e5b58519eb9943c7b9d093b19880c4a0c881dc5a2491c6e1c68b70ff10f032d6`.
- Context: `bda345a14ec110cf5b3118d7289204c304ba13795f9c9677351aa940d0ab198e`.
- Baseline: `596d91daf3311ad3aa0ee42e7220f699f58daf59`.
- Scope: `calculator.py`, `test_calculator.py`.
- Original challenge attempt: 77 bytes, mtime_ns `1792187986367039147`.
- Original planning attempt: 60 bytes, mtime_ns `1792181749323796085`.

The attempt bytes are root-private and were not independently readable in this
session. Operator-supplied `uncertain_until_result` is retained as such; root must
checksum the actual protected evidence before/after installation. No send intent,
receipt, result or new approval is backfilled for T-0003. The poll's skip occurs
without calling its plan-recovery verifier or any task action. New host code does
not rewrite the original planning-recovery runtime pins or decision. Any later
T-0003 recovery requires separate review; this overlay grants none.

## Verification and deployment limits

See `TESTS.md` and `staging-tests.xml`. Tests use temporary repositories and mocked
Photon, SDK events and model/worker boundaries. No specialist execution, model
API, live send, remote Git operation, service control or production mutation was
performed. The seven-file transaction is tested at every write position and on
explicit repeatable rollback; activation, private policy, credentials, QA/Reviewer,
Publisher, notification and T-0001/T-0002/T-0003 fixture evidence remain unchanged.

The pinned corrective archive is a standalone overlay over the inspected
V1.0.1 installation with planning fix/recovery. Do **not** install the earlier
diagnostics-only archive first or use the legacy full-release builder for this
overlay. Unknown/drifted host hashes must fail preflight and require review.

Future activation requires separate operator authorization, PAUSE and idle
workers, then restarting the existing Intake and Photon services to load their
changed code. **Hermes has Requires=alfred-photon.service, so the Photon restart
also propagates a Hermes restart under the existing systemd contract.** That
maintenance impact must be separately authorized; do not bypass the dependency
or claim this is an Intake-only activation. No service restart has occurred.
Gateway/Evidence use their existing timer and load host code on their next
invocation. Keep PAUSE after installation and verification. A genuine future owner
request/test is a separate operator decision and is not executed by the installer.
