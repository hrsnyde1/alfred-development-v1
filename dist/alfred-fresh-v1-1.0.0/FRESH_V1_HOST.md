# Fresh-task V1 integration — staged installation candidate

This release connects existing components. It adds no service, timer, Gateway,
Photon SDK connection, model identity, credential or database. Installation and
activation require separate operator authorization. No commands below have been
executed against production. Earlier T-0002-specific installation and acceptance
commands are historical; do not use them for this release or a fresh task.

## What changes

- Intake derives one explicit, active, Hermes-authorized project ID from the
  authenticated original owner text. Ambiguous or absent projects are refused.
  A native confirmation seals its original request/confirmation/DM route before
  the existing Gateway filer allocates a new canonical ID.
- Existing CTO polling prepares plans without sending its former ordinary
  approval summary. The existing root evidence timer prepares current-main CTO
  evidence, freezes the baseline in the canonical plan, and calls the existing
  root-only development issuer through its Unix socket. The exact plan hash,
  repository, scope and specialist are bound to the native owner reply.
- The same existing timer invokes the installed specialist runner as `alfred`,
  QA as `alfredqa`, Reviewer as `alfredreview`, Publisher as `alfredpublish`, and
  notifier as `alfred`. Worker environments/capabilities are cleared. Only Intake
  authenticates replies; only Publisher creates the branch and draft PR.
- Root creates protected per-task evidence under `/var/lib/alfred-v1-handoffs`.
  Each external attempt is fsynced before dispatch. An interrupted, failed or
  uncertain attempt is held for investigation, never automatically retried.
- QA and Reviewer keep their installed independent models and checks. Each
  fresh canonical criterion gets a verified unittest mapping. A missing QA model,
  failed test, failed criterion or non-approved review stops publication.
- Publisher V1.1 is unchanged. Its verified fresh plan is sealed by root and
  separately approved through Intake. Historical decisions remain readable and
  owner-event replay checks still span development and publication decisions.
- Completion uses a separate per-task configuration and the existing durable
  tracker. It requires exact verified `PUBLISHED_DRAFT` evidence, separate owner
  authorization and a current GitHub PR readback. It never initializes/reset the
  installed tracker, retries uncertain sends, asserts an owner merge without
  evidence, merges, or claims deployment.

The initial activation policy is deliberately limited to `dev-v1-accept`, its
registered `hrsnyde1/alfred-dev-v1-acceptance` destination, `main`, backend scope
`calculator.py` and `test_calculator.py`, and the existing model budget. There
is no task ID or baseline constant. Historical canonical checkouts are not reset:
planning fetches current registered main into `refs/remotes/alfred-v1/main`,
freezes that SHA before approval, and starts the new worktree there. Publisher
rejects a moved main before pushing.

## Preconditions and disabled installation

Use the exact archive SHA-256 and manifest SHA-256 from `FRESH_V1_RESULTS.md`.
Copy the archive into a new root-owned mode-0700 operator directory, verify that
pin there, and extract there before executing any root script. The release
contains `host-contract.json` with the observed installed code hashes. The
transaction refuses changed dependencies and verifies the old Developer file
inventory. Test-only QA/Reviewer/Publisher/notifier copies in the archive are
never installed.

Operator prerequisites:

1. Retain an existing Gateway PAUSE, or create it as `alfred` and record that
   this installation created it. Wait for Gateway/evidence oneshots and all
   Developer/QA/Reviewer/Publisher workers to be idle. Do not interrupt an active
   worker or reuse a pending grant. Do not send a test message.
2. Verify the root-owned Developer `active` marker, existing private stores,
   separate worker UIDs, exact authorized registry destination and the installed
   component hashes. The transaction never moves or removes `active`.
3. Confirm actual private Personal Alfred guidance permits owner requests for
   `dev-v1-accept`. The existing tool accepts draft fields only and needs no
   identity/project argument. If its instructions restrict requests to
   `dev-001`, replace that restriction in the existing instruction location with:

   > For an owner software change naming one explicit authorized project,
   > faithfully draft the request and call development_gateway_submit for the
   > original Photon turn. Never guess an ambiguous project. Ask the owner to
   > reply directly to the protected preview with “Yes, go ahead”. Filing does
   > not approve development. After confirmation, use development_gateway_status
   > and report a task ID only when the trusted result says filed. Development
   > and GitHub publication each require a separate native reply to their
   > protected challenge. Do not promise merge or deployment.

   That private guidance was not readable by this staging account; its contents
   are an operator verification gate. Do not blindly edit an unknown file or
   restart Personal Alfred. If a guidance change requires a restart, review that
   separately before activation.
4. Create the new **data directory only**, if absent, root:alfredevidencero mode
   0750, with read/search ACLs for existing role users. Preserve it on rollback:

   ```bash
   sudo install -d -o root -g alfredevidencero -m 0750 /var/lib/alfred-v1-handoffs
   sudo setfacl -m u:alfred:r-x,u:alfredqa:r-x,u:alfredreview:r-x,u:alfredpublish:r-x /var/lib/alfred-v1-handoffs
   ```

   On an existing directory first verify owner/mode and retain every record.

The exact expanded commands and release pins are in `FRESH_V1_RESULTS.md`.
The file transaction itself performs no service control and invokes no worker.
It installs a disabled policy, takes a private durable byte-for-byte backup,
updates five Developer code files plus its schema/manifest, existing Intake and
CTO code/schema, a root library, and three drop-ins for existing units. Only
the existing Intake service needs a restart. Gateway and evidence use their
existing timers and pick up the new oneshot commands after daemon-reload.

The Intake drop-in adds an inherited `u:root:rw-` ACL for its Unix socket.
The existing root timer lacks CAP_DAC_OVERRIDE, so UID 0 otherwise has no write
permission on the alfred-owned mode-0660 socket. No broader capability/group is
added. After restart, verify that specific ACL with `sudo getfacl -cp
/run/alfred-development-intake/intake.sock`; native SO_PEERCRED checks still
refuse privileged operations from Photon, Hermes and the Intake UID.

After an authorized transaction:

```bash
sudo systemctl daemon-reload
sudo systemctl restart alfred-development-intake.service
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl is-active alfred-development-gateway.timer alfred-development-evidence.timer
sudo systemd-analyze verify alfred-development-intake.service alfred-development-gateway.service alfred-development-evidence.service
```

Keep PAUSE and policy `enabled: false`. Verify installed files against the
mapping, root ancestry/permissions, unchanged activation marker, and Intake
journal without sending messages. A disabled existing evidence tick returns
`{"state":"disabled"}` and does not create a job or approval.

The evidence drop-in retains the existing capability boundary and extends only
its existing oneshot for the required worker directories/network families. It
does not grant worker capabilities. Home access becomes read-only, with exact
write exceptions for canonical Git metadata, CTO state, the existing completion
tracker and model runtime state. Verify actual QA/Reviewer CLI/auth home paths
before activation; no credentials are copied or changed.

## Rollback and interrupted installation

Retain PAUSE and wait for current workers to finish. Execute the reviewed
`fresh_v1/upgrade.py rollback --backup ...` from the protected extracted release,
then daemon-reload and restart **Intake only**. The backup index predates every
mutation. Caught failures restore prior files automatically; an uncatchable kill
or power loss requires the same explicit rollback. A failed rollback must be
resolved and rerun; it never silently removes activation.

Rollback restores only its listed code, policy, drop-ins and Intake configuration,
including original owners/modes. It never removes a Developer grant, execution
result, task/spec/plan, QA/Reviewer output, Publisher ERROR/success result,
publication authorization, Git credential, worktree, notification record or
reconciliation. Newly created data directories remain. Do not roll back whole
`/var/lib` trees or run an installer that deactivates/reinitializes Developer.
Do not remove attempt markers or rewrite uncertain delivery to force a retry.

## Readiness checklist for one genuine request

- [ ] Reviewed pins, inventory, disabled install and disposable rollback tests pass.
- [ ] Existing Intake, Photon, Personal Alfred, Gateway timer and evidence timer
      are healthy; only Intake was restarted for this code upgrade.
- [ ] Private Personal Alfred guidance/tool availability is project-aware.
- [ ] Existing root service can read policy/job inputs and assume existing UIDs.
      Each role can read only its new inputs, execute its existing CLI, and write
      its own outputs; Publisher source/authorization remain root-owned read-only.
- [ ] Developer activation and one-use native grant verification remain enabled.
      QA model is enabled, checks include existing examples and unittest, and
      Reviewer retains `gpt-6-astra` under its independent identity.
- [ ] Existing `alfred` gh read credentials and Publisher credentials are intact.
      Read current registered main; never replace it with the old T-0002 SHA.
- [ ] Existing completion tracker is valid/private and retains T-0002's uncertain
      transport record plus separate reconciliation. Do not initialize it.
- [ ] A separate operator activation approves the bounded automatic handoffs,
      challenge sends, draft-only publication after its separate owner reply,
      and completion send after verified success. Only then atomically set the
      protected policy `enabled: true` and release a PAUSE created for this work.
- [ ] No historical task is adopted: only new Intake route records qualify.
      Fresh Gateway allocation must avoid T-0001/T-0002; do not preassign an ID.

Proposed genuine owner iMessage:

> In project dev-v1-accept, please add a backend calculator helper
> multiply(a: int, b: int) -> int in calculator.py, with unittest coverage in
> test_calculator.py for positive integers, negative integers, and zero. Preserve
> add and subtract and keep the existing dependencies. Limit changes to those
> two files. Please prepare the development plan for my approval, then obtain
> separate publication approval for a GitHub draft PR. Do not merge or deploy.

The owner confirms the preview, separately approves development, and separately
approves publication using fresh native replies. No operator injects a Gateway
task, fabricates an authorization or manually runs each specialist. A held stage
requires evidence review; it is never bypassed to complete acceptance.
