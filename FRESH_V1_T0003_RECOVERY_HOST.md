# Reviewed T-0003 recovery commands

**Review only: no production command below has been executed.** Keep Gateway
PAUSE throughout. Installation, a root planning-recovery decision, and eventual
release of PAUSE require separate operator decisions. No service restart is needed.
Review `FRESH_V1_T0003_RECOVERY.md` first, including preservation of the original
preliminary version while normal CTO planning later advances its canonical path.

## 1. Root read-only preflight

Use a root Bash shell. Use the actual prior protected preservation baseline if
the operator chose another directory; do not replace an absent baseline with a
newly invented one. Failure means stop, without chmod/chown/setfacl or retries.

```bash
set -euo pipefail
test "$(id -u)" = 0
test -f /home/alfred/Alfred/gateway/PAUSE
sha256sum -c /root/alfred-fresh-v1-planning-fix-1-review/preserved.sha256
/usr/bin/python3 -I -B - <<'PY'
import hashlib, json, os, stat
from pathlib import Path
root = Path('/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003')
assert sorted(p.name for p in root.iterdir()) == ['job.json', 'plan.attempt.json']
attempt = root / 'plan.attempt.json'
info = attempt.lstat()
assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
raw = attempt.read_bytes()
assert json.loads(raw) == {'stage': 'plan', 'status': 'uncertain_until_result'}
policy = Path('/etc/alfred-fresh-v1/policy.json')
p = policy.lstat()
assert stat.S_ISREG(p.st_mode) and (p.st_uid, p.st_gid, stat.S_IMODE(p.st_mode)) == (0, 0, 0o600)
assert p.st_ctime_ns <= info.st_mtime_ns
assert 'system.posix_acl_access' not in os.listxattr(policy)
print(json.dumps({'original_attempt_sha256': hashlib.sha256(raw).hexdigest(), 'state': 'verified_held'}))
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
```

Confirm manual workers are also idle. Fresh role workers are children of the
existing Evidence oneshot. Do not interrupt an active worker.

## 2. Install extension — only after installation approval

Only three runtime destinations change: root-owned fresh_v1/recovery.py, host.py
and handoffs.py. The installer requires installed planning fix.1, PAUSE, a valid
Developer activation marker, pinned source and a new private backup. It does not
change policy, evidence, credentials, activation or service configuration.

```bash
umask 077
RECOVERY_NAME=alfred-fresh-v1-1.0.1-T0003-recovery.1
RECOVERY_ARCHIVE=/root/alfred-fresh-v1-1.0.1-T0003-recovery.1.tar.gz
RECOVERY_PARENT=/root/alfred-fresh-v1-T0003-recovery-1-review
RECOVERY_RELEASE="$RECOVERY_PARENT/$RECOVERY_NAME"
RECOVERY_BACKUP=/root/alfred-fresh-v1-T0003-recovery-1-backup
RECOVERY_MANIFEST=267a8d279a61c9d288ef23df860efc23c9d8b0989b5e6f925aeecd5c0ced1bc3
test ! -e "$RECOVERY_ARCHIVE"
test ! -e "$RECOVERY_PARENT"
test ! -e "$RECOVERY_BACKUP"
install -o root -g root -m 0600 \
  /home/alfred/alfred-development-lab/milestone2/task-a/dist/alfred-fresh-v1-1.0.1-T0003-recovery.1.tar.gz \
  "$RECOVERY_ARCHIVE"
printf '%s  %s\n' f6740a605e99d80131d020b0243b019cf8ca13f6dbdf3c9ef60c6a48fdbe1bca "$RECOVERY_ARCHIVE" | sha256sum -c -
install -d -o root -g root -m 0700 "$RECOVERY_PARENT"
tar --extract --gzip --file="$RECOVERY_ARCHIVE" --directory="$RECOVERY_PARENT" \
  --no-same-owner --no-same-permissions
printf '%s  %s\n' d697f535f0160619ae68f41576f32b46317ed580ddf63a55a8a7373561f5f0dd "$RECOVERY_RELEASE/fresh_v1_recovery_patch.py" | sha256sum -c -
/usr/bin/python3 -I -B "$RECOVERY_RELEASE/fresh_v1_recovery_patch.py" verify \
  --release "$RECOVERY_RELEASE" --manifest "$RECOVERY_MANIFEST"
assert_idle
test -f /home/alfred/Alfred/gateway/PAUSE
/usr/bin/python3 -I -B "$RECOVERY_RELEASE/fresh_v1_recovery_patch.py" install \
  --release "$RECOVERY_RELEASE" --manifest "$RECOVERY_MANIFEST" --backup "$RECOVERY_BACKUP"
printf '%s  %s\n' \
  9cb19786ec25b87de5012704fb739b7c8bce9bacdad38469c41b774909ce2b73 /usr/local/lib/alfred-fresh-v1/fresh_v1/host.py \
  09568b8de620b61c28dbf4c4a3be824c7e4eecd3800aaa47d6858a13ad066ebb /usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py \
  d6e3f3627f5f6c82223fe16dab7ef43d619cda4d98c4edf99467a76c0df688c4 /usr/local/lib/alfred-fresh-v1/fresh_v1/recovery.py | sha256sum -c -
sha256sum -c /root/alfred-fresh-v1-planning-fix-1-review/preserved.sha256
```

Expected `INSTALLED_HELD`. No reload/restart, timer trigger, planner or poll call.

## 3. Inspect actual root-private evidence; review and pin

```bash
test ! -e "$RECOVERY_PARENT/inspection.json"
/usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0,"/usr/local/lib/alfred-fresh-v1"); from fresh_v1.recovery import main; main()' \
  inspect > "$RECOVERY_PARENT/inspection.json"
sha256sum "$RECOVERY_PARENT/inspection.json"
cat "$RECOVERY_PARENT/inspection.json"
```

This writes no task evidence. Compare its job/spec/route/preliminary hashes with
the reviewed incident report. Any refusal or mismatch means stop and investigate.

## 4. Append decision — only after explicit recovery approval

Approve **one new planning attempt and normal separately approved flow**.
Enter the actual operator approval/change-record reference; do not synthesize an
owner event or use a placeholder. This appends only the preserved preliminary
bytes and root decision; it executes no role and issues no approval or grant.

```bash
assert_idle
test -f /home/alfred/Alfred/gateway/PAUSE
read -r -p 'Actual operator recovery-decision reference: ' OPERATOR_REFERENCE
INSPECTION_SHA=$(sha256sum "$RECOVERY_PARENT/inspection.json")
INSPECTION_SHA=${INSPECTION_SHA%% *}
/usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0,"/usr/local/lib/alfred-fresh-v1"); from fresh_v1.recovery import main; main()' \
  authorize --inspection-sha256 "$INSPECTION_SHA" --operator-reference "$OPERATOR_REFERENCE"
/usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0,"/usr/local/lib/alfred-fresh-v1"); from fresh_v1.recovery import main; main()' verify
sha256sum -c /root/alfred-fresh-v1-planning-fix-1-review/preserved.sha256
cmp /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json \
  /var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/plan-recovery-1.preliminary.json
for name in plan-recovery-1.attempt.json plan-recovery-1.result.json context.json; do
  test ! -e "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003/$name"
done
test -f /home/alfred/Alfred/gateway/PAUSE
```

Expected `ONE_PLANNING_RECOVERY_AUTHORIZED_HELD`, then
`RECOVERY_EVIDENCE_VERIFIED_NO_EXECUTION`. **Stop with PAUSE retained.**
A later separate decision may release it through the existing operator procedure
within the unused decision's one-hour lifetime. The existing timer then handles
planning and native owner approval; do not manually invoke agents or inject tasks.
If the new attempt becomes uncertain or the unused decision expires, keep the
evidence and stop. No timestamp edits, replacement decisions or automatic retries.

## Code-only rollback — PAUSE retained, all evidence retained

Repeat step 1's `assert_idle` definition/check in a new root shell. Do not restore
the preliminary plan over a genuine subsequent CTO plan or approval evidence.

```bash
set -euo pipefail
RECOVERY_RELEASE=/root/alfred-fresh-v1-T0003-recovery-1-review/alfred-fresh-v1-1.0.1-T0003-recovery.1
RECOVERY_BACKUP=/root/alfred-fresh-v1-T0003-recovery-1-backup
test -f /home/alfred/Alfred/gateway/PAUSE
assert_idle
printf '%s  %s\n' d697f535f0160619ae68f41576f32b46317ed580ddf63a55a8a7373561f5f0dd "$RECOVERY_RELEASE/fresh_v1_recovery_patch.py" | sha256sum -c -
/usr/bin/python3 -I -B "$RECOVERY_RELEASE/fresh_v1_recovery_patch.py" rollback --backup "$RECOVERY_BACKUP"
printf '%s  %s\n' \
  162d553df4512e235ba9a0a8ab8adb4187dde2a140c9c728c6e41c0958647954 /usr/local/lib/alfred-fresh-v1/fresh_v1/host.py \
  4a0ee3c9efeb3a2ef23368d4359d5a23162cfdfd0e17ab1fa94d97df9e1bcb9c /usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py | sha256sum -c -
test ! -e /usr/local/lib/alfred-fresh-v1/fresh_v1/recovery.py
```

Expected `ROLLED_BACK_HELD`. Original/recovery attempts, decisions, preserved
preliminary bytes, new results/plans, all approvals, QA/Reviewer evidence,
credentials, notification tracking and historical T-0001/T-0002 artifacts remain.
The restored handoff holds on the untouched original attempt. Retain backup and
PAUSE; do not reset evidence to make old code run.
