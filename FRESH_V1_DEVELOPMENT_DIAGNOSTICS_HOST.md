# Reviewed Intake diagnostic overlay installation and rollback

**Review only. No production command below was executed.** This is a diagnostic
correction, not a proven transport fix or T-0003 recovery authorization. The old
challenge remains held. Do not invoke the issuer, replay the attempt, or remove
PAUSE as part of this procedure. Read the failure and separate recovery reports.

## Artifact and exact mapping

Archive: `dist/alfred-fresh-v1-1.0.1-development-diagnostics.1.tar.gz`

SHA-256: `ed89f15a16b87ea9dd0a661859c7948f4bfe085a4654b52911e3c4824211d31f`

Manifest SHA-256: `14c6c1ba1c1665c8d7e962f2974cfb8e396d7f3daf2d68b36643f4405614f165`

The archive contains 12 payload files plus its manifest. Only these three
destinations can be installed or rolled back:

| Payload | Destination |
| --- | --- |
| developer_v1/trusted_intake_development.py | /usr/local/lib/alfred-v1.1/trusted_intake.py |
| same source | /opt/alfred-developer-v1/developer_v1/trusted_intake_development.py |
| developer_v1/release.sha256 | /opt/alfred-developer-v1/developer_v1/release.sha256 |

The installer reuses the existing, unchanged `fresh_v1.upgrade` file transaction.
It verifies the old source and manifest pins, every old Developer inventory file,
and that only the Intake entry changes in the new inventory. All three files are
backed up before writes; failures during writes restore them. UID/GID/modes and
the Developer activation marker are preserved. Policy, credentials, routes,
attempts, grants, CTO/QA/Reviewer/Publisher evidence and notification tracking are
outside the mapping. The transaction never starts services or workers.

## 1. Explicit installation decision, then PAUSE and idle preflight

Use a root Bash shell only after the operator approves this diagnostic installation.
PAUSE was absent during inspection. Establish it without replacing an existing
marker. Do not stop active workers or disable timers; wait for the existing work
to become idle. Keep PAUSE throughout installation and rollback.

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
    finally:
        os.close(fd)
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

Also confirm manually launched workers are idle. Before any Intake restart,
confirm no unfiled owner request/confirmation or pending approval is in progress;
otherwise defer the restart. PAUSE does not stop Intake receiving owner events.
Any failed precheck means stop; no chmod/chown/setfacl workaround.

## 2. Pin and verify the private review copy

```bash
DIAG_NAME=alfred-fresh-v1-1.0.1-development-diagnostics.1
DIAG_ARCHIVE=/root/alfred-fresh-v1-1.0.1-development-diagnostics.1.tar.gz
DIAG_PARENT=/root/alfred-fresh-v1-development-diagnostics-1-review
DIAG_RELEASE="$DIAG_PARENT/$DIAG_NAME"
DIAG_BACKUP=/root/alfred-fresh-v1-development-diagnostics-1-backup
DIAG_MANIFEST=14c6c1ba1c1665c8d7e962f2974cfb8e396d7f3daf2d68b36643f4405614f165
test ! -e "$DIAG_ARCHIVE"
test ! -e "$DIAG_PARENT"
test ! -e "$DIAG_BACKUP"
install -o root -g root -m 0600 \
  /home/alfred/alfred-development-lab/milestone2/task-a/dist/alfred-fresh-v1-1.0.1-development-diagnostics.1.tar.gz \
  "$DIAG_ARCHIVE"
printf '%s  %s\n' ed89f15a16b87ea9dd0a661859c7948f4bfe085a4654b52911e3c4824211d31f "$DIAG_ARCHIVE" | sha256sum -c -
install -d -o root -g root -m 0700 "$DIAG_PARENT"
tar --extract --gzip --file="$DIAG_ARCHIVE" --directory="$DIAG_PARENT" \
  --no-same-owner --no-same-permissions
printf '%s  %s\n' 267deed11ff02709b6d3afb9ee2954938d19369c53c5c1be9c7055c0ca12e74d "$DIAG_RELEASE/fresh_v1_development_diagnostics_patch.py" | sha256sum -c -
/usr/bin/python3 -I -B "$DIAG_RELEASE/fresh_v1_development_diagnostics_patch.py" verify \
  --release "$DIAG_RELEASE" --manifest "$DIAG_MANIFEST"
```

Expected 12 verified payload files. The archive has no symlinks or special files;
its inventory was independently checked against archive member bytes in staging.

## 3. Root preservation checks, then file transaction

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
spec = Path(ctx['spec_path'])
assert hashlib.sha256(spec.read_bytes()).hexdigest() == '2474942d42eef568c150fda9da76601fe4b3bcd946546a22ca9ec6eeeaf22f58'
grants = Path('/var/lib/alfred-development-grants')
assert not list(grants.glob('pending-*.json'))
print('Frozen evidence verified; no approval or recovery issued')
PY
test ! -e "$DIAG_PARENT/preserved.sha256"
find /var/lib/alfred-v1-handoffs /var/lib/alfred-development-grants \
  -type f -print0 | sort -z | xargs -0 sha256sum > "$DIAG_PARENT/preserved.sha256"
sha256sum \
  /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json \
  /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo/.dev/tasks/T-0003-add-calculator-multiply-helper-dev-v1.md \
  /opt/alfred-developer-v1/active \
  /etc/alfred-fresh-v1/policy.json \
  /home/alfred/Alfred/gateway/v1-1-intake.json >> "$DIAG_PARENT/preserved.sha256"
/usr/bin/python3 -I -B "$DIAG_RELEASE/fresh_v1_development_diagnostics_patch.py" install \
  --release "$DIAG_RELEASE" --manifest "$DIAG_MANIFEST" --backup "$DIAG_BACKUP"
```

Expected `INSTALLED_HELD`, `retry_authorized: false`, `service_action: none`.
If the command fails, keep PAUSE and the backup. A normal exception after writes
triggers rollback; power loss requires explicitly running the rollback below.
The activation marker is never removed, including during partial installation.

## 4. Verify installed bytes; separately approve Intake restart

```bash
printf '%s  %s\n' \
  e7f85b860936a47e1c969757d4ffad5d0f27e708032d14cf749ffc46efdfe910 /usr/local/lib/alfred-v1.1/trusted_intake.py \
  e7f85b860936a47e1c969757d4ffad5d0f27e708032d14cf749ffc46efdfe910 /opt/alfred-developer-v1/developer_v1/trusted_intake_development.py \
  8e4f2e9e71b41d0da44df96f85832d02f0258906a17c5c789322fecdb2bf143f /opt/alfred-developer-v1/developer_v1/release.sha256 | sha256sum -c -
( cd /opt/alfred-developer-v1 && sha256sum -c developer_v1/release.sha256 )
sha256sum -c "$DIAG_PARENT/preserved.sha256"
assert_idle
test -f /home/alfred/Alfred/gateway/PAUSE
```

Only after the separate restart decision and no in-flight Intake exchange:

```bash
systemctl restart alfred-development-intake.service
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl show alfred-development-intake.service -p User -p Group -p MainPID -p ExecMainStartTimestamp
sha256sum -c "$DIAG_PARENT/preserved.sha256"
test -f /home/alfred/Alfred/gateway/PAUSE
```

No daemon-reload is needed. **Do not restart Photon, Hermes, Gateway or any worker.**
Do not stage a challenge to test diagnostics. The static hashes and staging tests
verify the correction; normal future refusals will journal redacted diagnostics.
Stop with PAUSE retained. No permission to recover T-0003 or run a fresh task is
implied by installation or restart approval.

## Code-only rollback

In a new root shell, repeat step 1's `assert_idle` definition/check and verify
Gateway PAUSE. Use the original private release/backup; never recreate evidence.

```bash
set -euo pipefail
test "$(id -u)" = 0
DIAG_PARENT=/root/alfred-fresh-v1-development-diagnostics-1-review
DIAG_RELEASE="$DIAG_PARENT/alfred-fresh-v1-1.0.1-development-diagnostics.1"
DIAG_BACKUP=/root/alfred-fresh-v1-development-diagnostics-1-backup
test -f /home/alfred/Alfred/gateway/PAUSE
assert_idle
printf '%s  %s\n' 267deed11ff02709b6d3afb9ee2954938d19369c53c5c1be9c7055c0ca12e74d "$DIAG_RELEASE/fresh_v1_development_diagnostics_patch.py" | sha256sum -c -
printf '%s  %s\n' 3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492 /usr/local/lib/alfred-fresh-v1/fresh_v1/upgrade.py | sha256sum -c -
/usr/bin/python3 -I -B "$DIAG_RELEASE/fresh_v1_development_diagnostics_patch.py" rollback --backup "$DIAG_BACKUP"
printf '%s  %s\n' \
  d3e1677cb8d7ee17ab801448e85db48fee12d88bbf21a3561e9e755eef742168 /usr/local/lib/alfred-v1.1/trusted_intake.py \
  d3e1677cb8d7ee17ab801448e85db48fee12d88bbf21a3561e9e755eef742168 /opt/alfred-developer-v1/developer_v1/trusted_intake_development.py \
  c23cb89acc0ddc17fe382c4ea3e985c8404ebbf2dace1d20bbad19da81fa9edd /opt/alfred-developer-v1/developer_v1/release.sha256 | sha256sum -c -
( cd /opt/alfred-developer-v1 && sha256sum -c developer_v1/release.sha256 )
sha256sum -c "$DIAG_PARENT/preserved.sha256"
test -f /home/alfred/Alfred/gateway/PAUSE
```

Expected `ROLLED_BACK_HELD`. If Intake had loaded the overlay, a separately
approved restart of **only Intake**, with the same no-in-flight-exchange checks,
loads the restored source. Repeat the preservation checks afterward. If it had
not loaded the overlay, no restart is required. Retain backup and PAUSE. All
task/approval/QA/Reviewer/Publisher/notification evidence remains in place;
rollback changes exactly the three mapped code/inventory files.
