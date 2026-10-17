# Alfred Developer V1 host installation

**Current status:** Developer V1 is installed and activated. The original
installation commands below are historical; the approval-evidence update at
the end is the current host procedure. The first disposable
Backend Developer acceptance is in
[`../live-acceptance/OPERATOR_STEPS.md`](../live-acceptance/OPERATOR_STEPS.md).

**Historical operator procedure; authorization required for any repeat.** Staging did not install
files, restart services, send iMessages, approve T-0001, or run production work.

## Reviewed baseline

At the original installation, `/usr/local/lib/alfred-v1.1/trusted_intake.py`
matched the then-staged `developer_v1/trusted_intake_development.py` byte for byte, SHA-256
`dbc1ecbdf69d7772557aa4181e46301ea5db32a3b0c701512c5c5aacb466cf3f`.
Compared with `v1_1b/trusted_intake.py`, the changes are four imports, optional
development issuer/input arguments, owner-reply observation and administrator
staging operations, and optional issuer initialization in `main`. Existing
Photon confirmation, Gateway filing, and sender behavior passed 40 original
Intake/turn-binding tests and the Photon observer test. The live config had no
development keys at that review; the installed config now has them. **Do not
replace the Intake script.** Any source-hash drift
requires a new review.

Installation adds only `development_grant_root`, `gateway_root`, and
`registry_path` to the existing Intake JSON. It validates a byte-identical,
same-owner, mode `0600` rollback backup *before* an atomic change. A changed
backup stops installation. No Photon, Hermes, Gateway, CTO, or Personal Alfred
source was replaced. The current staged Intake source has one additional
root-only revocation branch; see the update procedure at the end.

## Read-only preflight

Run from `/home/alfred/alfred-development-lab/milestone2/task-a`. Record the
Gateway state and CTO digest. Intake, Photon, and Hermes must be active. An
inactive Gateway oneshot is acceptable when its baseline result is success.
Every manifest line must say `OK`, and the installed Intake source hash must
equal the value above. Stop on any mismatch.

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
sha256sum /usr/local/lib/alfred-v1.1/trusted_intake.py
cmp /usr/local/lib/alfred-v1.1/trusted_intake.py developer_v1/trusted_intake_development.py
sha256sum developer_v1/release.sha256
sha256sum -c developer_v1/release.sha256
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl show -p ActiveState -p Result alfred-development-gateway.service alfred-development-gateway.timer
sha256sum /home/alfred/Git/alfred/.dev/bin/cto.py
```

## Installation (administrator, after separate authorization)

The procedure file is outside the executable release manifest so it can carry
the pinned digest. Compare the preflight manifest digest with
`cd9826eb4aa37dac44592486cdf37cff11681e974f5448279a78c6432bd2e045` before running these commands. Promote only the
reviewed package to root-owned staging, omitting Python caches:

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
sudo install -d -o root -g root -m 0755 /opt/alfred-developer-v1/verified-staging
tar --exclude='__pycache__' --exclude='*.pyc' -C /home/alfred/alfred-development-lab/milestone2/task-a -cf /tmp/alfred-developer-v1-release.tar developer_v1
sudo tar --no-same-owner -C /opt/alfred-developer-v1/verified-staging -xf /tmp/alfred-developer-v1-release.tar
sudo chown -R root:root /opt/alfred-developer-v1/verified-staging
sudo chmod -R go-w /opt/alfred-developer-v1/verified-staging
sudo sha256sum /opt/alfred-developer-v1/verified-staging/developer_v1/release.sha256
sudo env -C /opt/alfred-developer-v1/verified-staging sha256sum -c developer_v1/release.sha256
```

Run this **standalone host permission preflight** after staging promotion and
before any installation authorization. It verifies the current Intake,
Photon, Hermes and Gateway service status, the required Linux identities,
Intake/config/release integrity, and actual UID access through `setpriv`.
Its only writes are a random private fixture under `/tmp`; it removes the
fixture on success, denial, or interruption. It does not touch existing grant,
state or worktree directories, change Intake, reload/restart services, issue a
grant, or start a developer.

```bash
sudo env PYTHONPATH=/opt/alfred-developer-v1/verified-staging:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.host_install --staging /opt/alfred-developer-v1/verified-staging --manifest-sha256 cd9826eb4aa37dac44592486cdf37cff11681e974f5448279a78c6432bd2e045 --preflight
```

**PASS:** exit `0`, JSON `state: PASS`, `runner_request: PASS`, and every
check for `alfreddev`, `alfredmsg`, and `alfredphoton` is `PASS` (their access
was denied). **FAIL:** nonzero exit or any `FAIL` check; do not install.
The preflight does not activate developers. A missing pre-existing protected
directory is represented by an identically owned and protected fixture;
installation checks the real directory again before activation.

Only after this PASS and separate installation authorization, run:

```bash
sudo env PYTHONPATH=/opt/alfred-developer-v1/verified-staging:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.host_install --staging /opt/alfred-developer-v1/verified-staging --manifest-sha256 cd9826eb4aa37dac44592486cdf37cff11681e974f5448279a78c6432bd2e045
```

The installer checks each staged file against the manifest, rejects unlisted
files and symlinks, and checks the installed Intake source. It creates private
grant/worktree/state directories and uses `setpriv` with the **actual host
UIDs** to prove `alfred` can read a mode `0600` request and `alfreddev`,
`alfredmsg`, and `alfredphoton` cannot read the request, grant store, Gateway
repository, Intake config, or provider auth. A failed probe stops before
config modification or Intake restart. The installer then copies a root-owned
release and drop-in, backs up and changes the config, reloads systemd, and
restarts **Intake only**. It checks Intake, Photon, Hermes, Gateway state, and
CTO source; only then does it create a root-owned activation marker. The
installer sends no challenge and starts no developer.
The promoted manifest digest must still equal the pinned value before Python
starts, and every promoted file must pass `sha256sum -c`.

```bash
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl show -p ActiveState -p Result alfred-development-gateway.service alfred-development-gateway.timer
sha256sum /home/alfred/Git/alfred/.dev/bin/cto.py
sudo test -f /opt/alfred-developer-v1/active
sudo stat -c '%a %U:%G %n' /var/lib/alfred-development-grants /var/lib/alfred-development-worktrees /var/lib/alfred-development-state /home/alfred/Alfred/gateway/v1-1-intake.json.pre-developer-v1
```

**PASS:** Intake/Photon/Hermes active, Gateway state and CTO hash match the
recorded baseline, marker exists, all three private directories are
`700 alfred:alfred`, backup is `600 alfred:alfred`, and parsed Intake JSON
differs from its backup only by the three fields above. **FAIL:** any other
result; stop dispatch and use rollback. Staged tests cover the partial-restart
failure path; the host installer leaves grants disabled if recovery fails.

## Live acceptance, after separate owner authorization

For the first disposable Backend Developer test, use
[`../live-acceptance/OPERATOR_STEPS.md`](../live-acceptance/OPERATOR_STEPS.md).
The installed ordinary Intake still pins new owner-confirmed requests to
`dev-001`; the `dev-001` example below must not be used for the new fixture.

Use a **new** disposable Gateway project/repository and canonical task with a
clarification-free CTO plan. T-0001 remains unapproved and has no identified
website repository. A CTO plan, filing confirmation, or model message is never
development approval. Only an exact native threaded owner reply observed by
trusted Photon/Intake creates a grant bound to task, raw spec/plan hashes,
repository, scope, and specialists. It authorizes no merge, deployment, or
publication. Do not send this challenge until the owner authorizes the live
test:

```bash
sudo env PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.stage_approval --socket /run/alfred-development-intake/intake.sock --project dev-001 --task '<NEW_TASK_ID>' --worktree-root /var/lib/alfred-development-worktrees --scope '<APPROVED_RELATIVE_FILE>' --space-id '<OWNER_DM_SPACE_ID>'
```

The run request must be `alfred:alfred`, mode `0600`, inside
`/var/lib/alfred-development-state` (`0700`). A root-owned `0600` request
would be unreadable by the authorized runner. It carries schema
`alfred.developer-run-request/1`, project, task ID, worktree root, scope,
authorization reference, items, and total cost limit. Each item specifies ID,
specialist, files, dependencies, and objective; files partition approved
scope without overlap. Model overrides can select only configured routes.

```bash
sudo -u alfred env PYTHONPATH=/home/alfred/Git/alfred/src:/opt/alfred-developer-v1 /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.run_task --request '/var/lib/alfred-development-state/<NEW_REQUEST>.json' --models /var/lib/alfred-development-state/models.json --gateway-root /home/alfred/Git/alfred --gateway-state /home/alfred/Alfred/gateway --registry /home/alfred/Git/alfred/registry/projects.yaml --grant-root /var/lib/alfred-development-grants --state-root /var/lib/alfred-development-state
```

**PASS:** the selected specialist uses its configured authenticated model,
the bounded worktree changes, approved checks/results and actual model appear
in the report, any local commit and QA input are inspectable, and duplicate
dispatch is denied. **FAIL:** missing evidence, out-of-scope edits, or any
unapproved task execution. Staged fixtures simulate owner approval only and
cannot pass the host verifier.

Coding edits and checks run in bubblewrap: only the assigned worktree is
writable, with no network and no mount of Gateway, grants, credentials, other
repositories, or services. The grant issuer lives in trusted Intake. A missing
or unusable OS namespace stops the worker.

## Targeted rollback and partial failures

Stop new dispatch and let active workers finish. This command first removes
the root-owned activation marker, then restores the verified config backup,
reloads systemd, restarts Intake only, and checks service/Gateway/CTO state.
It retains the reviewed package and drop-in because the currently installed
Intake imports the package at module load even when development is disabled.
It retains grants, reports, and worktrees for audit. No Photon/Hermes restart.

```bash
sudo env PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.host_install --staging /opt/alfred-developer-v1/verified-staging --manifest-sha256 cd9826eb4aa37dac44592486cdf37cff11681e974f5448279a78c6432bd2e045 --rollback
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl show -p ActiveState -p Result alfred-development-gateway.service alfred-development-gateway.timer
sha256sum /home/alfred/Git/alfred/.dev/bin/cto.py
sudo cmp /home/alfred/Alfred/gateway/v1-1-intake.json.pre-developer-v1 /home/alfred/Alfred/gateway/v1-1-intake.json
sudo test ! -e /opt/alfred-developer-v1/active
```

**PASS:** backup and config identical, marker absent, Intake/Photon/Hermes
active, Gateway and CTO match their baseline. **FAIL:** any mismatch; keep
dispatch disabled and inspect Intake logs. An install error before config
change needs no rollback; an error after restart automatically restores config
and retries Intake. If automatic recovery fails, an administrator must repair
Intake before any developer task can run.

## Approval-evidence update for the already installed host (separate authorization)

This section supersedes the historical installation command above for the
approval-evidence correction. **Do not run `host_install` again on the active
host.** Nothing in this section has been run against production. The update
changes only four package modules, their release manifest, and one Intake
source branch for root-only revocation. It does not change Intake JSON,
Photon/Hermes, Gateway, CTO, or any existing grant. The existing `dev-v1-accept
/ T-0002` grant has no issuance evidence and the new verifier must reject it.
Do not run a worker or send a challenge as part of this update.

The reviewed staged release manifest SHA-256 is
`93fbb6b7f29cec18ff9c172808a5ce4a257264000793ec0b639560b05e6b47d8`.
The currently installed manifest and Intake source SHA-256 values are,
respectively, `cd9826eb4aa37dac44592486cdf37cff11681e974f5448279a78c6432bd2e045`
and `dbc1ecbdf69d7772557aa4181e46301ea5db32a3b0c701512c5c5aacb466cf3f`.
`diff -u` between the installed Intake source and staged replacement shows
only the root-only `revoke_development_grant` dispatch branch.

Run these **read-only prechecks** first. Every command must succeed; record
the CTO hash and Gateway results. The release manifest checks every staged
executable file. The update replaces only the five named package files; it
also stages the Intake source and a standalone checker in a root-owned
directory and verifies their copies before replacement or use.

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
echo '93fbb6b7f29cec18ff9c172808a5ce4a257264000793ec0b639560b05e6b47d8  developer_v1/release.sha256' | sha256sum -c -
sha256sum -c developer_v1/release.sha256
echo 'cd9826eb4aa37dac44592486cdf37cff11681e974f5448279a78c6432bd2e045  /opt/alfred-developer-v1/developer_v1/release.sha256' | sudo sha256sum -c -
echo 'dbc1ecbdf69d7772557aa4181e46301ea5db32a3b0c701512c5c5aacb466cf3f  /usr/local/lib/alfred-v1.1/trusted_intake.py' | sudo sha256sum -c -
sudo test -f /opt/alfred-developer-v1/active
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl show -p ActiveState -p Result alfred-development-gateway.service alfred-development-gateway.timer
sha256sum /home/alfred/Git/alfred/.dev/bin/cto.py
```

After explicit operator authorization, prepare the private backup and
root-owned update files. The fixed backup path prevents accidental overwrite;
stop if it already exists. The backup is verified before disabling execution.
No credentials or grant records are copied. The update directory is readable by
`alfred` solely so the post-install checker can run without root privileges;
the protected backup remains mode `0700`.

```bash
set -e
DEV_ROOT=/opt/alfred-developer-v1
DEV_STAGE=/home/alfred/alfred-development-lab/milestone2/task-a/developer_v1
DEV_BACKUP=$DEV_ROOT/approval-evidence-backup-v1
DEV_UPDATE=$DEV_ROOT/approval-evidence-update-v1
sudo test ! -e "$DEV_BACKUP"
sudo test ! -e "$DEV_UPDATE"
sudo install -d -o root -g root -m 0700 "$DEV_BACKUP"
sudo install -d -o root -g root -m 0755 "$DEV_UPDATE"
sudo cp -a "$DEV_ROOT/developer_v1" "$DEV_BACKUP/developer_v1"
sudo cp -a /usr/local/lib/alfred-v1.1/trusted_intake.py "$DEV_BACKUP/trusted_intake.py"
echo "cd9826eb4aa37dac44592486cdf37cff11681e974f5448279a78c6432bd2e045  $DEV_BACKUP/developer_v1/release.sha256" | sudo sha256sum -c -
echo "dbc1ecbdf69d7772557aa4181e46301ea5db32a3b0c701512c5c5aacb466cf3f  $DEV_BACKUP/trusted_intake.py" | sudo sha256sum -c -
sudo env -C "$DEV_BACKUP" sha256sum -c developer_v1/release.sha256
for file in owner_grants.py pipeline.py stage_approval.py trusted_intake_development.py release.sha256; do
  sudo install -o root -g root -m 0644 "$DEV_STAGE/$file" "$DEV_UPDATE/$file"
done
sudo install -o root -g root -m 0644 "$DEV_STAGE/trusted_intake_development.py" "$DEV_UPDATE/trusted_intake.py"
sudo install -o root -g root -m 0644 /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/verify_evidence_host_update.py "$DEV_UPDATE/verify_evidence_host_update.py"
for file in owner_grants.py pipeline.py stage_approval.py trusted_intake_development.py release.sha256; do
  sudo cmp "$DEV_STAGE/$file" "$DEV_UPDATE/$file"
done
echo "93fbb6b7f29cec18ff9c172808a5ce4a257264000793ec0b639560b05e6b47d8  $DEV_UPDATE/release.sha256" | sudo sha256sum -c -
echo "cef079f4041aea439a3bb58f4ea728e9dd38ae45b4258a1183c962670b0c4a6f  $DEV_UPDATE/trusted_intake.py" | sudo sha256sum -c -
echo "cd45b6d17efd0c95867835a022b2321079bc627024d4515209bcaf9c7c6df362  $DEV_UPDATE/verify_evidence_host_update.py" | sudo sha256sum -c -
```

The next block is the **only host replacement**. It moves the activation
marker into the verified backup before touching code. Each file replacement is
atomic. A failed command stops the block; then use the rollback block below.
Only Intake is restarted. The post-install checker imports the installed
trusted Intake, confirms that the historical T-0002 grant fails specifically
for missing evidence, verifies a synthetic evidence-bound grant only under a
private temporary `/tmp` directory, and compares service/Gateway/CTO state
with the pre-replacement baseline. It does not send through Photon, issue a
production grant, invoke a worker, or change the historical grant. The real
activation marker stays absent during this check; its read-only verifier
diagnostic uses the already hash-checked root-owned Intake source as a marker
solely within the checker process. Re-enable execution only if it prints
`PASS` and exits zero. Do not dispatch a task during this procedure.

```bash
set -euo pipefail
DEV_ROOT=/opt/alfred-developer-v1
DEV_BACKUP=$DEV_ROOT/approval-evidence-backup-v1
DEV_UPDATE=$DEV_ROOT/approval-evidence-update-v1
CTO_BEFORE=$(sha256sum /home/alfred/Git/alfred/.dev/bin/cto.py | cut -d ' ' -f1)
GATEWAY_BEFORE=$(systemctl show -p ActiveState -p Result alfred-development-gateway.service alfred-development-gateway.timer | sha256sum | cut -d ' ' -f1)
sudo test -f "$DEV_BACKUP/trusted_intake.py"
sudo test -f "$DEV_UPDATE/release.sha256"
echo "cd45b6d17efd0c95867835a022b2321079bc627024d4515209bcaf9c7c6df362  $DEV_UPDATE/verify_evidence_host_update.py" | sudo sha256sum -c -
sudo mv -T "$DEV_ROOT/active" "$DEV_BACKUP/active"
for file in owner_grants.py pipeline.py stage_approval.py trusted_intake_development.py release.sha256; do
  sudo install -o root -g root -m 0644 "$DEV_UPDATE/$file" "$DEV_ROOT/developer_v1/$file.next"
  sudo mv -T "$DEV_ROOT/developer_v1/$file.next" "$DEV_ROOT/developer_v1/$file"
done
sudo install -o root -g root -m 0644 "$DEV_UPDATE/trusted_intake.py" /usr/local/lib/alfred-v1.1/trusted_intake.py.next
sudo mv -T /usr/local/lib/alfred-v1.1/trusted_intake.py.next /usr/local/lib/alfred-v1.1/trusted_intake.py
echo '93fbb6b7f29cec18ff9c172808a5ce4a257264000793ec0b639560b05e6b47d8  /opt/alfred-developer-v1/developer_v1/release.sha256' | sudo sha256sum -c -
sudo env -C "$DEV_ROOT" sha256sum -c developer_v1/release.sha256
echo 'cef079f4041aea439a3bb58f4ea728e9dd38ae45b4258a1183c962670b0c4a6f  /usr/local/lib/alfred-v1.1/trusted_intake.py' | sudo sha256sum -c -
sudo systemctl restart alfred-development-intake.service
sudo test ! -e "$DEV_ROOT/active"
sudo -u alfred env PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B "$DEV_UPDATE/verify_evidence_host_update.py" --cto-sha256 "$CTO_BEFORE" --gateway-sha256 "$GATEWAY_BEFORE"
sudo mv -T "$DEV_BACKUP/active" "$DEV_ROOT/active"
sudo test -f "$DEV_ROOT/active"
```

**PASS:** all hashes/checks succeed, the checker prints `PASS`, Intake/Photon/
Hermes remain active, Gateway state and CTO hash are unchanged, and the marker
is restored only afterward. **FAIL:** any command fails, the checker prints
`FAIL` or returns nonzero, any source hash differs, or the marker appears
before acceptance; leave execution disabled and perform rollback.
Personal Alfred messaging is covered by the staged Intake/Photon tests; this
update sends no live message. The existing T-0002 grant is rejected by the
new verifier because it lacks challenge, decision and issuance records.

For **rollback after a partial or completed update**, retain all grant and
execution records. The rollback deliberately leaves development execution
disabled: restoring the old verifier while re-enabling it would make the
historical grant executable again. Restore only the five changed package
files and Intake source from the verified backup, then restart Intake.

```bash
set -e
DEV_ROOT=/opt/alfred-developer-v1
DEV_BACKUP=$DEV_ROOT/approval-evidence-backup-v1
echo "cd9826eb4aa37dac44592486cdf37cff11681e974f5448279a78c6432bd2e045  $DEV_BACKUP/developer_v1/release.sha256" | sudo sha256sum -c -
echo "dbc1ecbdf69d7772557aa4181e46301ea5db32a3b0c701512c5c5aacb466cf3f  $DEV_BACKUP/trusted_intake.py" | sudo sha256sum -c -
sudo env -C "$DEV_BACKUP" sha256sum -c developer_v1/release.sha256
if sudo test -e "$DEV_ROOT/active"; then sudo mv -T "$DEV_ROOT/active" "$DEV_BACKUP/disabled-after-rollback"; fi
for file in owner_grants.py pipeline.py stage_approval.py trusted_intake_development.py release.sha256; do
  sudo install -o root -g root -m 0644 "$DEV_BACKUP/developer_v1/$file" "$DEV_ROOT/developer_v1/$file.next"
  sudo mv -T "$DEV_ROOT/developer_v1/$file.next" "$DEV_ROOT/developer_v1/$file"
done
sudo install -o root -g root -m 0644 "$DEV_BACKUP/trusted_intake.py" /usr/local/lib/alfred-v1.1/trusted_intake.py.next
sudo mv -T /usr/local/lib/alfred-v1.1/trusted_intake.py.next /usr/local/lib/alfred-v1.1/trusted_intake.py
echo 'cd9826eb4aa37dac44592486cdf37cff11681e974f5448279a78c6432bd2e045  /opt/alfred-developer-v1/developer_v1/release.sha256' | sudo sha256sum -c -
sudo env -C "$DEV_ROOT" sha256sum -c developer_v1/release.sha256
echo 'dbc1ecbdf69d7772557aa4181e46301ea5db32a3b0c701512c5c5aacb466cf3f  /usr/local/lib/alfred-v1.1/trusted_intake.py' | sudo sha256sum -c -
sudo systemctl restart alfred-development-intake.service
test "$(systemctl is-active alfred-development-intake.service)" = active
test "$(systemctl is-active alfred-photon.service)" = active
test "$(systemctl is-active alfred-hermes.service)" = active
sudo test ! -e "$DEV_ROOT/active"
```

Only after a separately authorized, successful update may an operator revoke
the historical T-0002 grant and send a **new** Photon challenge. Revocation
does not fabricate old evidence. The challenge command must recompute the
canonical task and current CTO plan; the owner must reply natively to its
actual outbound ID. Neither command is part of installation:

```bash
sudo env PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.stage_approval --socket /run/alfred-development-intake/intake.sock --revoke --project dev-v1-accept --task T-0002
sudo env PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.stage_approval --socket /run/alfred-development-intake/intake.sock --project dev-v1-accept --task T-0002 --worktree-root /var/lib/alfred-development-worktrees --scope calculator.py --space-id '<VERIFIED_OWNER_DM_SPACE_ID>'
```

## Codex executable-resolution correction (separate operator authorization)

The first T-0002 run failed at `CodexReadOnlyBroker.authenticated()` before
`authority.claim()`. The `alfred` identity has an executable, authenticated
Codex CLI at `/home/alfred/.local/bin/codex`; the restricted runner `PATH`
does not include that directory. The corrected broker derives this absolute
path from the runner UID, verifies and pins its resolved target before any
single-use claim, and uses that target for authentication and generation.
The evidence-bound T-0002 grant was unrevoked, unexpired and unclaimed at
inspection; no task worktree, branch, model generation, commit, report or QA
input was created. This update does not change the grant or its evidence.

The installed approval-evidence manifest must still be
`93fbb6b7f29cec18ff9c172808a5ce4a257264000793ec0b639560b05e6b47d8`.
The corrected staged manifest is
`586f92ef61d6cc328c4c5202e5d86dd0d3e47bfa3e42a1e1e08750fef721576c`.
Only `real_worker.py`, `pipeline.py` and `release.sha256` are replaced. Intake,
Photon, Hermes, Gateway, CTO, model configuration and provider credentials
are untouched. No service restart is needed because the runner is on demand.

After explicit authorization, run these prechecks and make a protected,
verified backup. Stop on any mismatch. The CLI check suppresses its output
so account details are not written to an ordinary log.

```bash
set -euo pipefail
cd /home/alfred/alfred-development-lab/milestone2/task-a
DEV_ROOT=/opt/alfred-developer-v1
DEV_BACKUP=$DEV_ROOT/codex-path-backup-v1
DEV_UPDATE=$DEV_ROOT/codex-path-update-v1
echo '586f92ef61d6cc328c4c5202e5d86dd0d3e47bfa3e42a1e1e08750fef721576c  developer_v1/release.sha256' | sha256sum -c -
sha256sum -c developer_v1/release.sha256
echo '93fbb6b7f29cec18ff9c172808a5ce4a257264000793ec0b639560b05e6b47d8  /opt/alfred-developer-v1/developer_v1/release.sha256' | sudo sha256sum -c -
sudo test -f "$DEV_ROOT/active"
sudo test ! -e "$DEV_BACKUP"
sudo test ! -e "$DEV_UPDATE"
sudo -u alfred env -i HOME=/home/alfred PATH=/usr/bin:/bin /home/alfred/.local/bin/codex login status >/dev/null 2>&1
sudo install -d -o root -g root -m 0700 "$DEV_BACKUP" "$DEV_UPDATE"
for file in real_worker.py pipeline.py release.sha256; do
  sudo cp -a "$DEV_ROOT/developer_v1/$file" "$DEV_BACKUP/$file"
  sudo install -o root -g root -m 0644 "developer_v1/$file" "$DEV_UPDATE/$file"
  sudo cmp "developer_v1/$file" "$DEV_UPDATE/$file"
done
echo "cda882868d81b0426edd423ca2bf9beb4f8715e8078d0e1f1a3314c0579d8a58  $DEV_BACKUP/real_worker.py" | sudo sha256sum -c -
echo "b8fadd70c597ff90feed672c81be7cb193b6dd93bbb8a51b06aaf073d1aba7e7  $DEV_BACKUP/pipeline.py" | sudo sha256sum -c -
echo "93fbb6b7f29cec18ff9c172808a5ce4a257264000793ec0b639560b05e6b47d8  $DEV_BACKUP/release.sha256" | sudo sha256sum -c -
echo "0c29350880f3fc76af87790554afff2b3a20d974a3f94981fcc8b3cb8e460b3f  $DEV_UPDATE/real_worker.py" | sudo sha256sum -c -
echo "49bf5c3e600f77c02d348f7d119da69509064c86597cdba18dcc435c0e6b7781  $DEV_UPDATE/pipeline.py" | sudo sha256sum -c -
echo "586f92ef61d6cc328c4c5202e5d86dd0d3e47bfa3e42a1e1e08750fef721576c  $DEV_UPDATE/release.sha256" | sudo sha256sum -c -
```

Then disable execution, replace the three files atomically, verify the
installed release, and run the **authentication-only** smoke test under the
restricted runner `PATH`. The marker is restored only after that test passes.
This block sends no message, issues no grant and performs no development work.

```bash
set -euo pipefail
DEV_ROOT=/opt/alfred-developer-v1
DEV_BACKUP=$DEV_ROOT/codex-path-backup-v1
DEV_UPDATE=$DEV_ROOT/codex-path-update-v1
sudo mv -T "$DEV_ROOT/active" "$DEV_BACKUP/active"
for file in real_worker.py pipeline.py release.sha256; do
  sudo install -o root -g root -m 0644 "$DEV_UPDATE/$file" "$DEV_ROOT/developer_v1/$file.next"
  sudo mv -T "$DEV_ROOT/developer_v1/$file.next" "$DEV_ROOT/developer_v1/$file"
done
echo '586f92ef61d6cc328c4c5202e5d86dd0d3e47bfa3e42a1e1e08750fef721576c  /opt/alfred-developer-v1/developer_v1/release.sha256' | sudo sha256sum -c -
sudo env -C "$DEV_ROOT" sha256sum -c developer_v1/release.sha256
sudo test ! -e "$DEV_ROOT/active"
sudo -u alfred env -i HOME=/home/alfred PATH=/usr/bin:/bin PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -c 'from developer_v1.real_worker import CodexReadOnlyBroker; broker=CodexReadOnlyBroker(); assert broker.require_executable().startswith("/home/alfred/.codex/packages/standalone/"); assert broker.authenticated()'
sudo mv -T "$DEV_BACKUP/active" "$DEV_ROOT/active"
sudo test -f "$DEV_ROOT/active"
```

**PASS:** both manifest checks and the restricted-PATH authentication check
succeed before activation. **FAIL:** any command fails; leave the marker absent
and run the rollback below. This smoke test does not consume a grant. Before a
later authorized T-0002 retry, recheck that its exact plan-bound grant remains
unexpired, unrevoked and without an `execution-<reference>.json` claim. If it
remains unused, the same grant can authorize that one attempt; an expired or
claimed grant requires a fresh owner authorization, never a silent retry.

Rollback restores only these three files and **leaves execution disabled**.
It retains the protected grant and evidence records for audit; no Intake or
Photon restart is required.

```bash
set -euo pipefail
DEV_ROOT=/opt/alfred-developer-v1
DEV_BACKUP=$DEV_ROOT/codex-path-backup-v1
echo "cda882868d81b0426edd423ca2bf9beb4f8715e8078d0e1f1a3314c0579d8a58  $DEV_BACKUP/real_worker.py" | sudo sha256sum -c -
echo "b8fadd70c597ff90feed672c81be7cb193b6dd93bbb8a51b06aaf073d1aba7e7  $DEV_BACKUP/pipeline.py" | sudo sha256sum -c -
echo "93fbb6b7f29cec18ff9c172808a5ce4a257264000793ec0b639560b05e6b47d8  $DEV_BACKUP/release.sha256" | sudo sha256sum -c -
if sudo test -e "$DEV_ROOT/active"; then sudo mv -T "$DEV_ROOT/active" "$DEV_BACKUP/disabled-after-rollback"; fi
for file in real_worker.py pipeline.py release.sha256; do
  sudo install -o root -g root -m 0644 "$DEV_BACKUP/$file" "$DEV_ROOT/developer_v1/$file.next"
  sudo mv -T "$DEV_ROOT/developer_v1/$file.next" "$DEV_ROOT/developer_v1/$file"
done
echo '93fbb6b7f29cec18ff9c172808a5ce4a257264000793ec0b639560b05e6b47d8  /opt/alfred-developer-v1/developer_v1/release.sha256' | sudo sha256sum -c -
sudo env -C "$DEV_ROOT" sha256sum -c developer_v1/release.sha256
sudo test ! -e "$DEV_ROOT/active"
```
