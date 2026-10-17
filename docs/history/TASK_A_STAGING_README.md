# Task A staging — v0.1.4 corrective work incomplete

The v0.1.3 release remains immutable. Current v0.1.4 changes are workspace
work in progress, with no release archive. Real Photon events are held out of
Hermes and Gateway filing because installed Spectrum source does not establish
durable redelivery. Exact event-to-turn authorization and the complete Hermes
regression environment remain blockers. See `V014_CORRECTIVE_STATUS.md`.

This tree is **planning, proposed code and isolated tests only**. It is not an installed service, a Gateway task, an approval, or an execution grant. Nothing here is called by production Hermes, Photon or the real Development Gateway. Task B remains blocked until formal ADR recording, separate Task A protected-path authorization, implementation in an approved test environment, and independent security acceptance.

## Inventory

| Component | Staged artifact | Current limit |
| --- | --- | --- |
| Conditional ADR record | `APPROVAL_RECORD_CANDIDATE.json`, generated `adr-0003-conditional-photon-front.proposed.patch` | Formal authoritative ADR recording is pending. Patch is checked against pinned source and never applied here. |
| Dedicated identities, system units, DAC/ACL | `templates/systemd/`, `templates/permissions/paths.json` | Candidates only; UID/group creation, mounts and real systemd confinement untested. |
| Photon split and event binding | `task_a/broker.py`, `task_a/photon_front.py`, `task_a/durable.py`, `task_a/service.py`, `patches/photon-secure-front.proposed.patch` | One proposed protected SDK sidecar, durable event feed and restricted Hermes socket; bounded handle-bound text replies and lab envelope submission. Synthetic tests pass; real SDK, multi-UID socket and patched-adapter compatibility are **not verified**. |
| Lab inbox writer | `task_a/transport.py` | Marked temporary roots in tests; the protected service has a fixed candidate lab path. Existing `alfred.devreq/1` JSON, write-ahead ledger, no-clobber publication, exact retry and conflict refusal. No protected path was written in this staging run. |
| Gateway/Hermes source copy prototype | `task_a/promote.py`, `templates/registry/projects.yaml` | Clean full commit + tracked file hashes and versioned selector in a disposable root. The human has not yet pinned a Gateway lab commit. Trusted remote provenance, dependency/launcher packaging, root ownership and production rollback require operator review. |
| Evidence Bridge | `task_a/evidence.py`, pinned v0.2.1 SHA-256 manifest | Reads installed plugin for verification and copies only into an isolated root. No live report ownership or permission changes. UID-31012 live reader compatibility is unverified. |
| Transaction/recovery/rollback | `task_a/release.py`, `task_a/release_cli.py` | Checks payload/baseline hashes, preserves backups, refuses interrupted state, recovers/rolls back in marked temporary roots. It neither installs accounts/ACLs/units nor restarts services. |
| Tests and evidence | `tests/`, `TEST_RESULTS.md`, `PHOTON_SECURITY_ARCHITECTURE.md`, `THREAT_MODEL.md`, `INDEPENDENT_REVIEW_RESPONSE.md` | Static and synthetic results are separated from privileged and live Photon claims. |

The root marker `.task-a-isolated-root` with exact contents `TASK_A_LAB_ONLY\n` is required for all mutable prototype roots. The code additionally requires the root to resolve below the system temporary directory. This is a staging safety guard, not a production authorization mechanism.

## Photon staging boundary

The installed Hermes adapter still supervises the Node sidecar, holds the full control token, and can call `/send-attachment` with a path. **It has not been changed.** The proposed patch moves the single sidecar connection behind a protected Unix socket, removes the path route, and switches Hermes to a separate restricted broker socket without Photon credentials or the control token. `task_a.photon_front` implements the restricted interface and consumes a private event feed. See `PHOTON_SECURITY_ARCHITECTURE.md` for the wire contract and `ATTACHMENT_COMPATIBILITY.md` for intentionally disabled media behavior.

The staging runner is limited to marked temporary roots. `task_a.service` is a separate fixed-path proposed entry point with protected credentials and sidecar supervision; its child lifecycle was tested with a disposable stub. The systemd templates remain review-only: account provisioning, socket group access, full service launch, patch integration, and real Photon compatibility have not been measured. No unit should be started from this archive. Passing unit tests or `git apply --check` does not establish kernel isolation or Photon authentication.

## Authority

The Gateway alone validates the envelope, resolves `project_hint` from a protected lab registry and files any canonical `proposed` spec. The disposable Gateway run-once test was deliberately excluded from this v0.1.3 run because this authorization forbids creating even lab task records. No direct Kanban intake, approval, execution, publication, merge, deployment, real company repository or permanent Codex runtime is provided.

See `PROTECTED_PATHS.md` for the reviewed production diff inventory, `MIGRATION_RECOVERY.md` for the proposed transaction order, and `INDEPENDENT_SECURITY_REVIEW.md` for acceptance blockers.
