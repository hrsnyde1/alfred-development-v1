# Candidate migration, recovery and rollback — not executable production instructions

## v0.1.4 hold and reconciliation gate

No v0.1.4 release, migration or cutover is authorized. The installed Spectrum
cursor is volatile and may accept an event gap; a sidecar spool plus broker
journal cannot prove that every incoming event survived a crash. The current
protected design journals real observations as `unverified`, sends `held` to
the sidecar without a read receipt, and does not deliver them to Hermes or
Gateway filing. Preserve the spool, journal, ledger and audit on every restart.
Do not promote, delete, or replay unverified records on operator intuition.
A future independently reviewed procedure must establish provider continuity
or explicit human reconciliation and account for events that never reached the
spool. Crash before inbox rename may leave hidden temporary names; cleanup
must be performed by an authorized Gateway-side operator, not by broadening
broker directory read permission. Stop intake at journal/audit capacity.

The current `task_a.release` CLI is **limited to marked temporary roots**. A protected production installer, account/ACL setup and migration script still require a new reviewed release. Nothing in this file authorizes service control or credential handling.

## v0.1.3 cutover and recovery addition

The protected service entry point is `python -m task_a.service` from a pinned,
root-owned runtime. The proposed systemd socket unit must create
`/run/alfred-photon-intake/hermes.sock` as `alfredphoton:alfredhermes 0660`;
the service must receive that one descriptor through socket activation. The
service owns `private.sock`, a single child Node process, a protected event
spool, event journal, ledger and bounded audit file. The credential directory
must be systemd-managed and carry only the five named `LoadCredential` items;
Hermes must receive only `PHOTON_TASK_A_BROKER_SOCKET` and no Photon credential.
Before enabling, an independent test must prove the runtime and state paths
have the exact owner/mode described in `templates/permissions/paths.json`.

Stop the old Photon sidecar before starting the protected sidecar, and verify
no concurrent Spectrum connection. To recover from a protected sidecar
crash, leave spool and journal bytes intact, restart the protected service,
and verify each pending delivery either receives a durable accepted/rejected
decision or remains explicitly unavailable. Do not clear an uncertain reply
reservation to force a retry. A three-attempt delayed event remains in the
journal for operator inspection and service restart. On storage failure or
audit capacity, stop intake and preserve spool, journal, audit and inbox
ledger for review; do not delete records to regain capacity without an
approved recovery procedure. A read receipt may be absent after a crash even
when the broker already accepted the event; the durable journal is the
authoritative intake evidence.

Rollback must stop the protected service and restricted socket, confirm the
child and private listener are gone, and restore the prior pinned adapter,
sidecar, units and credentials from verified backups. Preserve v0.1.2 and
v0.1.3 archives separately. Do not replay a reserved outbound reply. Verify
Evidence Bridge v0.2.1 payload hashes and both tool handlers after rollback.

## Required deployment transaction after separate authorization

1. Record the formal ADR amendment and allocate/approve the protected Task A spec. Independently verify pinned Hermes source commit, source provenance, package checksums, Evidence Bridge v0.2.1 hashes, exact live config/unit/credential inventory, UID/GID availability, and all baseline path hashes. Refuse any mismatch.
2. On a separately approved test host, verify the root-controlled source checkout and promote a reviewed full commit plus separately hashed `alfred`/`dev-001` registry fixture to a versioned root-owned lab runtime. Pin the separate lab Python/dependency environment under `/opt/alfred-dev-gateway-lab-venv` and hash executable entry points. Preserve the prior selector, manifest and runtime copy.
3. Prepare new dedicated identities, root-owned unit files, code trees, narrow ACLs, service-private state and isolated lab repo/inbox. Do not copy real Gateway journal, grants, approvals, PAUSE/STOP, publisher or GitHub credentials. Do not copy Photon `auth.json`, project credentials, sidecar token or stale runtime token record into Hermes state; place new credentials only in the protected Photon service. Copy only audited Hermes session/Kanban state and the exact Evidence Bridge v0.2.1 payload; leave original evidence report ownership/mode unchanged.
4. In the authorized disposable test host, apply only the hash-pinned proposed Photon patch to a protected copy. Start exactly one protected sidecar process with private Photon credentials and a private control token; keep its Unix control socket inaccessible to Hermes. Start the restricted front and verify event-feed peer UID, original explicit `sender.id`, one-connection behavior, bounded replies and lab envelope submission. Prove Hermes has no project credentials, control token or path-bearing attachment route. If any check fails, **stop before service migration**.
5. In a later approved maintenance window, stop the UID-1000 user gateway, verify it and any supervised children are gone, then install/enable the new root-managed system gateway. Never run both. No installer step restarts a service automatically. Run independent kernel-denial, service, Evidence Bridge and Photon compatibility acceptance before any lab request submission.
6. Only after Task A independent security sign-off may Task B planning or implementation begin. A lab `proposed` task never grants execution.

## Transaction state model tested in staging

`verify` checks payload and baseline SHA-256 plus baseline modes before writing. `install` records a transaction, makes and verifies preserved backups, atomically replaces each file, then marks `committed`. An interruption before the first state file or during backup causes **no target replacement**; an interruption after any replacement requires `recover`, which checks every backup and observed target before restoring. `rollback` accepts only a committed transaction whose targets still match released hashes. Both operations preserve the transaction and backup directory and mark `rolled_back`. A changed target, backup, path component or checksum refuses recovery rather than overwriting it.

The staging CLI requires `--root`, `--payload` and `--manifest`; both roots must resolve below the temporary directory and have the exact marker. Its install/recover/rollback methods do not change users, groups, ACLs, systemd or production. Failure injection covers transaction creation, each backup, the backup barrier and each file replacement. This is a **simulator**, not a deployable root installer; its ownership and multi-service activation logic are unimplemented.

## Human-controlled production rollback decision

If future approved deployment fails before the new gateway starts, stop and recover from preserved backups while the old user gateway remains inactive; verify hashes and re-enable it only by operator decision. If it fails after startup, stop the new Hermes gateway, restricted front and protected sidecar, verify no child or private socket listener remains, then restore the original adapter/sidecar bytes, user/system service choice, config/state and preserved plugin from verified backups. Revoke the candidate private token before any restart. Re-enable only the previously approved service by operator decision; never run both Photon connections. Check both Evidence Bridge tools and absence of intake tools. Preserve the transaction, old v0.3.2 rollback, Evidence Bridge backups and audit records. A failed checksum requires investigation, not forced overwrite.
