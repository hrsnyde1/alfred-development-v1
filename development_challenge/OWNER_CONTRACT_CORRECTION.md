# Owner-contract correction — development-handoff.2

Staging artifact only. Nothing was installed, no service was touched and no host
permission was changed. Phases B, C and D still each need their own approval.

## Defect

The pinned handoff.1 installer (`install_patch.py`, SHA-256 `cee25c92…629f`)
checks every unchanged dependency with `checked()`, and `checked()` requires
`st_uid == os.geteuid()`. A root installation therefore requires all seven
dependencies to be root-owned. On the host, the unchanged Photon dependency

```text
/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/index.mjs
```

is `alfred:alfred` (UID 1000), mode 0644, one link, and its digest matches the
pin `ef019d1d…b8e4` exactly. So Phase A and the installer refused a correct
file. `PHASE_A_PREPARE.sh` and `phase_a_continue.py` enforced the same root-only
rule. This is a contract mismatch, not drifted content.

## Correction

One explicit expected-owner exception, applied identically in all three tools:

| Tool | Change |
| --- | --- |
| `install_patch.py` | `DEPENDENCY_OWNERS = {…/index.mjs: "alfred"}`. `checked()` takes an expected UID. `install()` passes `dependency_uid(name)`, which is the installer's own UID for every other dependency. |
| `phase_a_continue.py` | `installed()` expects the alfred UID for that one pinned path and the caller's UID (root) for the other 13. Release name, paths and counts move to handoff.2. |
| `PHASE_A_PREPARE.sh` | The root verification loop uses `owners.get(name, 0)` for the same single path. The Developer inventory, activation marker and policy keep their unconditional `st_uid==0` checks. |

The following do **not** change:

- The exempted file must still be a regular, single-link file with no group or
  other write permission, and its digest must match exactly. Only its expected
  owner changes.
- The exception is limited to unchanged dependencies. An import-time guard
  refuses any exception that names one of the seven install destinations, the
  baseline files, or a path outside the dependency pins.
- If `alfred` resolves to UID 0, the exception is refused.
- The owner must be **exactly** the alfred UID. A root-owned or other-owned
  `index.mjs` is now rejected.
- The installer only reads `index.mjs`. It never writes, backs up or restores it,
  and no host ownership or permission changes.
- Every destination, the baseline files and all other dependencies still require
  installer (root) ownership. Rollback backup checks are unchanged.

Residual risk, accepted by naming the owner explicitly: `alfred` can rewrite
`index.mjs`. The digest check proves the bytes at verification time, not later.
This was already true on the host. The correction makes the existing trust
explicit and does not widen it.

## Payload delta from handoff.1

- `development_challenge/install_patch.py`: the correction above.
- `development_challenge/test-selection.txt`: adds the owner-contract tests.
- `tests/test_handoff_dependency_owner_contract.py`: new tests (below).
- `development_challenge/OWNER_CONTRACT_CORRECTION.md`: this file.

The other 20 payload files are byte-identical to handoff.1, so the payload is 23
files instead of 21. `REPORT.md`, `TESTS.md` and `staging-tests.xml` are
unchanged historical evidence from the handoff.1 host run. The selection has
**not** been rerun on the host for handoff.2.

## Tests

`tests/test_handoff_dependency_owner_contract.py` models ownership with
monkeypatched `lstat`/`fstat` and `pwd`. It never runs `chown` or `sudo` and never
touches the host. It covers:

- The pinned handoff.1 installer still rejects alfred and accepts root
  (regression evidence for the defect).
- The corrected installer accepts the alfred-owned index and rejects root, 1001
  and 65534 as owners.
- All six other dependencies still reject an alfred owner.
- A wrong digest, group write, other write or a second hard link is still
  refused with the right owner.
- An `alfred` account that maps to UID 0 is refused.
- The full install transaction on a disposable root succeeds with an
  alfred-owned index and leaves that index byte-identical. Repeatable rollback
  restores the exact tree. An installer-owned index is refused before any write
  or backup.
- Phase A `installed()` accepts the alfred-owned index, rejects an
  installer-owned index, and rejects an alfred owner on any other pin.
- The prepare script contains exactly one exception, and its remaining root
  checks are present.

Local result (macOS, Python 3.12): **23 passed, 2 skipped**. The two transaction
tests need a Linux `/tmp` fixture root. With a scratch-only shim that relaxes
only that path check, all **25 passed**. `ruff check` and `ruff format --check`
pass on the changed Python files. The rest of the host selection was not run
here, because it needs the Linux host, the Gateway source and the installed
Photon dependency bytes.
