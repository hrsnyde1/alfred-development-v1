# Deployment status

## Correction staged for review — development-handoff.2 (not installed)

The owner-contract mismatch below has a staged correction:
[OWNER_CONTRACT_CORRECTION.md](OWNER_CONTRACT_CORRECTION.md). The unchanged
Photon `index.mjs` must be owned by the alfred UID, match its exact digest and
have no group/other write. Everything else still requires root. Nothing was
installed and no host ownership was changed. **This supersedes the handoff.1
pins and the continuation command further down.**

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.2.tar.gz` | `0f44351cca7ff57d15efc0d535c1a479a8db7ad36ea69506eafb34e7bb264c6f` |
| Release `MANIFEST.sha256` (23 payload files) | `4083213e209cbdbeec41de9837f962d0a9c9d3ac3bc53deec9cd0dc7f1a48bfd` |
| Release `development_challenge/install_patch.py` | `f88b3f8ce01534ff256ff3773ee01be6e6df005b97156a62203215492981133d` |
| `development_challenge/PHASE_A_PREPARE.sh` | `8ae5244a94cf2e51a5c19492c8ea80bd6ad8178cefc1763c621677164a1cc95c` |
| `development_challenge/phase_a_continue.py` | `9836add1c2fd42c6f56f15e4fdc0effa27f5a4455d767e44fa5426dccd5c9778` |

`build_handoff_release.py --reproduce` rebuilds the pinned handoff.1 archive
byte-for-byte (`4cd5448e…75b9`). That is how the handoff.2 build is shown to
follow the same process. handoff.2 uses new `/root/…-handoff-2-*` paths, so the
existing handoff.1 review directory is left alone and does not block
preparation.

After review approval, and after the operator independently confirms messaging
quiescence, Phase A runs as in [PHASE_A_STATUS.md](PHASE_A_STATUS.md) with the
new prepare-script pin:

```bash
set -euo pipefail
test "$(id -u)" = 0
umask 077
test ! -e /root/alfred-fresh-v1-phase-a-prepare.sh || cmp -s \
  /home/alfred/alfred-development-lab/milestone2/task-a/development_challenge/PHASE_A_PREPARE.sh \
  /root/alfred-fresh-v1-phase-a-prepare.sh
install -o root -g root -m 0600 \
  /home/alfred/alfred-development-lab/milestone2/task-a/development_challenge/PHASE_A_PREPARE.sh \
  /root/alfred-fresh-v1-phase-a-prepare.sh
printf '%s  %s\n' \
  8ae5244a94cf2e51a5c19492c8ea80bd6ad8178cefc1763c621677164a1cc95c \
  /root/alfred-fresh-v1-phase-a-prepare.sh | sha256sum -c -
bash /root/alfred-fresh-v1-phase-a-prepare.sh --operator-quiescence-confirmed
```

The existing `/root/alfred-fresh-v1-phase-a-prepare.sh` holds the handoff.1
script. Read it before replacing it, and keep a copy as evidence. The `cmp`
line above deliberately stops when that file differs, so it is never silently
overwritten. If preparation is interrupted after the review directory exists,
resume with the continuation, pinned to `9836add1…9778`. Phases B, C and D
still each need their own approval.

---

# Inspection — 2026-10-17 00:39 UTC (handoff.1)

## BLOCKED in Phase A

No preservation baseline, installation, service restart, task operation, send or
publication was executed. PAUSE remains present. Phases B/C were not entered;
`PHASE_A_PREPARED_HELD`, `INSTALLED_HELD` and `LIVE_READY_FOR_ACCEPTANCE` are not
verified host outcomes.

### Confirmed current preflight failure

The unchanged Photon dependency:

```text
/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/index.mjs
```

is **alfred:alfred (UID/GID 1000), mode 0644, regular, single link**. Its bytes
match the pinned SHA-256 exactly:

```text
ef019d1d50e4ca680aede49276181f8eff8d396d9b7c22a73bb5da2b2d7bb8e4
```

The pinned `install_patch.py` sends every unchanged dependency through
`checked()`, which requires `st_uid == os.geteuid()`. A root installation
therefore rejects this file before backup creation or runtime replacement.
`PHASE_A_PREPARE.sh` and `phase_a_continue.py` also require it to be root-owned.
This is a metadata/contract mismatch, not a content-hash mismatch.

All other 13 pinned runtime/dependency files have matching bytes, root ownership,
single links and no group/other write permissions. The prior PHASE_A_STATUS.md
claim that all runtime/dependency ownership checks passed is contradicted by
this direct host inspection; do not rely on that claim for deployment.

This **does not establish the historical stopping condition**. In the original
preparation script, the all-root dependency check occurs *after* creation of
`preserved.sha256`. It cannot by itself explain the earlier reported absence of
that file. The original error/trace or root inspection of the intervening
preflights is still required. The original script must not be replayed: its
existing-archive/review-directory guard necessarily blocks initialization now.

### Root authentication unavailable

The session runs as alfred (UID 1000). Outside the filesystem sandbox,
`sudo -n -l` returned `sudo: a password is required`. `/root` paths cannot be
inspected. No password, permission bypass or root action was attempted.

## Verified actual host observations

- Staged archive, manifest, installer and continuation hashes match their pins;
  all 21 payload files and 22 archive members agree with the staged release.
- All 14 installed content hashes match; ownership passes for 13, with the
  unchanged Photon index exception above. All 29 installed Developer files
  verify against the pinned installed inventory, including their protection.
- Gateway, Evidence, executor and all three QA execution services are loaded,
  inactive/dead, with MainPID and ControlPID zero.
- Intake PID 439206, Photon PID 140714, Hermes PID 454732 are active/running.
  Gateway/Evidence timers are active/waiting. Hermes still requires Photon.
- PAUSE remains alfred:alfred 0664, empty. Developer activation marker remains
  root:root 0644. Canonical policy remains root:root 0600; its private contents
  were not read in this session.
- T-0003 context, CTO plan and canonical spec match their previously reviewed
  hashes. Frozen baseline and scope are unchanged. Original attempt sizes and
  nanosecond mtimes match the reviewed observations. No challenge result exists.
  Root-private attempt bytes still need the protected check.
- T-0003 job SHA-256:
  `2a0ec905a71be607b2166639c742fcfdf2c7b420b62e9035be5746c4f71a84bc`.
  Its request route is bound through `job.request_id`, not `task_id` (route
  records intentionally precede task allocation). Project, configured owner,
  DM, Photon observation UID, distinct confirmation/request events and native
  reply target validate. Route SHA-256:
  `f0311e1e5270ccdf37f15cacdec261911571fa388c60d2629f8776cdfb88fd8c`.
  These are current observations; comparison with protected recovery bindings
  still requires root access.
- No pending development/publication records were found. This does not prove
  Intake's in-memory conversation state is empty; independent operator
  confirmation of messaging quiescence remains mandatory.

## Tested stopping behavior

- Existing Phase A continuation: **31 tests passed** again.
- New `tests/test_handoff_dependency_owner_contract.py`: **2 tests passed**.
  They load the exact pinned installer and model root caller/owner metadata on
  disposable bytes. UID 1000 fails despite the correct digest; UID 0 passes.
  No real chown or privileged operation occurs.
- Ruff checks pass. No production source or immutable release was changed.

## One authenticated Phase A command

After independently confirming messaging quiescence, this single operator
command runs the existing pinned continuation from hash-verified bytes. It
cannot install code, restart services, retry T-0003 or bypass a preflight. Under
the observed host state it will stop at the ownership checkpoint unless an
earlier protected check fails. It does **not** authorize changing that ownership
or claiming Phase A passed. Its output supplies the first protected refusal.

```bash
sudo /usr/bin/python3 -I -B -c '
import hashlib, sys
p = "/home/alfred/alfred-development-lab/milestone2/task-a/development_challenge/phase_a_continue.py"
b = open(p, "rb").read()
if hashlib.sha256(b).hexdigest() != "c5b088b4e378f247c4df2e4018e943768591b2ca4c12beb820339076d7e1a08b":
    raise SystemExit("BLOCKED: continuation_sha256")
sys.argv = [p, "--operator-quiescence-confirmed"]
exec(compile(b, p, "exec"), {"__name__": "__main__", "__file__": p})
'
```

Return only the failure checkpoint/status and, if available, the original
preparation error. Do not share private evidence bodies or credentials.

## Minimum corrective decision required

The current pinned installation contract and current host ownership cannot
both pass unchanged. Root authentication alone is insufficient. Under the
present instructions, do not chown Photon index, skip ownership checks, edit
protected artifacts or replace the approved archive/manifest pins.

The smallest candidate for separate review is an explicit expected-owner
contract for this **one unchanged Photon dependency**, enforcing its existing
alfred UID and exact digest while retaining root ownership checks for every
mapped destination and protected dependency. That would require a tested,
reviewed installer/continuation correction and new release pins; it has not
been implemented or installed. Alternatively, changing host ownership requires
an explicit exception to the requirement to preserve production permissions.
Neither decision is inferred from installation authorization.

Keep PAUSE, all attempts and every historical record intact. Phase B approval
must wait until the contract mismatch is resolved and actual Phase A completion
is verified. Phase C still requires its separate restart approval covering
Intake, Photon and the existing Hermes dependency impact.
