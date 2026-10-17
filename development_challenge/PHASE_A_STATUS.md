# Phase A — final deployment preparation

## Status: BLOCKED before installation approval

Read-only checks passed during this preparation pass, beginning at
2026-10-16 23:52 UTC.
The session runs as alfred (UID 1000); `sudo -n -l` returns
`sudo: a password is required`. Root-protected release preparation and evidence
checksumming have therefore **not** been performed. No privilege, credential or
permission change is proposed to bypass that boundary.

An operator must also confirm there is no in-flight owner conversation, unfiled
confirmation or message send requiring preservation. The available read-only
interfaces do not expose Intake's in-memory conversation state. Empty socket and
pending-record observations alone cannot prove that state is empty.

## Verified actual host state

- Existing Gateway PAUSE is present and was preserved. Its observed UID/GID are
  1000/1000, mode 0664, size zero, mtime_ns `1792194527082105726`. No chmod,
  chown, replacement or timestamp change was performed.
- All six existing execution services were checked twice: inactive/dead, with
  MainPID and ControlPID zero. No specialist-identity processes or role/model
  worker candidates under alfred were found.
- Intake PID 439206, Photon PID 140714 and Hermes PID 454732 remain active. Their
  start times are unchanged. Hermes still Requires=alfred-photon.service.
- Gateway and Evidence timers remain active. Evidence journal reports `paused`
  at 23:49:36, 23:51:37 and 23:53:42 UTC. No timer was triggered or reconfigured.
- No pending development/publication records or modern development send intents.
  Two existing development grant records remain. Intake showed its listening
  socket, no accepted connection and no outbound HTTP socket at inspection.
- Archive SHA-256 matches
  `4cd5448ed005c8d1eb759ec80a8a021c23b97bf4d030bd880124e9f6043175b9`.
- Extracted manifest SHA-256 matches
  `4392696cd25bbd38ffbe24972899ccc884041a1a8f19321a118c08154a52bb27`;
  exactly 21 payload files plus manifest, with no special members/path escapes.
- Installer SHA-256 matches
  `cee25c92548ae07bf3c68a25cb0fea00f2ff54ecbe94421e80368cfa4962629f`.
- All seven installed destination hashes and seven unchanged dependency pins
  match the release's original host contract. All 29 installed Developer files
  match the current pinned manifest.
- Developer activation marker remains root:root 0644. Canonical policy remains
  root:root 0600. Grant store remains alfred:alfred 0700. No permissions changed.
- T-0003 readable CTO plan and context hashes remain respectively
  `e5b58519eb9943c7b9d093b19880c4a0c881dc5a2491c6e1c68b70ff10f032d6` and
  `bda345a14ec110cf5b3118d7289204c304ba13795f9c9677351aa940d0ab198e`.
  Original planning/challenge attempt sizes and nanosecond mtimes match the
  reviewed baseline. Their root-private bytes still require the operator check.

The archive retains the previously verified 176 Python tests, 45 subtests and
three Node cases; XML reports zero failures/errors/skips. No live acceptance,
model, worker, message, GitHub write or service restart was executed here.

## One operator command to finish Phase A

Use a root Bash shell after independently confirming messaging quiescence. Do
not share a password or private task/approval JSON in chat. These commands copy
the reviewed preparation script to a root-private location, pin it, then run it.
It bundles only Phase A portions of HOST.md. It cannot invoke installation,
activation, a messaging endpoint or a worker. Existing preparation paths cause
a stop rather than an overwrite.

```bash
set -euo pipefail
test "$(id -u)" = 0
umask 077
test ! -e /root/alfred-fresh-v1-phase-a-prepare.sh
install -o root -g root -m 0600 \
  /home/alfred/alfred-development-lab/milestone2/task-a/development_challenge/PHASE_A_PREPARE.sh \
  /root/alfred-fresh-v1-phase-a-prepare.sh
printf '%s  %s\n' \
  dcc6395369f16ae844fea26d131449e688b232943c16843e2a61f3804a0d0edb \
  /root/alfred-fresh-v1-phase-a-prepare.sh | sha256sum -c -
bash /root/alfred-fresh-v1-phase-a-prepare.sh --operator-quiescence-confirmed
```

Expected final line:

```text
PHASE_A_PREPARED_HELD: release and protected evidence verified; no code installed; no services restarted.
```

The resulting protected review directory is
`/root/alfred-fresh-v1-development-handoff-1-review`; the preserved checksums are
`preserved.sha256`. The runtime backup is deliberately not created until the
separately approved installation transaction backs up all seven mapped files.
Return the final status or concise failure message, not private evidence bodies.
Any failure means keep PAUSE and stop; do not delete/rewrite original evidence,
relax permissions or retry T-0003.

The script passed shell syntax and its missing-quiescence guard checks. Its
mutating root branch was **not** executed. The fixed corrective archive and its
manifest are unchanged; this preparation script is an external operator aid.

## Required next approvals

Only after root Phase A succeeds, request explicit **Phase B file-installation
approval for the seven destinations in HOST.md**, with PAUSE retained. Do not
interpret it as approval to restart services or run a live acceptance task.

Phase C separately requires approval for Intake/Photon restart **including the
existing systemd-propagated Hermes restart**. Phase D separately requires live
acceptance authorization and genuine owner iMessages/approvals. T-0003 remains
held in every phase; no approval or result is backfilled.

No production runtime file, policy, credential, historical record or service
state was changed during this preparation pass.
