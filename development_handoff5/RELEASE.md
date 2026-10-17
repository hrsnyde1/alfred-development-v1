# handoff.5 release pins and root commands

Staging review artifact. Built by `development_handoff5/build_release.py`.
`--reproduce` rebuilds it byte for byte. The why and how are in
[HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.5.tar.gz` | `f34e67ccc2d320b808eefc36a38e1aa5f9d62a0adc33912e66c3bf0b28bf7d06` |
| Release `MANIFEST.sha256` (11 payload files) | `070323b23736689da01f451b1202f9abbad41008359fd20569f869ebc1111cee` |
| Release `development_handoff5/install_patch.py` | `aca0374f563db6c873a99eab4960a88ef3623d4993b43a5dd8f2bb76387d6092` |

Staging evidence:
- **Release tests:** `staging-tests.xml` records 19 passed and 0 failed.
- **Mutation check:** 7 of the 8 role-view tests fail with the old `role.py`.
- **Gate 1:** all nine suites pass.
- **Dry run:** the real archive was extracted, and `verify` reported 11 files.
- **Sandbox preview:** `role_sandbox_preflight.py --with-gateway-view` returned
  `PASS` for all four roles (64 checks, 0 failures).

## Root commands

Run these in a root shell (`sudo -i`; the prompt ends in `#`). PAUSE must be
present. Stop at the first line that does not match, and paste the output.

**1. Copy, pin-check, extract and verify:**

```bash
cp /home/alfred/alfred-development-v1/dist/alfred-fresh-v1-1.0.1-development-handoff.5.tar.gz /root/ && echo 'f34e67ccc2d320b808eefc36a38e1aa5f9d62a0adc33912e66c3bf0b28bf7d06  /root/alfred-fresh-v1-1.0.1-development-handoff.5.tar.gz' | sha256sum -c - && install -d -m 0700 /root/alfred-fresh-v1-development-handoff-5-review && tar --no-same-owner --no-same-permissions -xzf /root/alfred-fresh-v1-1.0.1-development-handoff.5.tar.gz -C /root/alfred-fresh-v1-development-handoff-5-review && R=/root/alfred-fresh-v1-development-handoff-5-review/alfred-fresh-v1-1.0.1-development-handoff.5 && echo "aca0374f563db6c873a99eab4960a88ef3623d4993b43a5dd8f2bb76387d6092  $R/development_handoff5/install_patch.py" | sha256sum -c - && /usr/bin/python3 -I -B $R/development_handoff5/install_patch.py verify --release $R --manifest 070323b23736689da01f451b1202f9abbad41008359fd20569f869ebc1111cee && test -f /home/alfred/Alfred/gateway/PAUSE && echo PAUSE_OK && test ! -e /root/alfred-fresh-v1-development-handoff-5-backup && echo BACKUP_ABSENT
```

Expect two `OK` lines, `{"files": 11}`, `PAUSE_OK` and `BACKUP_ABSENT`.

**2. Install, reload unit definitions (no restart), verify and run the preflight
against the installed unit:**

```bash
R=/root/alfred-fresh-v1-development-handoff-5-review/alfred-fresh-v1-1.0.1-development-handoff.5; /usr/bin/python3 -I -B $R/development_handoff5/install_patch.py install --release $R --manifest 070323b23736689da01f451b1202f9abbad41008359fd20569f869ebc1111cee --backup /root/alfred-fresh-v1-development-handoff-5-backup 2>&1 | tee /root/handoff-5.log; echo "HANDOFF5_EXIT=${PIPESTATUS[0]}" | tee -a /root/handoff-5.log; systemctl daemon-reload && sha256sum -c $R/development_handoff5/installed-after.sha256 && cd /home/alfred/alfred-development-v1 && /usr/bin/python3 -I -B verification/role_sandbox_preflight.py && test -f /home/alfred/Alfred/gateway/PAUSE && echo PAUSE_STILL_SET
```

Expect all of these:
- `INSTALLED_HELD` and `HANDOFF5_EXIT=0`;
- two `OK` lines;
- four role lines with `"failures": []`;
- `"overall": "PASS"`;
- `PAUSE_STILL_SET`.

There is no `--with-gateway-view` flag this time: the preflight now tests the
installed unit itself.

**3. Gate 6, T-0007:** resume with

```bash
rm -f /home/alfred/Alfred/gateway/PAUSE
```

Then send a fresh request from your phone and reply in thread to each approval.
