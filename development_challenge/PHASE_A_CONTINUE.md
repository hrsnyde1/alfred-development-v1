# Resume interrupted Phase A only

## Status and stopping condition

**Continuation prepared and tested; host Phase A completion is not verified.**
No command below has been executed on the host by this session.

The original script prints the 21-file verification result before its second
worker-idle check, PAUSE check, frozen T-0003/approval preflight, and baseline
creation. A missing `preserved.sha256` narrows the interruption to that interval
(including failure to open the output file). It does **not** identify a unique
failed assertion. The original terminal error or trace is still needed to
establish the historical stopping condition. Do not attribute it to a timeout,
permission problem, or evidence mismatch without that evidence.

The session cannot read `/root` and `sudo -n -l` requires a password. No attempt
was made to bypass that boundary. The readable T-0003 context, CTO plan and spec
hashes still match their pins; all six execution services were observed
inactive/dead with MainPID and ControlPID zero. These observations cannot
replace root verification of the protected files.

**Confirmed replay blocker:** rerunning `PHASE_A_PREPARE.sh` now necessarily
stops at its existing-protected-path guard. The archive/review directory already
exist. Keep that guard and those files intact. The continuation does not invoke
the original script, copy/extract the package again, or retry a failed task.

## Continuation contract

`phase_a_continue.py` is a separate operator preparation aid, outside the frozen
release. Its SHA-256 is:

```text
c5b088b4e378f247c4df2e4018e943768591b2ca4c12beb820339076d7e1a08b
```

Before any evidence write it verifies:

1. Existing PAUSE, and all six Gateway/Evidence/specialist execution services
   inactive/dead with both PIDs zero. It never changes timers or services.
2. Root ownership/protection and pinned bytes of the existing original script,
   archive, extracted manifest and all 21 payload files. Archive/extracted file
   inventory and bytes must agree exactly. Installer pin is checked separately;
   the installation backup path must still be absent.
3. Original T-0003 planning/challenge attempts, including their previously
   observed sizes and nanosecond mtimes; exact context, CTO plan, canonical spec,
   frozen baseline and scope; recovered planning result bound to context;
   absent challenge result; protected grant store; no pending owner approval or
   T-0003 approval evidence. Request-route records remain permitted.
4. All 14 installed runtime/dependency pins, all 29 Developer manifest entries,
   the root-owned 0644 activation marker, and root-owned 0600 canonical policy
   still enabled for the same project and destination.
5. Two equal snapshots of the original host-contract preservation set: all
   handoff/grant files, T-0003 CTO plan/spec, activation marker, canonical policy
   and Intake configuration. Every pre-existing file remains unchanged.

Only then it writes a private temporary checksum file, fsyncs it and atomically
publishes `preserved.sha256` using Linux `renameat2(RENAME_NOREPLACE)`, followed
by a directory fsync. It repeats all verification after publication. An existing
baseline is verified byte for byte and never replaced, appended to or chmodded.
Interrupted runs can therefore resume without creating a second baseline.
Unrelated pre-existing temporary files are retained. Only the current run's own
unpublished temporary is cleaned up.

Any failed check exits nonzero with `BLOCKED: <checkpoint>` and no success
status. Errors name paths/checkpoints or exception classes/errno; they never
print evidence JSON, credentials or subprocess output. A failure after atomic
publication retains the baseline for verification on a later explicitly chosen
continuation. No automatic retry occurs. A conflicting baseline or any pinned
file drift requires investigation; do not delete it or repin it to pass.

## One root-operator command

First review the original failure output if available. Independently confirm
there is no in-flight approval send, pending owner conversation or unfiled
confirmation. Filesystem/service checks alone cannot prove Intake's in-memory
conversation state is empty. **Executing this command asserts that operator
confirmation.** Keep PAUSE active throughout.

Run this single command in a root shell. It copies only the pinned continuation
aid into a new root-private file, or verifies an identical existing copy; it
never overwrites an existing file. It then runs the continuation's read-only
preflights before the one permitted evidence-baseline publication.

```bash
/usr/bin/python3 -I -B - <<'PY'
import hashlib, os, stat
from pathlib import Path

if os.geteuid() != 0:
    raise SystemExit('BLOCKED: root_operator_required')
os.umask(0o077)
expected = 'c5b088b4e378f247c4df2e4018e943768591b2ca4c12beb820339076d7e1a08b'
source = Path('/home/alfred/alfred-development-lab/milestone2/task-a/development_challenge/phase_a_continue.py')
destination = Path('/root/alfred-fresh-v1-phase-a-continue.py')
raw = source.read_bytes()
if hashlib.sha256(raw).hexdigest() != expected:
    raise SystemExit('BLOCKED: continuation_source_sha256')
try:
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
except FileExistsError:
    pass
else:
    with os.fdopen(fd, 'wb') as output:
        os.fchown(output.fileno(), 0, 0)
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    directory = os.open('/root', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
info = destination.lstat()
if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        and info.st_uid == info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o600):
    raise SystemExit('BLOCKED: existing_continuation_protection')
if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
    raise SystemExit('BLOCKED: existing_continuation_sha256; preserve and investigate')
os.execv('/usr/bin/python3', ['/usr/bin/python3', '-I', '-B', str(destination),
                           '--operator-quiescence-confirmed'])
PY
```

The only successful final line is:

```text
PHASE_A_PREPARED_HELD
```

Return that status or the concise failure checkpoint; do not share private
approval/task bodies. No success means remain held. Even after success, stop
before installation: Phase B installation and Phase C service interruption
still require their separate approvals. T-0003 remains held; nothing here
authorizes replay, approval issuance or worker execution.

## Verification performed in staging

- `tests/test_phase_a_continuation.py`: **31 passed**, using disposable `/tmp`
  host fixtures and mocked read-only systemctl observations. No private live
  approval/attempt contents are copied into fixtures.
- Covers successful preservation, repeat runs without inode/mtime changes,
  original evidence/runtime drift, pending approvals, non-idle workers,
  permissions/ownership, conflicting/concurrent baselines, interruption before
  and after atomic publication, changing evidence, and CLI privilege guards.
- Ruff format/check passed for both new Python files.
- Original preparation script SHA remains
  `dcc6395369f16ae844fea26d131449e688b232943c16843e2a61f3804a0d0edb`.
- Release archive SHA remains
  `4cd5448ed005c8d1eb759ec80a8a021c23b97bf4d030bd880124e9f6043175b9`.
- Release manifest SHA remains
  `4392696cd25bbd38ffbe24972899ccc884041a1a8f19321a118c08154a52bb27`.

These are staging/source checks. The root-protected host copies and installed
inventory remain subject to the command's mandatory checks.
