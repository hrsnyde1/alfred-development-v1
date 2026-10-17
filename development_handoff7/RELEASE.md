# handoff.7 release pins and root commands

Staging review artifact. Built by `development_handoff7/build_release.py`.
`--reproduce` rebuilds it byte for byte. The why and how are in
[HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.7.tar.gz` | `f81eb4bfacd35998b24f27513604279454bf986202e48b4c17c17d2c4123657b` |
| Release `MANIFEST.sha256` (9 payload files) | `3a7bd04412da83c53fdb00526ef404e32a6c0698ea707f29c154d61fe1f9198d` |
| Release `development_handoff7/install_patch.py` | `91f07848303f159c693a8a7b52460dfdb8069247e5721113e7301702b489c7e7` |
| Installed `host.py` after | `7158c6276829f43fdce48db572d86d76589f8ac6eebb09f6087280bd835c5751` |

Staging evidence:
- **Release tests:** `staging-tests.xml` records 21 passed and 0 failed. All 10
  clone tests fail with the old `host.py`.
- **Gate 1:** all eleven suites pass.
- **Reproduction:** T-0008's real final worktree, with
  `GIT_TEST_ASSUME_DIFFERENT_OWNER=1`. The old single entry fails, and the
  three entries succeed for both the snapshot and the bare clone.
- **Dry run:** the real archive was extracted, and `verify` reported 9 files.
- **Live preconditions:** checked read-only as alfred, with 0 mismatches.

## Root commands

Run these in a root shell (`sudo -i`; the prompt ends in `#`). Stop at the
first line that does not match, and paste the output.

**1. Pause, copy, pin-check, extract and verify:**

```bash
touch /home/alfred/Alfred/gateway/PAUSE && cp /home/alfred/alfred-development-v1/dist/alfred-fresh-v1-1.0.1-development-handoff.7.tar.gz /root/ && echo 'f81eb4bfacd35998b24f27513604279454bf986202e48b4c17c17d2c4123657b  /root/alfred-fresh-v1-1.0.1-development-handoff.7.tar.gz' | sha256sum -c - && install -d -m 0700 /root/alfred-fresh-v1-development-handoff-7-review && tar --no-same-owner --no-same-permissions -xzf /root/alfred-fresh-v1-1.0.1-development-handoff.7.tar.gz -C /root/alfred-fresh-v1-development-handoff-7-review && R=/root/alfred-fresh-v1-development-handoff-7-review/alfred-fresh-v1-1.0.1-development-handoff.7 && echo "91f07848303f159c693a8a7b52460dfdb8069247e5721113e7301702b489c7e7  $R/development_handoff7/install_patch.py" | sha256sum -c - && /usr/bin/python3 -I -B $R/development_handoff7/install_patch.py verify --release $R --manifest 3a7bd04412da83c53fdb00526ef404e32a6c0698ea707f29c154d61fe1f9198d && test ! -e /root/alfred-fresh-v1-development-handoff-7-backup && echo BACKUP_ABSENT
```

Expect two `OK` lines, `{"files": 9}` and `BACKUP_ABSENT`.

**2. Install, verify and run the full sandbox preflight, including root's
snapshot clone:**

```bash
R=/root/alfred-fresh-v1-development-handoff-7-review/alfred-fresh-v1-1.0.1-development-handoff.7; /usr/bin/python3 -I -B $R/development_handoff7/install_patch.py install --release $R --manifest 3a7bd04412da83c53fdb00526ef404e32a6c0698ea707f29c154d61fe1f9198d --backup /root/alfred-fresh-v1-development-handoff-7-backup 2>&1 | tee /root/handoff-7.log; echo "HANDOFF7_EXIT=${PIPESTATUS[0]}" | tee -a /root/handoff-7.log; sha256sum -c $R/development_handoff7/installed-after.sha256 && cd /home/alfred/alfred-development-v1 && /usr/bin/python3 -I -B verification/role_sandbox_preflight.py && test -f /home/alfred/Alfred/gateway/PAUSE && echo PAUSE_STILL_SET
```

Expect all of these:
- `INSTALLED_HELD` and `HANDOFF7_EXIT=0`;
- one `OK` line;
- five lines with `"failures": []`: the four roles and
  `root (snapshot clone)`;
- `"overall": "PASS"`;
- `PAUSE_STILL_SET`.

**3. Gate 6, T-0009:** resume with

```bash
rm -f /home/alfred/Alfred/gateway/PAUSE
```

Then send a fresh request from your phone and reply in thread to each approval.
