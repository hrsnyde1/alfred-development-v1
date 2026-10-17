#!/bin/bash
# Phase A only: PAUSE, private release preparation and evidence checksums.
# No installer invocation, service actions, sends, worker calls or task retries.
set -euo pipefail
if test "${1:-}" != --operator-quiescence-confirmed; then
  echo 'Stop: operator must first confirm no in-flight sends, owner approvals or unfiled conversations.' >&2
  exit 2
fi

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

HANDOFF_NAME=alfred-fresh-v1-1.0.1-development-handoff.1
HANDOFF_ARCHIVE=/root/alfred-fresh-v1-1.0.1-development-handoff.1.tar.gz
HANDOFF_PARENT=/root/alfred-fresh-v1-development-handoff-1-review
HANDOFF_RELEASE="$HANDOFF_PARENT/$HANDOFF_NAME"
HANDOFF_BACKUP=/root/alfred-fresh-v1-development-handoff-1-backup
HANDOFF_MANIFEST=4392696cd25bbd38ffbe24972899ccc884041a1a8f19321a118c08154a52bb27
for HANDOFF_PREP_PATH in "$HANDOFF_ARCHIVE" "$HANDOFF_PARENT" "$HANDOFF_BACKUP"; do
  if test -e "$HANDOFF_PREP_PATH" || test -L "$HANDOFF_PREP_PATH"; then
    printf 'Stop: existing protected preparation path requires review; nothing will be overwritten: %s\n' "$HANDOFF_PREP_PATH" >&2
    exit 1
  fi
done
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


# Verify actual root-owned installed files against every pinned baseline/dependency.
/usr/bin/python3 -I -B - "$HANDOFF_RELEASE" <<'PYROOT'
import hashlib,json,os,stat,sys
from pathlib import Path
release=Path(sys.argv[1])
installed=json.loads((release/'development_challenge/installed-sha256.json').read_bytes())
for name,expected in installed.items():
    p=Path(name)
    s=p.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and not s.st_mode & 0o022,name
    for parent in p.parents:
        assert not parent.is_symlink(),str(parent)
    assert hashlib.sha256(p.read_bytes()).hexdigest()==expected,name
manifest=Path('/opt/alfred-developer-v1/developer_v1/release.sha256')
seen=set()
for line in manifest.read_text().splitlines():
    expected,name=line.split('  ',1)
    assert name.startswith('developer_v1/') and '..' not in Path(name).parts and name not in seen
    seen.add(name)
    p=Path('/opt/alfred-developer-v1')/name
    s=p.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and not s.st_mode & 0o022,name
    assert hashlib.sha256(p.read_bytes()).hexdigest()==expected,name
assert len(seen)==29
marker=Path('/opt/alfred-developer-v1/active')
s=marker.lstat()
assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o644
policy=Path('/etc/alfred-fresh-v1/policy.json')
s=policy.lstat()
assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600
policy_data=json.loads(policy.read_bytes())
assert policy_data['enabled'] is True and policy_data['project']=='dev-v1-accept'
assert policy_data['destination']=='hrsnyde1/alfred-dev-v1-acceptance'
print(json.dumps({'installed_pins':len(installed),'developer_inventory':len(seen),'activation_marker':'PASS','policy':'protected_and_unchanged'}))
PYROOT
sha256sum -c "$HANDOFF_PARENT/preserved.sha256"
assert_idle
test -f /home/alfred/Alfred/gateway/PAUSE
test ! -e "$HANDOFF_BACKUP"
printf '%s\n' 'PHASE_A_PREPARED_HELD: release and protected evidence verified; no code installed; no services restarted.'
