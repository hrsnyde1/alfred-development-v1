# Reviewed host procedure: V1.0.1 planning fix.1

**Review only. Nothing in this procedure has been run against production.**
Installing code and authorizing T-0003 recovery are separate decisions. Keep the
task's original uncertain attempt and all existing evidence. This package adds no
recovery override and cannot cause that attempt to replay.

## Pins and scope

- Archive: `alfred-fresh-v1-1.0.1-planning-fix.1.tar.gz`
- Archive SHA-256: `a0d47865f0722f40cd4196e9a218e541a8eb154f982757a6a0c457dd7c450194`
- Manifest SHA-256: `6c65817bf16cc53c4dc91c87743e78f1cba88086db2c0a124a04d3b1c935413d`
- Installer SHA-256: `0cb7bc116ec83739361ce233530ca6297ee1dbd08a7fa99f5e400c501030230c`

Only `/usr/local/lib/alfred-fresh-v1/fresh_v1/{diagnostics,role,host}.py`
are installed. The other seven inventoried files are review/tests/evidence.
The utility uses the existing, unchanged, pinned V1 file-transaction primitives.
It does not invoke the original broad V1 installer.

## Preconditions for a later authorized installation

1. Operator approval for this code upgrade; root-owned release/backup paths.
2. Establish the existing Gateway PAUSE through the normal operator procedure.
   Preserve an already existing PAUSE. Leave it in place after this installation.
3. Wait for existing Evidence/Developer/QA/Reviewer/Publisher work to finish.
   Fresh role workers (including Publisher and completion) are children of the
   Evidence oneshot. Require its explicit `inactive/dead` state and zero main
   and control PIDs; `is-active` alone misses an `activating` oneshot. Also check
   the existing Gateway and legacy execution/QA services listed below. Confirm
   no separately started manual worker remains. Do not kill a worker.
4. Confirm installed V1.0.1 base hashes and protected library parent ownership.
   The transaction enforces host/role/protected/handoffs/upgrade hashes, a valid
   existing Developer activation marker and a present PAUSE. It refuses an
   already present/unexpected diagnostics.py.
5. Preserve original T-0003 files and hashes in the operator incident record.
   No chmod/setfacl of the canonical policy is needed or permitted by this patch.

## Installation commands — after separate authorization

Run in a root shell. Use a new backup directory; do not reuse an old transaction.

```bash
set -eu
umask 077
PATCH_NAME=alfred-fresh-v1-1.0.1-planning-fix.1
PATCH_ARCHIVE=/root/alfred-fresh-v1-1.0.1-planning-fix.1.tar.gz
PATCH_PARENT=/root/alfred-fresh-v1-planning-fix-1-review
PATCH_RELEASE="$PATCH_PARENT/$PATCH_NAME"
PATCH_BACKUP=/root/alfred-fresh-v1-planning-fix-1-backup
PATCH_MANIFEST=6c65817bf16cc53c4dc91c87743e78f1cba88086db2c0a124a04d3b1c935413d

# Establish PAUSE only after the separate installation decision. Never truncate
# or replace an existing PAUSE. This leaves the existing marker's bytes intact.
/usr/bin/python3 -I -B - <<'PY'
import os, stat
from pathlib import Path
p = Path('/home/alfred/Alfred/gateway/PAUSE')
try:
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
except FileExistsError:
    if not stat.S_ISREG(p.lstat().st_mode):
        raise SystemExit('PAUSE must be an existing regular file')
else:
    os.fsync(fd)
    os.close(fd)
    fd = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY)
    os.fsync(fd)
    os.close(fd)
PY

assert_workers_idle() {
  for unit in alfred-development-evidence.service alfred-development-gateway.service \
      alfred-dev-executor.service alfred-dev-qa-runner.service \
      alfred-dev-qa-snapshot.service alfred-dev-qa-auth.service; do
    test "$(systemctl show "$unit" -p ActiveState --value)" = inactive
    test "$(systemctl show "$unit" -p SubState --value)" = dead
    test "$(systemctl show "$unit" -p MainPID --value)" = 0
    test "$(systemctl show "$unit" -p ControlPID --value)" = 0
  done
}
assert_workers_idle

test ! -e "$PATCH_ARCHIVE"
test ! -e "$PATCH_PARENT"
test ! -e "$PATCH_BACKUP"
install -o root -g root -m 0600 \
  /home/alfred/alfred-development-lab/milestone2/task-a/dist/alfred-fresh-v1-1.0.1-planning-fix.1.tar.gz \
  "$PATCH_ARCHIVE"
printf '%s  %s\n' a0d47865f0722f40cd4196e9a218e541a8eb154f982757a6a0c457dd7c450194 "$PATCH_ARCHIVE" | sha256sum -c -
install -d -o root -g root -m 0700 "$PATCH_PARENT"
tar --extract --gzip --file="$PATCH_ARCHIVE" --directory="$PATCH_PARENT" \
  --no-same-owner --no-same-permissions
printf '%s  %s\n' 0cb7bc116ec83739361ce233530ca6297ee1dbd08a7fa99f5e400c501030230c "$PATCH_RELEASE/fresh_v1_planning_patch.py" | sha256sum -c -
/usr/bin/python3 -I -B "$PATCH_RELEASE/fresh_v1_planning_patch.py" verify \
  --release "$PATCH_RELEASE" --manifest "$PATCH_MANIFEST"

# Store private, read-only preservation checks outside the task evidence tree.
PRESERVE_FILES=(
  /etc/alfred-fresh-v1/policy.json
  /opt/alfred-developer-v1/active
  /var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/job.json
  /var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/plan.attempt.json
  /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json
)
test "$(stat -c '%u:%g:%a' /etc/alfred-fresh-v1/policy.json)" = 0:0:600
sha256sum "${PRESERVE_FILES[@]}" > "$PATCH_PARENT/preserved.sha256"
stat -c '%u:%g:%a:%h:%s:%Y:%n' "${PRESERVE_FILES[@]}" > "$PATCH_PARENT/preserved.stat"
getfacl -p "${PRESERVE_FILES[@]}" > "$PATCH_PARENT/preserved.acl"
test -f /home/alfred/Alfred/gateway/PAUSE
assert_workers_idle
/usr/bin/python3 -I -B "$PATCH_RELEASE/fresh_v1_planning_patch.py" install \
  --release "$PATCH_RELEASE" --manifest "$PATCH_MANIFEST" --backup "$PATCH_BACKUP"
```

Expected: `INSTALLED_HELD`, `service_action: none`.

Verify only the installed code, without invoking a role or poll:

```bash
printf '%s  %s\n' \
  162d553df4512e235ba9a0a8ab8adb4187dde2a140c9c728c6e41c0958647954 /usr/local/lib/alfred-fresh-v1/fresh_v1/host.py \
  99d43e22ace57b1cf4f97972e2e3755a8a2269d66f53f9078220b859407cd109 /usr/local/lib/alfred-fresh-v1/fresh_v1/role.py \
  c5862c14b39b22b7e6faef07aea1d4c32b5ab0df20aab987d4a0fed33b763e0e /usr/local/lib/alfred-fresh-v1/fresh_v1/diagnostics.py | sha256sum -c -
test "$(stat -c '%u:%g:%a' /etc/alfred-fresh-v1/policy.json)" = 0:0:600
test "$(stat -c '%u:%a' /opt/alfred-developer-v1/active)" = 0:644
test -f /home/alfred/Alfred/gateway/PAUSE
```

Run these preservation checks after installation **and after any rollback**.
They work in a new root Bash shell and do not invoke a worker:

```bash
set -eu
PATCH_PARENT=/root/alfred-fresh-v1-planning-fix-1-review
PRESERVE_FILES=(
  /etc/alfred-fresh-v1/policy.json
  /opt/alfred-developer-v1/active
  /var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/job.json
  /var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/plan.attempt.json
  /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json
)
sha256sum -c "$PATCH_PARENT/preserved.sha256"
stat -c '%u:%g:%a:%h:%s:%Y:%n' "${PRESERVE_FILES[@]}" | cmp "$PATCH_PARENT/preserved.stat" -
getfacl -p "${PRESERVE_FILES[@]}" | cmp "$PATCH_PARENT/preserved.acl" -
for name in plan.result.json context.json worker-policy.json plan.failure.json; do
  test ! -e "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/$name"
done
```

Retain PAUSE, the private backup, incident evidence and the pinned archive. Do
not call host.poll, role.main, gh fetch, a challenge issuer, or any live worker
as an installation check. No daemon-reload or service restart is necessary:
no unit/configuration or long-running worker code changes; the existing Evidence
oneshot loads the files on later invocations. Releasing PAUSE or recovering a
task requires a separate operator decision. T-0003 remains blocked by its attempt.

## Rollback commands — after separate authorization

Require PAUSE and idle workers again. Use the same root-owned extracted package
and original backup. The installer retains every original byte, owner, group
and mode before the first mutation. It restores automatically on ordinary partial
failure; explicit rollback handles interruption or failed recovery.

```bash
set -eu
PATCH_RELEASE=/root/alfred-fresh-v1-planning-fix-1-review/alfred-fresh-v1-1.0.1-planning-fix.1
PATCH_BACKUP=/root/alfred-fresh-v1-planning-fix-1-backup
test -f /home/alfred/Alfred/gateway/PAUSE
for unit in alfred-development-evidence.service alfred-development-gateway.service \
    alfred-dev-executor.service alfred-dev-qa-runner.service \
    alfred-dev-qa-snapshot.service alfred-dev-qa-auth.service; do
  test "$(systemctl show "$unit" -p ActiveState --value)" = inactive
  test "$(systemctl show "$unit" -p SubState --value)" = dead
  test "$(systemctl show "$unit" -p MainPID --value)" = 0
  test "$(systemctl show "$unit" -p ControlPID --value)" = 0
done
printf '%s  %s\n' 0cb7bc116ec83739361ce233530ca6297ee1dbd08a7fa99f5e400c501030230c "$PATCH_RELEASE/fresh_v1_planning_patch.py" | sha256sum -c -
/usr/bin/python3 -I -B "$PATCH_RELEASE/fresh_v1_planning_patch.py" rollback \
  --backup "$PATCH_BACKUP"
printf '%s  %s\n' \
  86267e1615454475dbca30708d912c7a333c796ea9bfc0d95d1d721000aaa03b /usr/local/lib/alfred-fresh-v1/fresh_v1/host.py \
  0817a393b47a991831d88fde4935f425620971f55468eb0ea7d42cdd2a497a0f /usr/local/lib/alfred-fresh-v1/fresh_v1/role.py | sha256sum -c -
test ! -e /usr/local/lib/alfred-fresh-v1/fresh_v1/diagnostics.py
```

Expected: `ROLLED_BACK_HELD`, `service_action: none`. Keep PAUSE. Rollback
restores the prior defect, so it does not authorize resuming a fresh task. Run
the preservation checks above after rollback; retain the original private backup.

Neither installation nor rollback changes or removes activation, canonical
policy, T-0003's attempt/preliminary plan, grants, approvals, QA/Reviewer evidence,
Publisher ERROR/success results, publication plans, credentials or delivery
tracking. Newly created job inputs/failure diagnostics, if any later authorized
operation creates them, are also retained across rollback. Do not reset evidence
to make old code run.
