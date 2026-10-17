# Reviewed host procedure — development handoff overlay

**Commands for a later, separately authorized operator action. None were run.**
This installs code only, retains PAUSE, and does not authorize a task or retry.
T-0003 recovery remains outside this procedure.

Archive: `alfred-fresh-v1-1.0.1-development-handoff.1.tar.gz`

SHA-256: `4cd5448ed005c8d1eb759ec80a8a021c23b97bf4d030bd880124e9f6043175b9`

Manifest SHA-256: `4392696cd25bbd38ffbe24972899ccc884041a1a8f19321a118c08154a52bb27`

21 payload files plus MANIFEST.sha256. Five runtime sources; seven destinations:

| Payload | Destination |
| --- | --- |
| developer_v1/owner_grants.py | /opt/alfred-developer-v1/developer_v1/owner_grants.py |
| developer_v1/trusted_intake_development.py | /opt/alfred-developer-v1/developer_v1/trusted_intake_development.py |
| same Intake source | /usr/local/lib/alfred-v1.1/trusted_intake.py |
| developer_v1/stage_approval.py | /opt/alfred-developer-v1/developer_v1/stage_approval.py |
| developer_v1/release.sha256 | /opt/alfred-developer-v1/developer_v1/release.sha256 |
| fresh_v1/host.py | /usr/local/lib/alfred-fresh-v1/fresh_v1/host.py |
| development_challenge/sidecar/development-observe.mjs | /home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/development-observe.mjs |

This standalone overlay includes the earlier diagnostics patch. Do not install
the diagnostics-only overlay first. The current pinned baseline is Fresh V1.0.1
with the installed planning fix/recovery. The installer rejects all drift, checks
the full old Developer inventory and unchanged Fresh/Photon dependencies, and
uses the existing atomic file primitive. No service/unit/configuration changes.

## 1. Installation decision, PAUSE and idle workers

Use a root Bash shell only after explicit installation approval. Establish the
existing Gateway PAUSE marker without rewriting an existing one. Wait for active
workers to finish; do not interrupt or launch them. Timers remain configured.

```bash
set -euo pipefail
test "$(id -u)" = 0
umask 077
/usr/bin/python3 -I -B - <<'PY'
import os, pwd, stat
from pathlib import Path
p = Path('/home/alfred/Alfred/gateway/PAUSE')
try:
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
except FileExistsError:
    assert stat.S_ISREG(p.lstat().st_mode) and not p.is_symlink()
else:
    try:
        u = pwd.getpwnam('alfred')
        os.fchown(fd, u.pw_uid, u.pw_gid)
        os.fsync(fd)
    finally: os.close(fd)
    fd = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
PY
assert_idle() {
  for unit in alfred-development-evidence.service alfred-development-gateway.service \
      alfred-dev-executor.service alfred-dev-qa-runner.service \
      alfred-dev-qa-snapshot.service alfred-dev-qa-auth.service; do
    test "$(systemctl show "$unit" -p ActiveState --value)" = inactive
    test "$(systemctl show "$unit" -p SubState --value)" = dead
    test "$(systemctl show "$unit" -p MainPID --value)" = 0
    test "$(systemctl show "$unit" -p ControlPID --value)" = 0
  done
}
assert_idle
test -f /home/alfred/Alfred/gateway/PAUSE
printf '%s  %s\n' \
  3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492 \
  /usr/local/lib/alfred-fresh-v1/fresh_v1/upgrade.py | sha256sum -c -
```

Also confirm no manual specialist, in-flight Photon send, owner approval or
unfiled request/confirmation exchange. PAUSE alone does not quiesce messaging.
If quiescence is unknown, defer installation/activation; do not reset evidence.

## 2. Private, pinned review copy

```bash
HANDOFF_NAME=alfred-fresh-v1-1.0.1-development-handoff.1
HANDOFF_ARCHIVE=/root/alfred-fresh-v1-1.0.1-development-handoff.1.tar.gz
HANDOFF_PARENT=/root/alfred-fresh-v1-development-handoff-1-review
HANDOFF_RELEASE="$HANDOFF_PARENT/$HANDOFF_NAME"
HANDOFF_BACKUP=/root/alfred-fresh-v1-development-handoff-1-backup
HANDOFF_MANIFEST=4392696cd25bbd38ffbe24972899ccc884041a1a8f19321a118c08154a52bb27
test ! -e "$HANDOFF_ARCHIVE"
test ! -e "$HANDOFF_PARENT"
test ! -e "$HANDOFF_BACKUP"
install -o root -g root -m 0600 \
  /home/alfred/alfred-development-lab/milestone2/task-a/dist/alfred-fresh-v1-1.0.1-development-handoff.1.tar.gz \
  "$HANDOFF_ARCHIVE"
printf '%s  %s\n' 4cd5448ed005c8d1eb759ec80a8a021c23b97bf4d030bd880124e9f6043175b9 "$HANDOFF_ARCHIVE" | sha256sum -c -
install -d -o root -g root -m 0700 "$HANDOFF_PARENT"
tar --extract --gzip --file="$HANDOFF_ARCHIVE" --directory="$HANDOFF_PARENT" \
  --no-same-owner --no-same-permissions
printf '%s  %s\n' cee25c92548ae07bf3c68a25cb0fea00f2ff54ecbe94421e80368cfa4962629f "$HANDOFF_RELEASE/development_challenge/install_patch.py" | sha256sum -c -
/usr/bin/python3 -I -B "$HANDOFF_RELEASE/development_challenge/install_patch.py" verify \
  --release "$HANDOFF_RELEASE" --manifest "$HANDOFF_MANIFEST"
```

Expected: 21 verified payload files. Review REPORT.md, TESTS.md, runtime.patch
and both installed hash inventories before approving the file transaction.

## 3. Root evidence preservation and file-only installation

```bash
assert_idle
test -f /home/alfred/Alfred/gateway/PAUSE
/usr/bin/python3 -I -B - <<'PY'
import hashlib, json, stat
from pathlib import Path
root = Path('/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003')
p = root / 'development-challenge.attempt.json'
s = p.lstat()
assert stat.S_ISREG(s.st_mode) and s.st_uid == 0 and s.st_nlink == 1
assert json.loads(p.read_bytes()) == {'stage':'development-challenge','status':'uncertain_until_result'}
assert not (root / 'development-challenge.result.json').exists()
c = root / 'context.json'
assert hashlib.sha256(c.read_bytes()).hexdigest() == 'bda345a14ec110cf5b3118d7289204c304ba13795f9c9677351aa940d0ab198e'
ctx = json.loads(c.read_bytes())
assert ctx['baseline_revision'] == '596d91daf3311ad3aa0ee42e7220f699f58daf59'
assert ctx['scope'] == ['calculator.py','test_calculator.py']
plan = Path('/home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json')
assert hashlib.sha256(plan.read_bytes()).hexdigest() == ctx['plan_sha256'] == 'e5b58519eb9943c7b9d093b19880c4a0c881dc5a2491c6e1c68b70ff10f032d6'
assert hashlib.sha256(Path(ctx['spec_path']).read_bytes()).hexdigest() == '2474942d42eef568c150fda9da76601fe4b3bcd946546a22ca9ec6eeeaf22f58'
grants = Path('/var/lib/alfred-development-grants')
assert not list(grants.glob('pending-*.json'))
assert not list(grants.glob('publication-pending-*.json'))
print('T-0003 remains held; frozen evidence verified; no approval issued')
PY
test ! -e "$HANDOFF_PARENT/preserved.sha256"
find /var/lib/alfred-v1-handoffs /var/lib/alfred-development-grants \
  -type f -print0 | sort -z | xargs -0 sha256sum > "$HANDOFF_PARENT/preserved.sha256"
sha256sum \
  /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json \
  /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo/.dev/tasks/T-0003-add-calculator-multiply-helper-dev-v1.md \
  /opt/alfred-developer-v1/active \
  /etc/alfred-fresh-v1/policy.json \
  /home/alfred/Alfred/gateway/v1-1-intake.json >> "$HANDOFF_PARENT/preserved.sha256"
/usr/bin/python3 -I -B "$HANDOFF_RELEASE/development_challenge/install_patch.py" install \
  --release "$HANDOFF_RELEASE" --manifest "$HANDOFF_MANIFEST" --backup "$HANDOFF_BACKUP"
```

Expected `INSTALLED_HELD`, `retry_authorized: false`, `service_action: none`.
Only the seven mapped files change, with original UID/GID/mode retained. All are
backed up and fsynced before any runtime replacement. A write exception restores
the complete code backup. A hard interruption requires explicit rollback below.
The Developer activation marker is never removed. No permissions or policy are
changed to accommodate a failed preflight. Grant/QA/Reviewer/Publisher/notification
data, credentials and every original attempt are outside the mapping.

## 4. Post-install verification — no task execution

```bash
sha256sum -c "$HANDOFF_RELEASE/development_challenge/installed-after.sha256"
( cd /opt/alfred-developer-v1 && sha256sum -c developer_v1/release.sha256 )
sha256sum -c "$HANDOFF_PARENT/preserved.sha256"
/usr/bin/python3 -I -B - <<'PY'
import ast
from pathlib import Path
for p in (
    '/usr/local/lib/alfred-v1.1/trusted_intake.py',
    '/opt/alfred-developer-v1/developer_v1/owner_grants.py',
    '/opt/alfred-developer-v1/developer_v1/stage_approval.py',
    '/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py',
): ast.parse(Path(p).read_bytes())
print('Runtime syntax verified without executing any entrypoint')
PY
assert_idle
test -f /home/alfred/Alfred/gateway/PAUSE
```

**Stop here unless activation maintenance is separately authorized.** Do not call
the live issuer, a worker, a planning operation or a mocked fixture on production
to test installation. Existing process memory still contains the previous code.

## 5. Separate activation maintenance decision

Loading the two changed long-running processes requires Intake and Photon
restart. **The installed Hermes unit Requires=alfred-photon.service, so systemd
propagates Photon restart to Hermes.** Approval must explicitly cover this impact
and no in-flight messaging/approval. Do not use ignore-dependencies, change unit
relationships, or claim an Intake-only activation. If Hermes restart is disallowed,
leave the overlay staged/installed under PAUSE and stop before activation.

Only after that separate decision:

```bash
assert_idle
test -f /home/alfred/Alfred/gateway/PAUSE
systemctl show alfred-hermes.service -p Requires -p ActiveState
systemctl restart alfred-development-intake.service alfred-photon.service
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl show alfred-development-intake.service alfred-photon.service alfred-hermes.service \
  -p Id -p User -p Group -p MainPID -p ExecMainStartTimestamp
sha256sum -c "$HANDOFF_RELEASE/development_challenge/installed-after.sha256"
sha256sum -c "$HANDOFF_PARENT/preserved.sha256"
test -f /home/alfred/Alfred/gateway/PAUSE
```

No daemon-reload or Gateway/Evidence restart is needed. If any unit is unhealthy,
keep PAUSE and investigate/roll back under the approved maintenance; do not send
messages or change credentials as a probe. Keep PAUSE after verification. A later
separate operator decision may permit one genuine fresh owner request through the
existing Gateway and timers. T-0003's original attempt is skipped, not replayed,
reconciled or marked complete. No owner approval is backfilled.

## Code-only rollback

In a root shell, re-establish the same PAUSE/idle/quiescence conditions and define
`assert_idle` as above. Use the original protected release and backup. Never
restore task data from a backup or delete modern send intents/receipts/grants.

```bash
set -euo pipefail
test "$(id -u)" = 0
HANDOFF_PARENT=/root/alfred-fresh-v1-development-handoff-1-review
HANDOFF_RELEASE="$HANDOFF_PARENT/alfred-fresh-v1-1.0.1-development-handoff.1"
HANDOFF_BACKUP=/root/alfred-fresh-v1-development-handoff-1-backup
test -f /home/alfred/Alfred/gateway/PAUSE
assert_idle
printf '%s  %s\n' cee25c92548ae07bf3c68a25cb0fea00f2ff54ecbe94421e80368cfa4962629f "$HANDOFF_RELEASE/development_challenge/install_patch.py" | sha256sum -c -
printf '%s  %s\n' 3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492 /usr/local/lib/alfred-fresh-v1/fresh_v1/upgrade.py | sha256sum -c -
/usr/bin/python3 -I -B "$HANDOFF_RELEASE/development_challenge/install_patch.py" rollback \
  --backup "$HANDOFF_BACKUP"
/usr/bin/python3 -I -B - "$HANDOFF_RELEASE/development_challenge/installed-sha256.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
for name, expected in json.loads(Path(sys.argv[1]).read_bytes()).items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
print('Original installed runtime/dependency hashes restored')
PY
( cd /opt/alfred-developer-v1 && sha256sum -c developer_v1/release.sha256 )
sha256sum -c "$HANDOFF_PARENT/preserved.sha256"
test -f /home/alfred/Alfred/gateway/PAUSE
```

Expected `ROLLED_BACK_HELD`. Repeatable rollback restores only the seven files;
activation, policy, credentials and all historical/new evidence remain untouched.
If new runtime had loaded, loading restored code requires the same separately
approved Intake/Photon maintenance and its Hermes dependency impact. If none had
loaded, no restart is required. Retain backup and PAUSE.

**After any live use**, this preservation baseline includes only pre-install
evidence. Never use it to reset later records. The older Intake will not adopt a
modern ACK-only receipt without its pending index, and the old issuer lacks the
new send-intent protection. Existing root uncertain-attempt guards remain, but
do not unpause or manually stage a previously attempted task on the old runtime.
Leave such tasks held until separately reviewed. No rollback clears a send slot,
fabricates a result, reissues a challenge or alters approval/QA/Reviewer evidence.
