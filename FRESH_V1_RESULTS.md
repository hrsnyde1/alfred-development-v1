# Fresh-task V1 staging results

**Staging: PASS. Live acceptance: BLOCKED until reviewed installation, host checks and separate activation.**

## Completed and tested

The existing Intake/Gateway/CTO/Developer/QA/Reviewer/Publisher/notifier handoffs are connected in staging. New tasks use canonical allocation and current registered main, two separate authenticated native owner approvals, protected task-specific inputs and durable attempts. The tests complete two sequential fresh tasks without reusing T-0001/T-0002 or resetting delivery state. No production code, service, credentials or historical evidence was modified. No real Photon message, model invocation, GitHub write or publication occurred.

- **269 passed, 2 skipped, 58 subtests passed** in the focused suite.
- Both skips are deliberate real-model probes, excluded from this mocked staging mission.
- New tests cover real Intake confirmation/filer, existing timer pickup, exact CTO summaries, one-use development execution, actual isolated Developer/QA checks, independent model ports, Reviewer, exact separate publication approval, local mocked draft publication, notification readback, sequential tasks and durable duplicate/uncertain guards.
- Negative tests cover ambiguous/missing projects, wrong callers, wrong owner/DM/thread, forwarding, stale/expired/reused events, changed plans/seals/baselines, failed QA/review, disabled/paused dispatch, oversized evidence, incomplete attempts and unsafe inputs.
- Disposable upgrade tests cover complete rollback, first/middle/last partial failures, interrupted recovery, historical evidence/credential retention, activation preservation and exact inherited root socket ACLs.
- Ruff: PASS for fresh integration and new tests.

JUnit report: `fresh-v1-staging-results.xml`, SHA-256 `02c675fa4b2eade126752104450245dbb63673c6ee2fb4db7d5730f52077f829`.

## Verified release

Archive: `dist/alfred-fresh-v1-1.0.1.tar.gz`

SHA-256: `a8c550a2a86e5eb8840b9cd85bc5847261cd2fd5c71bcfdd93f4e19dd6a4da3c`

Manifest SHA-256: `e5d76646988548dce178f3d0f734def52cd974c1796ec85aa04ebe9e802c1a56`

**196 inventoried files**, exact archive extraction/inventory and current source comparison PASS. The Developer sub-release has **29 inventoried files** and manifest SHA-256 `c23cb89acc0ddc17fe382c4ea3e985c8404ebbf2dace1d20bbad19da81fa9edd`. Staged Intake SHA-256: `d3e1677cb8d7ee17ab801448e85db48fee12d88bbf21a3561e9e755eef742168`.

The final 1.0.1 release restricts independent worker imports to root-owned paths. The preliminary 1.0.0 candidate is superseded.

The archive contains test-only copies of unchanged workers. They are not deployed. `host-contract.json` pins the observed installed dependencies, including Publisher V1.1. The installation refuses drift.

## Files changed

- `developer_v1/trusted_intake_development.py`: project-aware routing/status, native confirmation route, fresh request rollover, generic protected publication loader and CTO plan delivery.
- `developer_v1/owner_grants.py`: optional exact-plan CTO summary/evidence; validate bounded receipts before sending; retain historical evidence compatibility.
- `developer_v1/pipeline.py`, `developer_v1/run_task.py`: use the approved baseline even without a caller override; retain exact scope and one-use claims.
- `developer_v1/publication_approval.py`, `developer_v1/schemas/publication-plan.schema.json`: root-sealed task-specific plans, per-plan decisions, global event replay checks, preserved historical verification.
- `developer_v1/release.sha256`: new complete component inventory.
- `v1_cto/cto.py`, `v1_cto/plan.schema.json`: prepare-only mode and approved baseline field.
- `fresh_v1/`: fixed handoffs, protected reads, existing-worker identity adapters, disabled example policy, deterministic release/file transaction tools and three existing-unit drop-ins.
- `tests/test_fresh_v1.py`, `tests/test_fresh_v1_release.py`: successful and fail-closed integration/upgrade tests.
- `tests/test_host_install_v1.py`, `tests/test_approval_evidence_host_v1.py`: historical pin checks now use an exact preserved historical fixture rather than mutable new staging code.
- `tests/test_draft_pr_release.py`: verify the already-reviewed Publisher V1.1 pin.
- `tests/fixtures/developer-v1-publication/`: 29-file verified copy of the prior Developer release; historical pins/evidence remain intact.
- `FRESH_V1_HOST.md`, this report, JUnit results and the versioned release artifacts.

## Reviewed disabled installation commands

First complete the preconditions in `FRESH_V1_HOST.md`: preserve/create Gateway PAUSE, wait for workers and existing oneshots to be idle, verify private Personal Alfred routing guidance, root marker, identities, paths and existing component hashes. These are proposed operator commands only.

```bash
sudo install -d -o root -g root -m 0700 /var/lib/alfred-v1-upgrade/fresh-1.0.1
sudo install -o root -g root -m 0600 /home/alfred/alfred-development-lab/milestone2/task-a/dist/alfred-fresh-v1-1.0.1.tar.gz /var/lib/alfred-v1-upgrade/fresh-1.0.1/release.tar.gz
echo 'a8c550a2a86e5eb8840b9cd85bc5847261cd2fd5c71bcfdd93f4e19dd6a4da3c  /var/lib/alfred-v1-upgrade/fresh-1.0.1/release.tar.gz' | sudo sha256sum -c -
sudo tar --no-same-owner --no-same-permissions -xzf /var/lib/alfred-v1-upgrade/fresh-1.0.1/release.tar.gz -C /var/lib/alfred-v1-upgrade/fresh-1.0.1
sudo /usr/bin/python3 -I -B /var/lib/alfred-v1-upgrade/fresh-1.0.1/alfred-fresh-v1-1.0.1/fresh_v1/upgrade.py verify --release /var/lib/alfred-v1-upgrade/fresh-1.0.1/alfred-fresh-v1-1.0.1 --manifest-sha256 e5d76646988548dce178f3d0f734def52cd974c1796ec85aa04ebe9e802c1a56

# Provision only after checking any existing directory; preserve every record.
sudo install -d -o root -g alfredevidencero -m 0750 /var/lib/alfred-v1-handoffs
sudo setfacl -m u:alfred:r-x,u:alfredqa:r-x,u:alfredreview:r-x,u:alfredpublish:r-x /var/lib/alfred-v1-handoffs

sudo /usr/bin/python3 -I -B /var/lib/alfred-v1-upgrade/fresh-1.0.1/alfred-fresh-v1-1.0.1/fresh_v1/upgrade.py install --release /var/lib/alfred-v1-upgrade/fresh-1.0.1/alfred-fresh-v1-1.0.1 --manifest-sha256 e5d76646988548dce178f3d0f734def52cd974c1796ec85aa04ebe9e802c1a56 --backup /var/lib/alfred-v1-upgrade/fresh-1.0.1/backup
sudo systemctl daemon-reload
sudo systemctl restart alfred-development-intake.service
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl is-active alfred-development-gateway.timer alfred-development-evidence.timer
sudo getfacl -cp /run/alfred-development-intake/intake.sock
```

Verify the inherited `user:root:rw-` socket ACL, marker and installed file mapping. Keep PAUSE and policy disabled until the readiness checklist is reviewed. Existing Gateway/evidence timers run the handoffs after separate activation. The transaction itself controls no services. **Intake is the only service requiring restart.** If its restart/health check fails, retain PAUSE and execute rollback; do not activate the new policy.

## Reviewed rollback commands

Retain PAUSE, disable fresh dispatch and wait for workers/oneshots to be idle. If installation was interrupted, the durable backup index identifies every file to restore; the activation marker remains in place.

```bash
sudo /usr/bin/python3 -I -B /var/lib/alfred-v1-upgrade/fresh-1.0.1/alfred-fresh-v1-1.0.1/fresh_v1/upgrade.py rollback --backup /var/lib/alfred-v1-upgrade/fresh-1.0.1/backup
sudo systemctl daemon-reload
sudo systemctl restart alfred-development-intake.service
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
```

Rollback restores only listed code/configuration/drop-ins and preserves original ownership/modes. It leaves grants, authorization decisions/records, all task/QA/Reviewer/Publisher evidence (including ERROR), Git credentials, worktrees, handoff attempts, completion tracking and reconciliation intact. It never moves or removes Developer activation. Data directories remain.

## Remaining host gates and next action

1. Private Personal Alfred guidance was inaccessible; read-only sudo failed because a password is required. An operator must verify project-aware tool routing. The exact replacement instruction, if its current restriction still names only dev-001, is in `FRESH_V1_HOST.md`; no unknown private file was edited.
2. Review/install the disabled release, verify actual UID/ACL/model runtime paths under the existing service restrictions and confirm service health. Root socket operations retain actual UID-0 SO_PEERCRED checks; no broad capabilities/groups are added.
3. Separately authorize bounded activation and the genuine owner request. Real models, delivery, credentials and GitHub were intentionally not exercised by staging tests. The current existing completion tracker must remain in place.

The next action is operator verification of the private guidance and review of this disabled upgrade. The live acceptance checklist and exact proposed owner iMessage are in `FRESH_V1_HOST.md`. Fresh development and publication each require their own genuine native owner reply; neither installation nor staging creates a live grant/authorization.
