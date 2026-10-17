# Proposed ADR 0009 exception — isolated Linux Photon requester

**Status: proposed; no accepted ADR text changed.** ADR 0009 decision 7
currently requires Hermes' Docker backend. This is a narrow proposed Linux
placement exception for the Task A laboratory and, only after separate
acceptance, a future requester deployment. It does not alter ADR 0009's
static inbox binding, source stamping or human-session attestation.

## Proposed exception

The entire Hermes gateway, every plugin, model tool, local terminal process,
Kanban/cron worker and child runs as a dedicated unprivileged requester
identity inside a measured whole-service OS boundary. No terminal-backend
setting or prompt instruction substitutes for that boundary. Hermes has no
access to protected Gateway checkout, registry, task specs, journal,
PAUSE/STOP, approvals, execution grants, publisher, operator credentials,
Photon project credentials or protected event ledger. The current UID-1000
user service is outside this exception. A local terminal backend is permitted
only if its children remain inside the measured boundary.

One protected Photon sidecar owner retains the existing single authenticated
connection. It observes native SDK events and owns all ingress provenance,
confirmation records, Photon credentials and privileged control operations.
Hermes gets the ordinary conversation feed and a reviewed messaging
compatibility interface, but no event-creation method, private event feed,
control token, sidecar shutdown, arbitrary protected-side filesystem-path
attachment read or direct Gateway submission capability. Normal messaging
features that cannot be safely proxied are individually gated for review;
the boundary cannot be widened just to preserve a feature. The gate is the
only writer of the narrow, statically bound requester inbox.

The separate trusted Gateway identity owns its protected source/runtime copy,
registry, journal, PAUSE/STOP and canonical task files. A lab Gateway is
limited to the isolated `alfred` / `dev-001` fixture. Neither lab runtime nor
Hermes can reach the real Gateway's state. Kernel UID, group, mount, socket,
descriptor and filesystem tests must independently establish these denials.
Service setup, credentials, migrations and a later production cutover require
separate operator approval and rollback.

## Non-grants and acceptance

This exception grants no Hermes-to-Claude path, direct Kanban intake, real
Gateway `run-once`, approval, execution, publication or merge. Gateway-origin
`source: hermes` still comes only from the bound inbox. An `origin.interface`
or sender field in an envelope remains untrusted. The owner’s authenticated
confirmation authorizes only one exact request submission; the existing
hash-bound human approval and protected execution gates remain unchanged.

If separate-identity sidecar operation breaks the installed Photon adapter,
if native SDK reply-target evidence is absent, if any model child can reach
the control token or protected Gateway state, or if the normal messaging and
Evidence Bridge regressions fail, the exception is not accepted. The older
Docker-only rule remains in force until a separately approved ADR amendment,
Task A security acceptance and deployment authorization say otherwise.
